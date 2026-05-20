"""Tests for the ``resoio record`` subcommand.

Mirrors :mod:`tests.resoio.cli.test_capture` (camera): a fake speaker
server is started on a tmp UDS, the CLI is driven via
:func:`resoio.cli._amain`, and the resulting WAV / raw PCM is read back
and compared against the deterministic samples emitted by the fake.
"""

import asyncio
import struct
import time
from collections.abc import AsyncIterator
from pathlib import Path

import numpy as np
import pytest
from grpclib.server import Server

from resoio._generated.resonite_io.v1 import (
    AudioFrame,
    SpeakerBase,
    SpeakerStreamRequest,
)
from resoio.cli import _amain, _build_parser

_SAMPLES_PER_FRAME = 128
_CHANNELS = 2


def _frame_samples(i: int) -> np.ndarray:
    """L=i, R=-i constant across the frame — deterministic byte content."""
    left = np.full(_SAMPLES_PER_FRAME, float(i), dtype=np.float32)
    right = np.full(_SAMPLES_PER_FRAME, -float(i), dtype=np.float32)
    return np.stack([left, right], axis=1)  # (N, 2)


def _make_finite_speaker(frame_count: int) -> type[SpeakerBase]:
    """Speaker that yields ``frame_count`` deterministic frames then ends."""

    class _FiniteSpeaker(SpeakerBase):
        async def stream_audio(
            self, message: SpeakerStreamRequest
        ) -> AsyncIterator[AudioFrame]:
            for i in range(frame_count):
                yield AudioFrame(
                    frame_id=i,
                    unix_nanos=time.time_ns(),
                    sample_count=_SAMPLES_PER_FRAME,
                    samples=_frame_samples(i).tobytes(),
                )

    return _FiniteSpeaker


def _make_infinite_speaker(interval_s: float = 0.01) -> type[SpeakerBase]:
    """Speaker that yields frames forever — used to exercise ``--duration``."""

    class _InfiniteSpeaker(SpeakerBase):
        async def stream_audio(
            self, message: SpeakerStreamRequest
        ) -> AsyncIterator[AudioFrame]:
            i = 0
            while True:
                yield AudioFrame(
                    frame_id=i,
                    unix_nanos=time.time_ns(),
                    sample_count=_SAMPLES_PER_FRAME,
                    samples=_frame_samples(i).tobytes(),
                )
                i += 1
                await asyncio.sleep(interval_s)

    return _InfiniteSpeaker


def _parse_wav_header(data: bytes) -> dict[str, int]:
    """Parse the fixed 44-byte WAV header into its numeric fields.

    The stdlib :mod:`wave` module rejects ``WAVE_FORMAT_IEEE_FLOAT``
    (format tag ``0x0003``), so the header is parsed directly with
    :mod:`struct`. The layout matches the writer's
    ``_build_placeholder_header()`` and is the public file format.
    """
    assert data[:4] == b"RIFF", data[:4]
    assert data[8:12] == b"WAVE", data[8:12]
    assert data[12:16] == b"fmt ", data[12:16]
    assert data[36:40] == b"data", data[36:40]
    (riff_size,) = struct.unpack("<I", data[4:8])
    (fmt_chunk_size,) = struct.unpack("<I", data[16:20])
    (format_tag,) = struct.unpack("<H", data[20:22])
    (channels,) = struct.unpack("<H", data[22:24])
    (sample_rate,) = struct.unpack("<I", data[24:28])
    (byte_rate,) = struct.unpack("<I", data[28:32])
    (block_align,) = struct.unpack("<H", data[32:34])
    (bits_per_sample,) = struct.unpack("<H", data[34:36])
    (data_size,) = struct.unpack("<I", data[40:44])
    return {
        "riff_size": riff_size,
        "fmt_chunk_size": fmt_chunk_size,
        "format_tag": format_tag,
        "channels": channels,
        "sample_rate": sample_rate,
        "byte_rate": byte_rate,
        "block_align": block_align,
        "bits_per_sample": bits_per_sample,
        "data_size": data_size,
    }


