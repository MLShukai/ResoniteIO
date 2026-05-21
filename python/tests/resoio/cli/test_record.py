"""Tests for the ``resoio record`` subcommand (video + audio routes).

After the ``capture`` → ``record`` unification, this module covers both
modality routes for the four currently-implemented outputs:

* video × stdout → Y4M (C444)
* video × file   → H.264 yuv420p mp4 (PyAV)
* audio × stdout → raw float32 LE PCM
* audio × file   → WAV (48 kHz / stereo / float32 LE)

Muxed routes are deferred to a follow-up commit and are deliberately
not exercised here.
"""

from __future__ import annotations

import asyncio
import struct
import sys
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import BinaryIO

import av
import numpy as np
import pytest
from grpclib.server import Server

from resoio._generated.resonite_io.v1 import (
    AudioFrame,
    CameraBase,
    CameraFrame,
    CameraFrameFormat,
    CameraStreamRequest,
    SpeakerBase,
    SpeakerStreamRequest,
)
from resoio.cli import _amain, _build_parser

# ---------------------------------------------------------------------------
# Camera fakes — formerly in tests/resoio/cli/test_capture.py.
# ---------------------------------------------------------------------------


def _make_fixed_camera(width: int, height: int, frame_count: int) -> type[CameraBase]:
    """Yield ``frame_count`` frames at fixed ``width``/``height``.

    Ignores ``request.width``/``height`` so tests assert that the CLI threads
    the *server-reported* dimensions through to the Y4M header.
    """

    class _FixedCamera(CameraBase):
        async def stream_frames(
            self, message: CameraStreamRequest
        ) -> AsyncIterator[CameraFrame]:
            for i in range(frame_count):
                pixels = bytes([i & 0xFF]) * (width * height * 4)
                yield CameraFrame(
                    width=width,
                    height=height,
                    format=CameraFrameFormat.RGBA8,
                    unix_nanos=time.time_ns(),
                    frame_id=i,
                    pixels=pixels,
                )

    return _FixedCamera


def _make_infinite_camera(
    width: int, height: int, interval_s: float = 0.01
) -> type[CameraBase]:
    """Yield frames forever at ``interval_s`` cadence."""

    class _InfiniteCamera(CameraBase):
        async def stream_frames(
            self, message: CameraStreamRequest
        ) -> AsyncIterator[CameraFrame]:
            i = 0
            while True:
                pixels = bytes([i & 0xFF]) * (width * height * 4)
                yield CameraFrame(
                    width=width,
                    height=height,
                    format=CameraFrameFormat.RGBA8,
                    unix_nanos=time.time_ns(),
                    frame_id=i,
                    pixels=pixels,
                )
                i += 1
                await asyncio.sleep(interval_s)

    return _InfiniteCamera


def _make_one_then_sleep_camera(width: int, height: int) -> type[CameraBase]:
    """Yield exactly one frame, then sleep — exercises the duplicate-frame
    branch."""

    class _OneFrameCamera(CameraBase):
        async def stream_frames(
            self, message: CameraStreamRequest
        ) -> AsyncIterator[CameraFrame]:
            yield CameraFrame(
                width=width,
                height=height,
                format=CameraFrameFormat.RGBA8,
                unix_nanos=time.time_ns(),
                frame_id=0,
                pixels=bytes([0]) * (width * height * 4),
            )
            # Outlast any reasonable test --duration so the producer never
            # ends first.
            await asyncio.sleep(10.0)

    return _OneFrameCamera


# ---------------------------------------------------------------------------
# Speaker fakes — formerly in the audio-only test_record.py.
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# WAV header parsing — kept here because the stdlib :mod:`wave` module
# rejects ``WAVE_FORMAT_IEEE_FLOAT`` (format tag 0x0003).
# ---------------------------------------------------------------------------


def _parse_wav_header(data: bytes) -> dict[str, int]:
    """Parse the fixed 44-byte WAV header into its numeric fields."""
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


# ===========================================================================
# Video route tests
# ===========================================================================


async def test_record_video_y4m_to_stdout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsysbinary: pytest.CaptureFixture[bytes],
):
    """``record --video -o -`` emits a C444 Y4M stream with correct
    payloads."""
    socket_path = tmp_path / "rio.sock"
    camera = _make_fixed_camera(width=16, height=8, frame_count=3)
    server = Server([camera()])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(
            ["record", "--video", "-o", "-", "--duration", "0.3"]
        )
        rc = await _amain(args)
        assert rc == 0
        data = capsysbinary.readouterr().out
        assert data.startswith(b"YUV4MPEG2 W16 H8 F30:1 Ip A1:1 C444\n")
        chunks = data.split(b"FRAME\n")
        assert len(chunks) >= 2
        # 4:4:4 payload per frame: 16 * 8 * 3 = 384.
        for payload in chunks[1:]:
            assert len(payload) == 16 * 8 * 3
    finally:
        server.close()
        await server.wait_closed()


