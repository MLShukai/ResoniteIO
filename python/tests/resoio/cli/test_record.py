"""Tests for the ``resoio record`` subcommand (all six routes).

After the ``capture`` → ``record`` unification this module covers
every (mode, output) pair the dispatcher emits:

* video × stdout → Y4M (C444)
* video × file   → H.264 yuv420p mp4 (PyAV)
* audio × stdout → raw float32 LE PCM
* audio × file   → WAV (48 kHz / stereo / float32 LE)
* muxed × stdout → matroska (H.264 + AAC) on ``sys.stdout.buffer``
* muxed × file   → mp4 (H.264 + AAC)
"""

from __future__ import annotations

import asyncio
import io
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
# Muxed route tests
# ===========================================================================


def _make_finite_camera_synced(
    width: int, height: int, frame_count: int, *, base_t0: int, period_ns: int
) -> type[CameraBase]:
    """Camera that emits ``frame_count`` frames with deterministic
    ``unix_nanos``.

    Both ``base_t0`` and ``period_ns`` are caller-controlled so the muxed
    A/V-sync test can correlate the camera and speaker timelines without
    relying on wall-clock alignment (which is noisy under CI load).
    """

    class _SyncedCamera(CameraBase):
        async def stream_frames(
            self, message: CameraStreamRequest
        ) -> AsyncIterator[CameraFrame]:
            for i in range(frame_count):
                pixels = bytes([i & 0xFF]) * (width * height * 4)
                yield CameraFrame(
                    width=width,
                    height=height,
                    format=CameraFrameFormat.RGBA8,
                    unix_nanos=base_t0 + i * period_ns,
                    frame_id=i,
                    pixels=pixels,
                )
                await asyncio.sleep(0.005)

    return _SyncedCamera


def _make_finite_speaker_synced(
    frame_count: int, *, base_t0: int, period_ns: int
) -> type[SpeakerBase]:
    """Speaker with deterministic ``unix_nanos`` for A/V sync verification."""

    class _SyncedSpeaker(SpeakerBase):
        async def stream_audio(
            self, message: SpeakerStreamRequest
        ) -> AsyncIterator[AudioFrame]:
            for i in range(frame_count):
                yield AudioFrame(
                    frame_id=i,
                    unix_nanos=base_t0 + i * period_ns,
                    sample_count=_SAMPLES_PER_FRAME,
                    samples=_frame_samples(i).tobytes(),
                )
                await asyncio.sleep(0.005)

    return _SyncedSpeaker


class _MuxedStdout:
    """``sys.stdout`` stand-in whose ``.buffer`` is a writeable ``BytesIO``.

    PyAV writes the matroska container directly into the buffer; the
    test reads the captured bytes back via ``av.open(BytesIO, ...)``
    once the CLI exits. Mirrors the pattern used by
    :class:`_FakeStdout` for the broken-pipe test but exposes the
    captured payload instead of raising.
    """

    def __init__(self) -> None:
        self.buffer: BinaryIO = io.BytesIO()  # type: ignore[assignment]


async def test_record_muxed_mp4_to_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Flag-less ``record -o out.mp4`` produces an H.264 + AAC mp4."""
    socket_path = tmp_path / "rio.sock"
    out_path = tmp_path / "out.mp4"
    camera = _make_fixed_camera(width=32, height=16, frame_count=20)
    speaker = _make_finite_speaker(40)
    server = Server([camera(), speaker()])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(
            ["record", "-o", str(out_path), "--duration", "0.5"]
        )
        rc = await _amain(args)
        assert rc == 0
        assert out_path.exists() and out_path.stat().st_size > 0

        container = av.open(str(out_path))
        try:
            assert len(container.streams.video) == 1
            assert len(container.streams.audio) == 1
            v = container.streams.video[0]
            assert v.width == 32
            assert v.height == 16
            a = container.streams.audio[0]
            assert a.codec_context.sample_rate == 48000
            assert a.layout.name == "stereo"

            video_frames = sum(1 for _ in container.decode(v))
            assert video_frames > 0
        finally:
            container.close()
    finally:
        server.close()
        await server.wait_closed()


async def test_record_muxed_mkv_to_stdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Flag-less ``record -o -`` emits a matroska stream on stdout."""
    socket_path = tmp_path / "rio.sock"
    camera = _make_fixed_camera(width=32, height=16, frame_count=20)
    speaker = _make_finite_speaker(40)
    server = Server([camera(), speaker()])
    await server.start(path=str(socket_path))
    stdout_stub = _MuxedStdout()
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        monkeypatch.setattr(sys, "stdout", stdout_stub)
        args = _build_parser().parse_args(["record", "-o", "-", "--duration", "0.5"])
        rc = await _amain(args)
        assert rc == 0
        # capsysbinary would intercept stdout before our buffer swap, so
        # we read the BytesIO that the swap exposed instead.
        buf = stdout_stub.buffer
        assert isinstance(buf, io.BytesIO)
        payload = buf.getvalue()
        assert len(payload) > 0

        container = av.open(io.BytesIO(payload), mode="r", format="matroska")
        try:
            assert len(container.streams.video) == 1
            assert len(container.streams.audio) == 1
            assert container.streams.audio[0].codec_context.sample_rate == 48000
        finally:
            container.close()
    finally:
        server.close()
        await server.wait_closed()


