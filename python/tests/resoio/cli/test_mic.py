"""Tests for the ``resoio mic`` subcommand."""

import asyncio
import json
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

# Mirror the CLI's internal defaults so the assertions read naturally.
_CHUNK_SAMPLES = 1024
_WARMUP_CHUNKS = 5
_SAMPLE_RATE = 48000

# A `unix_nanos` value past 2^53 — exercises that the end-of-stream summary
# round-trips through json without the precision loss a float would suffer.
_BIG_UNIX_NANOS = 1_700_000_000_123_456_789


class _RecordingMicrophone(MicrophoneBase):
    """In-process fake that captures every received frame."""

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


class _FixedSummaryMicrophone(MicrophoneBase):
    """Fake that returns a fixed, fully-populated end-of-stream summary.

    Decouples the summary-output assertions from frame arithmetic: every
    field is a distinct, non-zero, known constant so a transposed or
    dropped field would surface, and ``unix_nanos`` is a large 64-bit
    value that pins exact round-tripping.
    """

    summary = _WireSummary(
        received_frames=3,
        received_samples=3072,
        dropped_frames=1,
        unix_nanos=_BIG_UNIX_NANOS,
    )

    async def stream_audio(
        self, messages: AsyncIterator[MicrophoneAudioFrame]
    ) -> _WireSummary:
        async for _ in messages:
            pass
        return self.summary


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
    """Write a WAV file via stdlib :mod:`wave`.

    Stdlib ``wave`` always writes format tag ``1`` (PCM); the CLI reader
    treats ``sampwidth == 4`` as float32 by convention — that lossless
    correspondence is what these tests exercise.
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
    socket_path = tmp_path / "rio-mic.sock"
    wav_path = tmp_path / "mono.wav"

    # Ramp pattern → every position has a distinct value, so a
    # reorder or duplicate would surface on the array-equal check.
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
    socket_path = tmp_path / "rio-mic.sock"
    wav_path = tmp_path / "stereo.wav"

    # L=0.5, R=-0.1 → mean 0.2 (exactly representable in float32).
    total_samples = 2 * _CHUNK_SAMPLES
    left = np.full(total_samples, 0.5, dtype=np.float32)
    right = np.full(total_samples, -0.1, dtype=np.float32)
    interleaved = np.stack([left, right], axis=1)
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
        np.testing.assert_allclose(decoded, 0.2, rtol=0, atol=1e-7)
    finally:
        server.close()
        await server.wait_closed()


async def test_wav_input_int16_normalized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    socket_path = tmp_path / "rio-mic.sock"
    wav_path = tmp_path / "int16.wav"

    # Anchors verify the 1/32768 normalisation:
    #   +16384 → +0.5, -16384 → -0.5, 0 → 0.0.
    total_samples = _CHUNK_SAMPLES
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
        assert float(decoded.min()) >= -1.0
        assert float(decoded.max()) <= 1.0
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
    socket_path = tmp_path / "rio-mic.sock"
    wav_path = tmp_path / "44k.wav"

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
        # Surface both the offending and canonical rates so the fix is unambiguous.
        assert "44100" in captured.err
        assert "48000" in captured.err
        assert fake.received == []
    finally:
        server.close()
        await server.wait_closed()


async def test_wav_input_channels_gt2_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    socket_path = tmp_path / "rio-mic.sock"
    wav_path = tmp_path / "six.wav"

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
        assert "6" in captured.err
        assert fake.received == []
    finally:
        server.close()
        await server.wait_closed()


# ---------------------------------------------------------------------------
# stdin pipe input
# ---------------------------------------------------------------------------


class _StdinShim:
    """Minimal ``sys.stdin`` replacement exposing only ``.buffer.read``."""

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
    socket_path = tmp_path / "rio-mic.sock"

    total_samples = 2 * _CHUNK_SAMPLES
    payload = np.linspace(-0.25, 0.25, total_samples, dtype=np.float32)
    raw_bytes = payload.tobytes()

    fake = _RecordingMicrophone()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        # Swap sys.stdin so the CLI reads canned bytes instead of pytest's captured fd.
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
# WAV input — real-time pacing
# ---------------------------------------------------------------------------


async def test_wav_input_paces_after_warmup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Streaming time must reflect paced emission, not a burst send."""
    socket_path = tmp_path / "rio-mic.sock"
    wav_path = tmp_path / "paced.wav"

    n_chunks = _WARMUP_CHUNKS + 10
    total_samples = n_chunks * _CHUNK_SAMPLES
    payload = np.zeros(total_samples, dtype=np.float32)
    _write_wav(wav_path, payload)

    fake = _RecordingMicrophone()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(["mic", "-i", str(wav_path), "--no-wait"])
        start = time.monotonic()
        rc = await _amain(args)
        elapsed = time.monotonic() - start
        assert rc == 0
        assert len(fake.received) == n_chunks

        # Paced phase is the tail after warmup. Lower bound with slack
        # absorbs scheduling jitter while still failing if pacing was
        # removed entirely (in which case elapsed ≈ a few ms).
        paced_chunks = n_chunks - _WARMUP_CHUNKS
        expected_paced_s = paced_chunks * _CHUNK_SAMPLES / _SAMPLE_RATE
        assert elapsed >= expected_paced_s * 0.7, (
            f"WAV mode emitted in {elapsed * 1000:.1f} ms — expected pacing "
            f"to take ≥ {expected_paced_s * 700:.1f} ms"
        )
    finally:
        server.close()
        await server.wait_closed()