async def test_record_video_threads_server_dimensions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsysbinary: pytest.CaptureFixture[bytes],
):
    """Server-reported dims are emitted verbatim (no crop in C444)."""
    socket_path = tmp_path / "rio.sock"
    camera = _make_fixed_camera(width=17, height=9, frame_count=1)
    server = Server([camera()])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(
            ["record", "--video", "-o", "-", "--duration", "0.2"]
        )
        rc = await _amain(args)
        assert rc == 0
        data = capsysbinary.readouterr().out
        assert data.startswith(b"YUV4MPEG2 W17 H9 F30:1 Ip A1:1 C444\n")
        chunks = data.split(b"FRAME\n")
        assert len(chunks) >= 2
        for payload in chunks[1:]:
            assert len(payload) == 17 * 9 * 3
    finally:
        server.close()
        await server.wait_closed()


async def test_record_video_mp4_to_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """``--video -o out.mp4`` produces an H.264 yuv420p mp4 readable by PyAV."""
    socket_path = tmp_path / "rio.sock"
    out_path = tmp_path / "out.mp4"
    # Even dimensions because yuv420p subsampling requires it; h264 also
    # tolerates odd dims but using even avoids any encoder padding noise.
    camera = _make_fixed_camera(width=32, height=16, frame_count=10)
    server = Server([camera()])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(
            ["record", "--video", "-o", str(out_path), "--duration", "0.5"]
        )
        rc = await _amain(args)
        assert rc == 0
        assert out_path.exists() and out_path.stat().st_size > 0

        container = av.open(str(out_path))
        try:
            assert len(container.streams.video) == 1
            assert len(container.streams.audio) == 0
            v = container.streams.video[0]
            assert v.width == 32
            assert v.height == 16
            packet_count = 0
            for packet in container.demux(v):
                if packet.size > 0:
                    packet_count += 1
            assert packet_count >= 1
        finally:
            container.close()
    finally:
        server.close()
        await server.wait_closed()


