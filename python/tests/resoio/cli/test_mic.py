"""Tests for the ``resoio mic`` subcommand.

Mirrors :mod:`tests.resoio.cli.test_record` (Speaker) but in the
opposite direction: a fake :class:`MicrophoneBase` server is started on
a tmp UDS, the CLI is driven via :func:`resoio.cli._amain`, and the
frames received by the fake are decoded back to assert wire-shape
integrity and the down-mix / normalisation paths.
"""

import asyncio
import struct
import time
import wave
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from grpclib.server import Server

from resoio._generated.resonite_io.v1 import (
    MicrophoneAudioFrame,
    MicrophoneBase,
    MicrophoneStreamSummary as _WireSummary,
)
from resoio.cli import _amain, _build_parser

# Mirror the CLI's internal default so the assertions read naturally.
_CHUNK_SAMPLES = 1024


class _RecordingMicrophone(MicrophoneBase):
    """In-process fake that captures every received frame for assertion.

    Tracks both the frames themselves (so the test can decode samples
    back from ``frame.samples``) and a deterministic summary tied to
    the captured count.
    """

    def __init__(self) -> None:
        self.received: list[MicrophoneAudioFrame] = []

    async def stream_audio(
        self, messages: AsyncIterator[MicrophoneAudioFrame]
    ) -> _WireSummary:
        async for frame in messages:
            self.received.append(frame)
        return _WireSummary(
            received_frames=len(self.received),
            received_samples=sum(f.sample_count for f in self.received),
            dropped_frames=0,
            unix_nanos=time.time_ns(),
        )


def _decode_samples(frames: list[MicrophoneAudioFrame]) -> np.ndarray:
    """Concatenate every frame's payload into a single 1-D float32 array."""
    if not frames:
        return np.empty(0, dtype=np.float32)
    parts = [np.frombuffer(f.samples, dtype=np.float32) for f in frames]
    return np.concatenate(parts)


def _write_wav(
    path: Path,
    samples: np.ndarray,
    *,
    sample_rate: int = 48000,
    sampwidth: int = 4,
    channels: int = 1,
) -> None:
    """Write a WAV file using stdlib :mod:`wave`.

    Defaults match the canonical wire format (48 kHz / mono / 4-byte
    samples). ``samples`` shape:

    * mono: ``(N,)`` (any dtype — converted by ``tobytes`` semantics
      below; callers supply the right dtype for ``sampwidth``)
    * stereo: ``(N, 2)`` interleaved on write

    Note: stdlib ``wave`` does not advertise ``WAVE_FORMAT_IEEE_FLOAT``
    in the header (it writes format tag ``1`` = PCM). The CLI reader
    treats ``sampwidth == 4`` as float32 by convention; that lossless
    correspondence is exactly what these tests exercise.
    """
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(sampwidth)
        wav.setframerate(sample_rate)
        wav.writeframes(samples.tobytes())


# ---------------------------------------------------------------------------
# WAV input — mono float32
# ---------------------------------------------------------------------------


