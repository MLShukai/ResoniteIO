import asyncio
import time
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from grpclib.server import Server

from resoio._generated.resonite_io.v1 import (
    CameraBase,
    CameraFrame,
    CameraFrameFormat,
    CameraStreamRequest,
)
from resoio.cli import _amain, _build_parser


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
            # Outlast any reasonable test --duration so the producer never ends first.
            await asyncio.sleep(10.0)

    return _OneFrameCamera


async def test_capture_to_file_yuv444(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    socket_path = tmp_path / "rio.sock"
    out_path = tmp_path / "out.y4m"
    camera = _make_fixed_camera(width=16, height=8, frame_count=3)
    server = Server([camera()])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(
            [
                "capture",
                "-o",
                str(out_path),
                "--chroma",
                "444",
                "--duration",
                "1",
            ]
        )
        rc = await _amain(args)
        assert rc == 0
        data = out_path.read_bytes()
        assert data.startswith(b"YUV4MPEG2 W16 H8 F30:1 Ip A1:1 C444\n")
        # First chunk is the header; subsequent chunks are FRAME blocks.
        # Output cadence is governed by --fps pacing, not by the producer
        # frame count: at least one frame must be emitted, the rest may
        # be duplicates of the latest producer frame.
        chunks = data.split(b"FRAME\n")
        assert len(chunks) >= 2
        # 4:4:4 payload per frame: 16 * 8 * 3 = 384.
        for payload in chunks[1:]:
            assert len(payload) == 16 * 8 * 3
    finally:
        server.close()
        await server.wait_closed()


async def test_capture_to_file_yuv420(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    socket_path = tmp_path / "rio.sock"
    out_path = tmp_path / "out.y4m"
    camera = _make_fixed_camera(width=16, height=8, frame_count=3)
    server = Server([camera()])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(
            [
                "capture",
                "-o",
                str(out_path),
                "--chroma",
                "420",
                "--duration",
                "1",
            ]
        )
        rc = await _amain(args)
        assert rc == 0
        data = out_path.read_bytes()
        assert data.startswith(b"YUV4MPEG2 W16 H8 F30:1 Ip A1:1 C420\n")
        chunks = data.split(b"FRAME\n")
        # Pacing-governed: see test_capture_to_file_yuv444 rationale.
        assert len(chunks) >= 2
        # 4:2:0: Y = 16*8 = 128, U = V = 8*4 = 32. Total per frame = 192.
        for payload in chunks[1:]:
            assert len(payload) == 128 + 32 + 32
    finally:
        server.close()
        await server.wait_closed()


async def test_capture_crops_odd_dimensions_for_420(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    socket_path = tmp_path / "rio.sock"
    out_path = tmp_path / "out.y4m"
    camera = _make_fixed_camera(width=17, height=9, frame_count=2)
    server = Server([camera()])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(
            [
                "capture",
                "-o",
                str(out_path),
                "--chroma",
                "420",
                "--duration",
                "1",
            ]
        )
        rc = await _amain(args)
        assert rc == 0
        data = out_path.read_bytes()
        # Cropped to even dimensions before the header is written.
        assert data.startswith(b"YUV4MPEG2 W16 H8 F30:1 Ip A1:1 C420\n")
    finally:
        server.close()
        await server.wait_closed()


async def test_capture_no_crop_for_444_with_odd_dimensions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    socket_path = tmp_path / "rio.sock"
    out_path = tmp_path / "out.y4m"
    camera = _make_fixed_camera(width=17, height=9, frame_count=1)
    server = Server([camera()])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(
            [
                "capture",
                "-o",
                str(out_path),
                "--chroma",
                "444",
                "--duration",
                "1",
            ]
        )
        rc = await _amain(args)
        assert rc == 0
        data = out_path.read_bytes()
        assert data.startswith(b"YUV4MPEG2 W17 H9 F30:1 Ip A1:1 C444\n")
        # 4:4:4 payload at 17x9 = 459 bytes per frame. Pacing may emit
        # duplicates of the same frame, so just check every chunk has
        # the right payload size.
        chunks = data.split(b"FRAME\n")
        assert len(chunks) >= 2
        for payload in chunks[1:]:
            assert len(payload) == 17 * 9 * 3
    finally:
        server.close()
        await server.wait_closed()


async def test_capture_duration_stops_streaming(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    socket_path = tmp_path / "rio.sock"
    out_path = tmp_path / "out.y4m"
    camera = _make_infinite_camera(width=8, height=8)
    server = Server([camera()])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(
            [
                "capture",
                "-o",
                str(out_path),
                "--chroma",
                "444",
                "--duration",
                "0.15",
            ]
        )
        start = time.monotonic()
        rc = await _amain(args)
        elapsed = time.monotonic() - start
        assert rc == 0
        # Wall-clock guard: duration should bound runtime; allow generous
        # CI slack but ensure we don't hang waiting for an infinite stream.
        assert elapsed < 0.5
        data = out_path.read_bytes()
        assert data.startswith(b"YUV4MPEG2 W8 H8 F30:1 Ip A1:1 C444\n")
        chunks = data.split(b"FRAME\n")
        # At ~10ms per frame and 0.15s duration we expect a handful of
        # frames, but stay tolerant for slower runners.
        assert 1 <= len(chunks) - 1 <= 30
    finally:
        server.close()
        await server.wait_closed()


async def test_capture_duplicates_slow_frames(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Slow producer: one frame must be duplicated to honor --fps."""
    socket_path = tmp_path / "rio.sock"
    out_path = tmp_path / "out.y4m"
    camera = _make_one_then_sleep_camera(width=8, height=8)
    server = Server([camera()])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(
            [
                "capture",
                "-o",
                str(out_path),
                "--chroma",
                "444",
                "--fps",
                "10",
                "--duration",
                "0.5",
            ]
        )
        rc = await _amain(args)
        assert rc == 0
        data = out_path.read_bytes()
        assert data.startswith(b"YUV4MPEG2 W8 H8 F10:1 Ip A1:1 C444\n")
        chunks = data.split(b"FRAME\n")
        # 10fps x 0.5s = 5 frames expected; allow generous slack for the
        # +1 edge frame + +1 boundary slip described in pacing tolerance.
        frame_count = len(chunks) - 1
        assert 2 <= frame_count <= 7, frame_count
    finally:
        server.close()
        await server.wait_closed()


async def test_capture_drops_fast_frames(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Fast producer (~100Hz) is paced down to --fps via drop-oldest."""
    socket_path = tmp_path / "rio.sock"
    out_path = tmp_path / "out.y4m"
    # ~100Hz producer: well above the 10fps consumer target so each
    # consumer wake-up sees a fresh frame and the rest must be dropped.
    camera = _make_infinite_camera(width=8, height=8, interval_s=0.01)
    server = Server([camera()])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(
            [
                "capture",
                "-o",
                str(out_path),
                "--chroma",
                "444",
                "--fps",
                "10",
                "--duration",
                "0.5",
            ]
        )
        rc = await _amain(args)
        assert rc == 0
        data = out_path.read_bytes()
        assert data.startswith(b"YUV4MPEG2 W8 H8 F10:1 Ip A1:1 C444\n")
        chunks = data.split(b"FRAME\n")
        frame_count = len(chunks) - 1
        # 10fps x 0.5s = 5; allow +-2 for jitter. Crucially this must be
        # nowhere near the ~50 frames the producer emitted in the window,
        # proving the drop-oldest path engaged.
        assert 2 <= frame_count <= 8, frame_count
    finally:
        server.close()
        await server.wait_closed()