async def test_record_video_mp4_duration_stops_streaming(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """``--video -o out.mp4 --duration`` produces a well-formed mp4.

    Regression guard for the flush ordering: if ``stream.encode(None)``
    or ``container.close()`` were skipped on the duration-cancel path,
    the moov atom would be missing and ``av.open`` would raise on
    read-back. The test also asserts at least one decoded frame to
    catch the case where flush ran but the writer otherwise produced an
    empty body.
    """
    socket_path = tmp_path / "rio.sock"
    out_path = tmp_path / "out.mp4"
    camera = _make_infinite_camera(width=32, height=16, interval_s=0.005)
    server = Server([camera()])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(
            ["record", "--video", "-o", str(out_path), "--duration", "0.3"]
        )
        start = time.monotonic()
        rc = await _amain(args)
        elapsed = time.monotonic() - start
        assert rc == 0
        assert elapsed < 1.5
        assert out_path.exists() and out_path.stat().st_size > 0

        container = av.open(str(out_path))
        try:
            assert len(container.streams.video) == 1
            assert len(container.streams.audio) == 0
            v = container.streams.video[0]
            assert v.width == 32
            assert v.height == 16
            decoded_frames = 0
            for frame in container.decode(v):
                del frame
                decoded_frames += 1
            assert decoded_frames > 0
        finally:
            container.close()
    finally:
        server.close()
        await server.wait_closed()


async def test_record_video_rejects_unsupported_extension(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """``--video -o out.avi`` exits rc=2 and writes nothing."""
    socket_path = tmp_path / "rio.sock"
    out_path = tmp_path / "out.avi"
    # Server isn't needed for the validate path, but starting one matches
    # the patterns used elsewhere and protects against accidental
    # resolution-fallback errors.
    camera = _make_fixed_camera(width=8, height=8, frame_count=1)
    server = Server([camera()])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(["record", "--video", "-o", str(out_path)])
        rc = await _amain(args)
        assert rc == 2
        err = capsys.readouterr().err
        assert "unsupported output extension for video-only mode" in err
        assert not out_path.exists()
    finally:
        server.close()
        await server.wait_closed()


async def test_record_video_rejects_y4m_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """Y4M files are no longer supported — stdout (``-``) is the only Y4M
    sink."""
    socket_path = tmp_path / "rio.sock"
    out_path = tmp_path / "out.y4m"
    camera = _make_fixed_camera(width=8, height=8, frame_count=1)
    server = Server([camera()])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(["record", "--video", "-o", str(out_path)])
        rc = await _amain(args)
        assert rc == 2
        err = capsys.readouterr().err
        assert "unsupported output extension" in err
        assert not out_path.exists()
    finally:
        server.close()
        await server.wait_closed()


async def test_record_video_duration_stops_streaming(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsysbinary: pytest.CaptureFixture[bytes],
):
    """``--duration`` bounds runtime against an infinite producer."""
    socket_path = tmp_path / "rio.sock"
    camera = _make_infinite_camera(width=8, height=8)
    server = Server([camera()])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(
            ["record", "--video", "-o", "-", "--duration", "0.15"]
        )
        start = time.monotonic()
        rc = await _amain(args)
        elapsed = time.monotonic() - start
        assert rc == 0
        assert elapsed < 0.5
        data = capsysbinary.readouterr().out
        assert data.startswith(b"YUV4MPEG2 W8 H8 F30:1 Ip A1:1 C444\n")
        chunks = data.split(b"FRAME\n")
        assert 1 <= len(chunks) - 1 <= 30
    finally:
        server.close()
        await server.wait_closed()


async def test_record_video_duplicates_slow_frames(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsysbinary: pytest.CaptureFixture[bytes],
):
    """Slow producer → fixed-rate pacing duplicates the latest frame."""
    socket_path = tmp_path / "rio.sock"
    camera = _make_one_then_sleep_camera(width=8, height=8)
    server = Server([camera()])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(
            [
                "record",
                "--video",
                "-o",
                "-",
                "--fps",
                "10",
                "--duration",
                "0.5",
            ]
        )
        rc = await _amain(args)
        assert rc == 0
        data = capsysbinary.readouterr().out
        assert data.startswith(b"YUV4MPEG2 W8 H8 F10:1 Ip A1:1 C444\n")
        chunks = data.split(b"FRAME\n")
        frame_count = len(chunks) - 1
        # 10fps × 0.5s = 5 frames expected; allow generous slack for the
        # +1 edge frame + +1 boundary slip in pacing tolerance.
        assert 2 <= frame_count <= 7, frame_count
    finally:
        server.close()
        await server.wait_closed()


async def test_record_video_drops_fast_frames(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsysbinary: pytest.CaptureFixture[bytes],
):
    """Fast producer (~100Hz) is paced down to ``--fps`` via drop-oldest."""
    socket_path = tmp_path / "rio.sock"
    camera = _make_infinite_camera(width=8, height=8, interval_s=0.01)
    server = Server([camera()])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(
            [
                "record",
                "--video",
                "-o",
                "-",
                "--fps",
                "10",
                "--duration",
                "0.5",
            ]
        )
        rc = await _amain(args)
        assert rc == 0
        data = capsysbinary.readouterr().out
        chunks = data.split(b"FRAME\n")
        frame_count = len(chunks) - 1
        # 10fps × 0.5s = 5; allow ±3 for jitter. Crucially this must be
        # nowhere near the ~50 frames the producer emitted in the window,
        # proving the drop-oldest path engaged.
        assert 2 <= frame_count <= 8, frame_count
    finally:
        server.close()
        await server.wait_closed()


class _BrokenPipeBuffer:
    """Minimal binary stream replacement that raises on every ``write``.

    Used to exercise the ``BrokenPipeError`` path of ``_record_video_y4m``
    without actually closing pytest's captured stdout (which would break
    later assertions).
    """

    def write(self, data: bytes) -> int:
        del data
        raise BrokenPipeError("simulated broken pipe")

    def flush(self) -> None:
        return None


class _FakeStdout:
    """``sys.stdout`` stand-in whose ``.buffer`` raises ``BrokenPipeError``.

    Patching ``sys.stdout.buffer`` directly fails — it is a read-only
    attribute on the real ``TextIOWrapper`` — so the test swaps the
    whole ``sys.stdout`` object for one whose ``buffer`` raises on
    write.
    """

    def __init__(self) -> None:
        self.buffer: BinaryIO = _BrokenPipeBuffer()  # type: ignore[assignment]


async def test_record_video_stdout_broken_pipe_clean_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A broken stdout pipe is swallowed and the CLI returns rc=0."""
    socket_path = tmp_path / "rio.sock"
    camera = _make_infinite_camera(width=8, height=8)
    server = Server([camera()])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        monkeypatch.setattr(sys, "stdout", _FakeStdout())
        args = _build_parser().parse_args(
            ["record", "--video", "-o", "-", "--duration", "0.3"]
        )
        rc = await _amain(args)
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()


# ===========================================================================
# Audio route tests
# ===========================================================================


async def test_record_audio_wav_to_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """End-to-end: 3 frames → ``.wav`` → parse header + sample bytes."""
    socket_path = tmp_path / "rio.sock"
    out_path = tmp_path / "out.wav"
    frame_count = 3
    speaker = _make_finite_speaker(frame_count)
    server = Server([speaker()])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(["record", "--audio", "-o", str(out_path)])
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
        assert len(data) == 44 + expected_payload_bytes

        payload = data[44:]
        samples = np.frombuffer(payload, dtype=np.float32).reshape(-1, _CHANNELS)
        assert samples.shape == (frame_count * _SAMPLES_PER_FRAME, 2)
        for i in range(frame_count):
            start = i * _SAMPLES_PER_FRAME
            end = start + _SAMPLES_PER_FRAME
            assert np.all(samples[start:end, 0] == float(i))
            assert np.all(samples[start:end, 1] == -float(i))
    finally:
        server.close()
        await server.wait_closed()


async def test_record_audio_pcm_to_stdout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsysbinary: pytest.CaptureFixture[bytes],
):
    """``--audio -o -`` writes interleaved float32 LE PCM (no header)."""
    socket_path = tmp_path / "rio.sock"
    frame_count = 3
    speaker = _make_finite_speaker(frame_count)
    server = Server([speaker()])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(["record", "--audio", "-o", "-"])
        rc = await _amain(args)
        assert rc == 0
        captured = capsysbinary.readouterr()
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


async def test_record_audio_rejects_unsupported_extension(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """``--audio -o out.mp3`` exits rc=2 and writes nothing."""
    socket_path = tmp_path / "rio.sock"
    out_path = tmp_path / "out.mp3"
    speaker = _make_finite_speaker(1)
    server = Server([speaker()])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(["record", "--audio", "-o", str(out_path)])
        rc = await _amain(args)
        assert rc == 2
        err = capsys.readouterr().err
        assert "unsupported output extension for audio-only mode" in err
        assert not out_path.exists()
    finally:
        server.close()
        await server.wait_closed()


async def test_record_audio_duration_stops_streaming(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """``--duration`` bounds runtime; WAV header is still patched on exit."""
    socket_path = tmp_path / "rio.sock"
    out_path = tmp_path / "out.wav"
    speaker = _make_infinite_speaker(interval_s=0.01)
    server = Server([speaker()])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(
            ["record", "--audio", "-o", str(out_path), "--duration", "0.15"]
        )
        start = time.monotonic()
        rc = await _amain(args)
        elapsed = time.monotonic() - start
        assert rc == 0
        assert elapsed < 1.0

        data = out_path.read_bytes()
        header = _parse_wav_header(data)
        assert header["data_size"] > 0
        assert header["data_size"] == len(data) - 44
        assert header["riff_size"] == 36 + header["data_size"]
        # Each stereo float32 sample is 8 bytes.
        assert header["data_size"] % 8 == 0
    finally:
        server.close()
        await server.wait_closed()


async def test_record_audio_rejects_fps_flag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """``--audio --fps 30`` is rejected with rc=2."""
    socket_path = tmp_path / "rio.sock"
    speaker = _make_finite_speaker(1)
    server = Server([speaker()])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(
            ["record", "--audio", "--fps", "30", "-o", "-"]
        )
        rc = await _amain(args)
        assert rc == 2
        err = capsys.readouterr().err
        assert "--fps/-v require video" in err
    finally:
        server.close()
        await server.wait_closed()


async def test_record_audio_rejects_verbose_flag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """``--audio -v`` is rejected with rc=2."""
    socket_path = tmp_path / "rio.sock"
    speaker = _make_finite_speaker(1)
    server = Server([speaker()])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(["record", "--audio", "-v", "-o", "-"])
        rc = await _amain(args)
        assert rc == 2
        err = capsys.readouterr().err
        assert "--fps/-v require video" in err
    finally:
        server.close()
        await server.wait_closed()


# ===========================================================================
# Muxed routes are intentionally not exercised here — see follow-up commit.
# ===========================================================================