async def test_record_writes_wav_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """End-to-end: 3 frames → ``.wav`` → parse header + sample bytes."""
    socket_path = tmp_path / "rio.sock"
    out_path = tmp_path / "out.wav"
    frame_count = 3
    speaker = _make_finite_speaker(frame_count)
    server = Server([speaker()])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(
            [
                "record",
                "-o",
                str(out_path),
            ]
        )
        rc = await _amain(args)
        assert rc == 0

        data = out_path.read_bytes()
        header = _parse_wav_header(data)
        assert header["format_tag"] == 0x0003  # WAVE_FORMAT_IEEE_FLOAT
        assert header["channels"] == 2
        assert header["sample_rate"] == 48000
        assert header["bits_per_sample"] == 32
        assert header["block_align"] == 8
        assert header["byte_rate"] == 48000 * 8
        assert header["fmt_chunk_size"] == 16

        expected_payload_bytes = frame_count * _SAMPLES_PER_FRAME * _CHANNELS * 4
        assert header["data_size"] == expected_payload_bytes
        assert header["riff_size"] == 36 + expected_payload_bytes
        # File size = header + payload.
        assert len(data) == 44 + expected_payload_bytes

        payload = data[44:]
        samples = np.frombuffer(payload, dtype=np.float32).reshape(-1, _CHANNELS)
        assert samples.shape == (frame_count * _SAMPLES_PER_FRAME, 2)
        # Frame i has L=i, R=-i across all 128 samples.
        for i in range(frame_count):
            start = i * _SAMPLES_PER_FRAME
            end = start + _SAMPLES_PER_FRAME
            assert np.all(samples[start:end, 0] == float(i))
            assert np.all(samples[start:end, 1] == -float(i))
    finally:
        server.close()
        await server.wait_closed()


async def test_record_to_stdout_raw_pcm(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsysbinary: pytest.CaptureFixture[bytes],
):
    """``-o -`` writes interleaved float32 LE PCM to stdout (no header)."""
    socket_path = tmp_path / "rio.sock"
    frame_count = 3
    speaker = _make_finite_speaker(frame_count)
    server = Server([speaker()])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(["record", "-o", "-"])
        rc = await _amain(args)
        assert rc == 0
        captured = capsysbinary.readouterr()
        # No WAV header — bytes start directly with the first sample
        # value (frame 0: L=0, R=-0 → float32 LE 0x00000000 four bytes).
        samples = np.frombuffer(captured.out, dtype=np.float32).reshape(-1, _CHANNELS)
        assert samples.shape == (frame_count * _SAMPLES_PER_FRAME, 2)
        for i in range(frame_count):
            start = i * _SAMPLES_PER_FRAME
            end = start + _SAMPLES_PER_FRAME
            assert np.all(samples[start:end, 0] == float(i))
            assert np.all(samples[start:end, 1] == -float(i))
    finally:
        server.close()
        await server.wait_closed()


async def test_record_rejects_unsupported_extension(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """A non-``.wav`` / non-``-`` output target exits with rc=2."""
    socket_path = tmp_path / "rio.sock"
    out_path = tmp_path / "out.mp3"
    speaker = _make_finite_speaker(1)
    server = Server([speaker()])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(["record", "-o", str(out_path)])
        rc = await _amain(args)
        assert rc == 2
        captured = capsys.readouterr()
        assert "unsupported output extension" in captured.err
        assert not out_path.exists()
    finally:
        server.close()
        await server.wait_closed()


async def test_record_duration_stops_streaming(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """``--duration`` bounds runtime against an infinite producer.

    Also verifies the WAV header sizes are still patched in correctly
    after the duration timeout unwinds the async context manager.
    """
    socket_path = tmp_path / "rio.sock"
    out_path = tmp_path / "out.wav"
    speaker = _make_infinite_speaker(interval_s=0.01)
    server = Server([speaker()])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(
            ["record", "-o", str(out_path), "--duration", "0.15"]
        )
        start = time.monotonic()
        rc = await _amain(args)
        elapsed = time.monotonic() - start
        assert rc == 0
        # Wall-clock guard so an infinite producer cannot stall the test.
        assert elapsed < 1.0

        data = out_path.read_bytes()
        header = _parse_wav_header(data)
        # Sizes must be patched in — placeholder 0s would mean the
        # finally branch never ran.
        assert header["data_size"] > 0
        assert header["data_size"] == len(data) - 44
        assert header["riff_size"] == 36 + header["data_size"]
        # data_size must be a multiple of one full stereo float32 sample.
        assert header["data_size"] % 8 == 0
    finally:
        server.close()
        await server.wait_closed()


def test_record_requires_output_argument(capsys: pytest.CaptureFixture[str]):
    """``-o`` is mandatory — argparse short-circuits with ``SystemExit(2)``."""
    with pytest.raises(SystemExit) as excinfo:
        _build_parser().parse_args(["record"])
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "--output" in err or "-o" in err