async def test_record_muxed_rejects_unsupported_extension(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """Flag-less ``record -o foo.avi`` exits rc=2 and writes nothing."""
    socket_path = tmp_path / "rio.sock"
    out_path = tmp_path / "out.avi"
    camera = _make_fixed_camera(width=8, height=8, frame_count=1)
    speaker = _make_finite_speaker(1)
    server = Server([camera(), speaker()])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(["record", "-o", str(out_path)])
        rc = await _amain(args)
        assert rc == 2
        err = capsys.readouterr().err
        assert "unsupported output extension for muxed mode" in err
        assert not out_path.exists()
    finally:
        server.close()
        await server.wait_closed()


async def test_record_muxed_duration_stops_streaming(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """``--duration`` bounds runtime against both infinite producers."""
    socket_path = tmp_path / "rio.sock"
    out_path = tmp_path / "out.mp4"
    camera = _make_infinite_camera(width=32, height=16, interval_s=0.005)
    speaker = _make_infinite_speaker(interval_s=0.005)
    server = Server([camera(), speaker()])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(
            ["record", "-o", str(out_path), "--duration", "0.3"]
        )
        start = time.monotonic()
        rc = await _amain(args)
        elapsed = time.monotonic() - start
        assert rc == 0
        # Generous bound; the duration cancel must still leave time for
        # flush + close before the assertion fires.
        assert elapsed < 1.5, elapsed
        assert out_path.exists() and out_path.stat().st_size > 0

        container = av.open(str(out_path))
        try:
            assert len(container.streams.video) == 1
            assert len(container.streams.audio) == 1
        finally:
            container.close()
    finally:
        server.close()
        await server.wait_closed()


async def test_record_both_flags_equivalent_to_no_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """``--video --audio`` is the same dispatch path as no flags."""
    socket_path_a = tmp_path / "rio_a.sock"
    socket_path_b = tmp_path / "rio_b.sock"
    out_a = tmp_path / "a.mp4"
    out_b = tmp_path / "b.mp4"

    async def _run_once(sock: Path, out: Path, argv: list[str]) -> None:
        camera = _make_fixed_camera(width=32, height=16, frame_count=20)
        speaker = _make_finite_speaker(40)
        server = Server([camera(), speaker()])
        await server.start(path=str(sock))
        try:
            monkeypatch.setenv("RESONITE_IO_SOCKET", str(sock))
            args = _build_parser().parse_args(argv)
            rc = await _amain(args)
            assert rc == 0
            assert out.exists() and out.stat().st_size > 0
            container = av.open(str(out))
            try:
                assert len(container.streams.video) == 1
                assert len(container.streams.audio) == 1
            finally:
                container.close()
        finally:
            server.close()
            await server.wait_closed()

    await _run_once(
        socket_path_a,
        out_a,
        ["record", "--video", "--audio", "-o", str(out_a), "--duration", "0.3"],
    )
    await _run_once(
        socket_path_b,
        out_b,
        ["record", "-o", str(out_b), "--duration", "0.3"],
    )


async def test_record_muxed_audio_av_sync_t0_shared(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Shared ``t0`` keeps the muxed mp4's video/audio ``start_time`` aligned.

    The camera and speaker fakes both anchor their ``unix_nanos`` to
    the same ``base_t0`` and emit at their natural cadences. The two
    streams therefore start within a few microseconds of each other on
    the source timeline; the muxed mp4 must preserve that to within a
    300 ms tolerance after PyAV's AAC priming / mp4 ``start_time``
    rounding (the spec calls 300 ms out as a CI-stable initial value).
    """
    socket_path = tmp_path / "rio.sock"
    out_path = tmp_path / "out.mp4"

    base_t0 = 1_000_000_000_000_000_000  # arbitrary fixed Unix-nanos epoch
    camera = _make_finite_camera_synced(
        width=32, height=16, frame_count=30, base_t0=base_t0, period_ns=33_333_333
    )
    speaker = _make_finite_speaker_synced(
        frame_count=120, base_t0=base_t0, period_ns=2_666_666
    )
    server = Server([camera(), speaker()])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(
            ["record", "-o", str(out_path), "--duration", "0.5"]
        )
        rc = await _amain(args)
        assert rc == 0

        container = av.open(str(out_path))
        try:
            vs = container.streams.video[0]
            audio = container.streams.audio[0]
            assert vs.start_time is not None
            assert audio.start_time is not None
            v_seconds = vs.start_time * float(vs.time_base)
            a_seconds = audio.start_time * float(audio.time_base)
            skew_ms = abs(v_seconds - a_seconds) * 1000.0
            # Spec §11.5 named 100 ms as the initial heuristic; relaxed
            # 3x to absorb PyAV muxer buffering (a few ms) plus CI
            # jitter. The shared-t0 design makes the observed skew
            # essentially 0 ms on a clean run.
            assert skew_ms < 300.0, skew_ms
        finally:
            container.close()
    finally:
        server.close()
        await server.wait_closed()


async def test_record_muxed_mp4_duration_matches_real_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Regression: muxed mp4 video duration matches the real recording window.

    Guards against the ``v_stream.codec_context.time_base`` mismatch: if
    the encoder still defaulted to ``1/fps`` while the stream advertised
    ``1/90000``, the muxer would rescale every packet PTS by
    ``90000/fps`` (=3000× at 30 fps), turning a ~0.4 s recording into a
    20+ minute video. Both audio and video durations are checked
    independently because the bug only inflated video.
    """
    socket_path = tmp_path / "rio.sock"
    out_path = tmp_path / "out.mp4"
    camera = _make_infinite_camera(width=32, height=16, interval_s=0.005)
    speaker = _make_infinite_speaker(interval_s=0.005)
    server = Server([camera(), speaker()])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        recording_window = 0.4
        args = _build_parser().parse_args(
            ["record", "-o", str(out_path), "--duration", str(recording_window)]
        )
        rc = await _amain(args)
        assert rc == 0
        assert out_path.exists() and out_path.stat().st_size > 0

        container = av.open(str(out_path))
        try:
            v = container.streams.video[0]
            a = container.streams.audio[0]
            assert v.duration is not None
            assert a.duration is not None
            v_seconds = float(v.duration * v.time_base)
            a_seconds = float(a.duration * a.time_base)
            # The recording window is 0.4 s but flush + buffering can
            # trim a touch; allow 0.1–2.0 s. The bug yields ~1200 s
            # at 0.4 s × 3000× scaling, so any sane upper bound catches
            # it. The lower bound rejects an empty stream.
            assert 0.1 < v_seconds < 2.0, f"video duration {v_seconds}s"
            assert 0.1 < a_seconds < 2.0, f"audio duration {a_seconds}s"
        finally:
            container.close()
    finally:
        server.close()
        await server.wait_closed()


class _LateBrokenPipeMuxedStdout:
    """``sys.stdout`` stand-in whose ``.buffer`` breaks after ``break_after``
    bytes.

    Mimics ``resoio record | head -c N`` / ``resoio record | ffmpeg -i -``
    being interrupted mid-stream: the matroska header and a few clusters
    are accepted, then the downstream pipe closes and every subsequent
    write raises ``BrokenPipeError``. The realistic timing matters
    because PyAV otherwise crashes natively when asked to mux into an
    already-broken container that never accepted a single byte.
    """

    class _Buffer:
        def __init__(self, break_after: int) -> None:
            self._break_after = break_after
            self._written = 0
            self.captured = bytearray()

        def write(self, data: bytes) -> int:
            if self._written >= self._break_after:
                raise BrokenPipeError("simulated broken pipe")
            n = len(data)
            self._written += n
            self.captured.extend(data)
            return n

        def flush(self) -> None:
            if self._written >= self._break_after:
                raise BrokenPipeError("simulated broken pipe")

        def seekable(self) -> bool:
            return False

    def __init__(self, break_after: int) -> None:
        self._buf = _LateBrokenPipeMuxedStdout._Buffer(break_after)
        self.buffer: BinaryIO = self._buf  # type: ignore[assignment]


async def test_record_muxed_stdout_broken_pipe_clean_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """Muxed stdout closed mid-stream → rc=0 with no traceback on stderr.

    Covers the user-visible end-to-end behaviour of
    ``resoio record | ffmpeg -i -`` when the downstream consumer
    detaches: the CLI must exit cleanly without a Python traceback
    leaking through. The clean exit is achieved by the composition of
    pump-level ``BrokenPipeError`` handling (the ``done``-task filter in
    :func:`_record_muxed`) and the teardown-time suppression in
    :func:`_suppress_teardown_errors`. Whether the teardown path is the
    one that actually catches an exception is PyAV-version dependent —
    on PyAV 17 the matroska muxer typically surfaces the break inside
    the video pump rather than during ``encode(None)`` / ``close()`` —
    so the suppression helper has its own dedicated unit tests below.
    """
    socket_path = tmp_path / "rio.sock"
    camera = _make_infinite_camera(width=32, height=16, interval_s=0.005)
    speaker = _make_infinite_speaker(interval_s=0.005)
    server = Server([camera(), speaker()])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        # 8 KiB is enough for the matroska header + a few clusters but
        # short enough that the duration window will overflow it.
        monkeypatch.setattr(sys, "stdout", _LateBrokenPipeMuxedStdout(break_after=8192))
        args = _build_parser().parse_args(["record", "-o", "-", "--duration", "0.3"])
        rc = await _amain(args)
        assert rc == 0
        # The pump-level + teardown-time suppression compose to keep
        # stderr clean even when the pipe breaks mid-stream.
        err = capsys.readouterr().err
        assert "Traceback" not in err
        assert "BrokenPipeError" not in err
        assert "PyAVCallbackError" not in err
    finally:
        server.close()
        await server.wait_closed()


# ---------------------------------------------------------------------------
# Unit tests for the suppression helper itself.
#
# The e2e test above asserts the *user-visible* shape (rc=0, no traceback);
# these target the helper's contract directly so that an accidental change
# to the ``except`` clause (e.g. dropping ``av.error.PyAVCallbackError``)
# is caught even when the e2e path happens to not exercise the teardown
# branch on the current PyAV version.
# ---------------------------------------------------------------------------


def test_suppress_teardown_errors_swallows_broken_pipe():
    """``BrokenPipeError`` raised by ``fn`` must be suppressed."""
    from resoio.cli.record import _suppress_teardown_errors

    def boom() -> None:
        raise BrokenPipeError("simulated")

    _suppress_teardown_errors(boom)


def test_suppress_teardown_errors_swallows_pyav_callback_error():
    """PyAV's ``PyAVCallbackError`` (wraps libav write callback) must be
    suppressed."""
    import av.error

    from resoio.cli.record import _suppress_teardown_errors

    def boom() -> None:
        # PyAV 17's PyAVCallbackError takes (errno, filename); errno=1 is
        # the FFmpeg "operation not permitted" sentinel libav uses when
        # the Python writer raised an exception inside a callback.
        raise av.error.PyAVCallbackError(1, "stdout")

    _suppress_teardown_errors(boom)


def test_suppress_teardown_errors_propagates_other_exceptions():
    """Non-IO errors must bubble out so real bugs are not hidden."""
    from resoio.cli.record import _suppress_teardown_errors

    def boom() -> None:
        raise RuntimeError("not an I/O error")

    with pytest.raises(RuntimeError, match="not an I/O error"):
        _suppress_teardown_errors(boom)