async def test_wav_input_mono_float32(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """End-to-end: 3 full chunks of mono float32 WAV → 3 frames received."""
    socket_path = tmp_path / "rio-mic.sock"
    wav_path = tmp_path / "mono.wav"

    # Deterministic ramp: each sample equals its index / N so the
    # post-decoding comparison is exact.
    total_samples = 3 * _CHUNK_SAMPLES
    payload = np.arange(total_samples, dtype=np.float32) / float(total_samples)
    _write_wav(wav_path, payload)

    fake = _RecordingMicrophone()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(["mic", "-i", str(wav_path), "--no-wait"])
        rc = await _amain(args)
        assert rc == 0

        assert len(fake.received) == 3
        for i, frame in enumerate(fake.received):
            assert frame.frame_id == i
            assert frame.sample_count == _CHUNK_SAMPLES
            assert frame.unix_nanos > 0
        decoded = _decode_samples(fake.received)
        assert decoded.shape == (total_samples,)
        np.testing.assert_array_equal(decoded, payload)
    finally:
        server.close()
        await server.wait_closed()


async def test_wav_input_stereo_downmix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Stereo WAV is averaged ``(L+R)/2`` into mono before being sent."""
    socket_path = tmp_path / "rio-mic.sock"
    wav_path = tmp_path / "stereo.wav"

    # Build a stereo signal where L=0.5 and R=-0.1 everywhere. Down-mix
    # mean = 0.2 — a single constant value makes the assertion exact.
    total_samples = 2 * _CHUNK_SAMPLES
    left = np.full(total_samples, 0.5, dtype=np.float32)
    right = np.full(total_samples, -0.1, dtype=np.float32)
    interleaved = np.stack([left, right], axis=1)  # (N, 2)
    _write_wav(wav_path, interleaved, channels=2)

    fake = _RecordingMicrophone()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(["mic", "-i", str(wav_path), "--no-wait"])
        rc = await _amain(args)
        assert rc == 0

        assert len(fake.received) == 2
        decoded = _decode_samples(fake.received)
        assert decoded.shape == (total_samples,)
        # (0.5 + -0.1) / 2 = 0.2 exactly representable in float32.
        np.testing.assert_allclose(decoded, 0.2, rtol=0, atol=1e-7)
    finally:
        server.close()
        await server.wait_closed()


async def test_wav_input_int16_normalized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Int16 mono WAV → samples are normalised to float32 in ``[-1, 1]``."""
    socket_path = tmp_path / "rio-mic.sock"
    wav_path = tmp_path / "int16.wav"

    total_samples = _CHUNK_SAMPLES
    # Mix three known int16 anchors so normalisation is verifiable:
    # +16384 → +0.5, -16384 → -0.5, 0 → 0.0.
    payload_i16 = np.full(total_samples, 16384, dtype=np.int16)
    payload_i16[100] = -16384
    payload_i16[200] = 0
    _write_wav(wav_path, payload_i16, sampwidth=2)

    fake = _RecordingMicrophone()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(["mic", "-i", str(wav_path), "--no-wait"])
        rc = await _amain(args)
        assert rc == 0

        assert len(fake.received) == 1
        decoded = _decode_samples(fake.received)
        assert decoded.shape == (total_samples,)
        # All samples must land in [-1.0, 1.0] after normalisation.
        assert float(decoded.min()) >= -1.0
        assert float(decoded.max()) <= 1.0
        # Anchor checks (division by 32768.0):
        # 16384 / 32768 = 0.5, -16384 / 32768 = -0.5.
        assert decoded[0] == pytest.approx(0.5)
        assert decoded[100] == pytest.approx(-0.5)
        assert decoded[200] == 0.0
    finally:
        server.close()
        await server.wait_closed()


# ---------------------------------------------------------------------------
# WAV input — error paths
# ---------------------------------------------------------------------------


async def test_wav_input_sample_rate_mismatch_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """Sample rate ≠ 48000 → rc=2 + stderr message mentioning the rate."""
    socket_path = tmp_path / "rio-mic.sock"
    wav_path = tmp_path / "44k.wav"

    # 44100 Hz mono float32 — same data, only the header rate differs.
    payload = np.zeros(_CHUNK_SAMPLES, dtype=np.float32)
    _write_wav(wav_path, payload, sample_rate=44100)

    fake = _RecordingMicrophone()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(["mic", "-i", str(wav_path), "--no-wait"])
        rc = await _amain(args)
        assert rc == 2
        captured = capsys.readouterr()
        # Mentions the offending sample rate so the user can grep for it.
        assert "44100" in captured.err
        # And mentions the canonical rate so the fix is unambiguous.
        assert "48000" in captured.err
        # No frames should have reached the server.
        assert fake.received == []
    finally:
        server.close()
        await server.wait_closed()


async def test_wav_input_channels_gt2_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """> 2 channels (e.g. 5.1) → rc=2 with a stderr message."""
    socket_path = tmp_path / "rio-mic.sock"
    wav_path = tmp_path / "six.wav"

    # 6 channels of zeros — we only care about the header's nchannels.
    n = 256
    payload = np.zeros((n, 6), dtype=np.float32)
    _write_wav(wav_path, payload, channels=6)

    fake = _RecordingMicrophone()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(["mic", "-i", str(wav_path), "--no-wait"])
        rc = await _amain(args)
        assert rc == 2
        captured = capsys.readouterr()
        # Mentions the offending channel count.
        assert "6" in captured.err
        assert fake.received == []
    finally:
        server.close()
        await server.wait_closed()


# ---------------------------------------------------------------------------
# stdin pipe input
# ---------------------------------------------------------------------------


class _StdinShim:
    """Minimal ``sys.stdin`` replacement exposing only ``.buffer.read``.

    The CLI consumes raw bytes through ``sys.stdin.buffer.read(n)``;
    feeding canned bytes via a class is simpler and more deterministic
    than spawning a subprocess or splicing an ``os.pipe`` fd.
    """

    def __init__(self, data: bytes) -> None:
        self.buffer = _StdinBuffer(data)


class _StdinBuffer:
    def __init__(self, data: bytes) -> None:
        self._data = data
        self._pos = 0

    def read(self, n: int) -> bytes:
        end = min(self._pos + n, len(self._data))
        out = self._data[self._pos : end]
        self._pos = end
        return out


async def test_stdin_pipe_raw_float32(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Raw float32 LE bytes on stdin → chunked into 1024-sample frames."""
    socket_path = tmp_path / "rio-mic.sock"

    total_samples = 2 * _CHUNK_SAMPLES
    payload = np.linspace(-0.25, 0.25, total_samples, dtype=np.float32)
    raw_bytes = payload.tobytes()

    fake = _RecordingMicrophone()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        # Swap sys.stdin in-place so the CLI's ``sys.stdin.buffer.read``
        # reads from our canned buffer instead of pytest's captured fd.
        shim: Any = _StdinShim(raw_bytes)
        monkeypatch.setattr("sys.stdin", shim)
        args = _build_parser().parse_args(["mic", "-i", "-", "--no-wait"])
        rc = await asyncio.wait_for(_amain(args), timeout=5.0)
        assert rc == 0
        assert len(fake.received) == 2
        decoded = _decode_samples(fake.received)
        assert decoded.shape == (total_samples,)
        np.testing.assert_array_equal(decoded, payload)
    finally:
        server.close()
        await server.wait_closed()


# ---------------------------------------------------------------------------
# --duration
# ---------------------------------------------------------------------------


async def test_duration_clips_stream(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """``--duration`` truncates the wire output at a chunk-aligned boundary.

    Input is a 4-chunk WAV (4096 samples ≈ 85 ms at 48 kHz). With
    ``--duration 0.05`` (= 50 ms = 2400 samples) we expect at most two
    full chunks (2 × 1024 = 2048 samples ≤ 2400); the partial third
    chunk is dropped rather than padded.
    """
    socket_path = tmp_path / "rio-mic.sock"
    wav_path = tmp_path / "long.wav"

    total_samples = 4 * _CHUNK_SAMPLES
    payload = np.zeros(total_samples, dtype=np.float32)
    _write_wav(wav_path, payload)

    fake = _RecordingMicrophone()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(
            ["mic", "-i", str(wav_path), "--duration", "0.05", "--no-wait"]
        )
        rc = await _amain(args)
        assert rc == 0
        # 0.05 s × 48 kHz = 2400 samples; floor(2400 / 1024) = 2 chunks.
        assert len(fake.received) == 2
        assert all(f.sample_count == _CHUNK_SAMPLES for f in fake.received)
    finally:
        server.close()
        await server.wait_closed()


# ---------------------------------------------------------------------------
# argparse surface
# ---------------------------------------------------------------------------


def test_mic_requires_input_argument(capsys: pytest.CaptureFixture[str]):
    """``-i`` is mandatory — argparse short-circuits with ``SystemExit(2)``."""
    parser = _build_parser()
    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["mic"])
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "--input" in err or "-i" in err


def test_mic_no_wait_flag_present(tmp_path: Path):
    """``--no-wait`` is the standard escape hatch from the bridge-ready loop."""
    parser = _build_parser()
    args = parser.parse_args(["mic", "-i", str(tmp_path / "x.wav"), "--no-wait"])
    assert args.no_wait is True
    assert args.input == str(tmp_path / "x.wav")
    assert args.duration is None


# ---------------------------------------------------------------------------
# Sanity: the WAV header writer we use in tests is the inverse of the reader
# ---------------------------------------------------------------------------


def test_wav_test_helper_round_trips_mono_float32(tmp_path: Path):
    """Regression guard: ``_write_wav`` + ``wave.open`` round-trip cleanly.

    If stdlib ``wave`` ever changes how it stores 4-byte samples this
    test fails first, ahead of every E2E test that depends on it.
    """
    path = tmp_path / "roundtrip.wav"
    payload = np.arange(_CHUNK_SAMPLES, dtype=np.float32) / float(_CHUNK_SAMPLES)
    _write_wav(path, payload)
    with wave.open(str(path), "rb") as wav:
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 4
        assert wav.getframerate() == 48000
        raw = wav.readframes(wav.getnframes())
    decoded = np.frombuffer(raw, dtype=np.float32)
    # struct round-trip uses native LE on every platform Resonite supports.
    assert struct.unpack("<f", raw[:4])[0] == pytest.approx(payload[0])
    np.testing.assert_array_equal(decoded, payload)