# ---------------------------------------------------------------------------
# --duration
# ---------------------------------------------------------------------------


async def test_duration_clips_stream(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """``--duration`` truncates the wire output at a chunk-aligned boundary.

    4-chunk WAV + ``--duration 0.05`` (2400 samples) → 2 full chunks
    (2048 samples ≤ 2400); the partial third is dropped, not padded.
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
        assert len(fake.received) == 2
        assert all(f.sample_count == _CHUNK_SAMPLES for f in fake.received)
    finally:
        server.close()
        await server.wait_closed()


# ---------------------------------------------------------------------------
# argparse surface
# ---------------------------------------------------------------------------


def test_mic_input_defaults_to_stdin():
    parser = _build_parser()
    args = parser.parse_args(["mic", "--no-wait"])
    assert args.input == "-"


def test_mic_no_wait_flag_present(tmp_path: Path):
    parser = _build_parser()
    args = parser.parse_args(["mic", "-i", str(tmp_path / "x.wav"), "--no-wait"])
    assert args.no_wait is True
    assert args.input == str(tmp_path / "x.wav")
    assert args.duration is None


def test_mic_format_defaults_to_human():
    """``mic`` carries ``--format`` and defaults to human output."""
    parser = _build_parser()
    args = parser.parse_args(["mic", "--no-wait"])
    assert args.format == "human"


def test_mic_format_accepts_json():
    parser = _build_parser()
    args = parser.parse_args(["mic", "--no-wait", "--format", "json"])
    assert args.format == "json"


def test_mic_unknown_format_is_a_parse_error():
    """``--format`` is a fixed choice set; an unknown value exits 2 at parse."""
    with pytest.raises(SystemExit) as excinfo:
        _build_parser().parse_args(["mic", "--no-wait", "--format", "yaml"])
    assert excinfo.value.code == 2


# ---------------------------------------------------------------------------
# End-of-stream summary — the command result, on STDOUT in both modes
# ---------------------------------------------------------------------------


async def test_summary_human_goes_to_stdout_not_stderr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """The summary is the command result, so human mode writes it to stdout.

    Same ``key=value`` content as before; only the stream changes
    (previously stderr). stderr stays empty on a clean run.
    """
    socket_path = tmp_path / "rio-mic.sock"

    fake = _FixedSummaryMicrophone()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        shim: Any = _StdinShim(b"")
        monkeypatch.setattr("sys.stdin", shim)
        args = _build_parser().parse_args(["mic", "-i", "-", "--no-wait"])
        rc = await _amain(args)
        assert rc == 0

        captured = capsys.readouterr()
        assert captured.out.strip() == (
            f"received_frames=3 received_samples=3072 "
            f"dropped_frames=1 unix_nanos={_BIG_UNIX_NANOS}"
        )
        assert captured.err == ""
    finally:
        server.close()
        await server.wait_closed()


async def test_summary_json_payload_on_stdout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """``--format json`` emits the summary as the documented json object.

    Field set and snake_case names mirror ``MicrophoneStreamSummary``;
    the large ``unix_nanos`` round-trips through ``json.loads`` exactly.
    """
    socket_path = tmp_path / "rio-mic.sock"

    fake = _FixedSummaryMicrophone()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        shim: Any = _StdinShim(b"")
        monkeypatch.setattr("sys.stdin", shim)
        args = _build_parser().parse_args(
            ["mic", "-i", "-", "--no-wait", "--format", "json"]
        )
        rc = await _amain(args)
        assert rc == 0

        captured = capsys.readouterr()
        payload = json.loads(captured.out)
        assert payload == {
            "received_frames": 3,
            "received_samples": 3072,
            "dropped_frames": 1,
            "unix_nanos": _BIG_UNIX_NANOS,
        }
        # The 64-bit timestamp must survive json exactly (no float coercion).
        assert payload["unix_nanos"] == _BIG_UNIX_NANOS
        assert captured.err == ""
    finally:
        server.close()
        await server.wait_closed()


async def test_summary_json_is_exactly_one_document(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """Stdout in json mode holds exactly one json document, nothing else."""
    socket_path = tmp_path / "rio-mic.sock"

    fake = _FixedSummaryMicrophone()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        shim: Any = _StdinShim(b"")
        monkeypatch.setattr("sys.stdin", shim)
        args = _build_parser().parse_args(
            ["mic", "-i", "-", "--no-wait", "--format", "json"]
        )
        rc = await _amain(args)
        assert rc == 0

        stdout = capsys.readouterr().out
        # A second document would make the buffer fail to parse as one value;
        # JSONDecoder.raw_decode then confirms nothing trails the first doc.
        decoder = json.JSONDecoder()
        _, end = decoder.raw_decode(stdout)
        assert stdout[end:].strip() == ""
    finally:
        server.close()
        await server.wait_closed()


async def test_input_format_error_json_keeps_stderr_and_emits_no_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """Format errors stay on stderr and map to rc=2 even with ``--format
    json``.

    The summary is the only stdout document; a rejected input never
    opens a stream, so stdout must be empty (no partial/empty json
    object).
    """
    socket_path = tmp_path / "rio-mic.sock"
    wav_path = tmp_path / "44k.wav"
    _write_wav(wav_path, np.zeros(_CHUNK_SAMPLES, dtype=np.float32), sample_rate=44100)

    fake = _FixedSummaryMicrophone()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(
            ["mic", "-i", str(wav_path), "--no-wait", "--format", "json"]
        )
        rc = await _amain(args)
        assert rc == 2

        captured = capsys.readouterr()
        assert captured.out == ""
        assert "44100" in captured.err
        assert "48000" in captured.err
    finally:
        server.close()
        await server.wait_closed()


# ---------------------------------------------------------------------------
# Sanity: the WAV header writer we use in tests is the inverse of the reader
# ---------------------------------------------------------------------------


def test_wav_test_helper_round_trips_mono_float32(tmp_path: Path):
    """If stdlib ``wave`` ever changes its 4-byte storage, fail here first.

    A regression in the test helper would silently invalidate every
    other WAV-input test in this file.
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
    assert struct.unpack("<f", raw[:4])[0] == pytest.approx(payload[0])
    np.testing.assert_array_equal(decoded, payload)
