import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import TYPE_CHECKING

import numpy as np
import pytest

from resoio._generated.resonite_io.v1 import (
    CameraBase,
    CameraFrame,
    CameraFrameFormat,
    CameraStreamRequest,
)
from resoio.camera import CameraClient, Frame

if TYPE_CHECKING:
    from grpclib._typing import IServable

UdsServer = Callable[["IServable"], Awaitable[str]]

# Sentinel default the fake substitutes when the client asks for 0; lets the
# default-resolution test assert the resolved value explicitly.
_DEFAULT_W = 32
_DEFAULT_H = 24
_FRAME_COUNT = 3


class _EchoCamera(CameraBase):
    """In-process fake yielding ``_FRAME_COUNT`` synthetic RGBA8 frames."""

    async def stream_frames(
        self, message: CameraStreamRequest
    ) -> AsyncIterator[CameraFrame]:
        w = message.width or _DEFAULT_W
        h = message.height or _DEFAULT_H
        for i in range(_FRAME_COUNT):
            # Deterministic payload: byte i encodes the frame index so
            # the test can prove pixels are propagated, not merely
            # zero-filled.
            pixels = bytes([i & 0xFF]) * (w * h * 4)
            yield CameraFrame(
                width=w,
                height=h,
                format=CameraFrameFormat.RGBA8,
                unix_nanos=time.time_ns(),
                frame_id=i,
                pixels=pixels,
            )


class TestCameraClient:
    async def test_round_trip_over_uds(self, uds_server: UdsServer):
        socket_path = await uds_server(_EchoCamera())
        width, height = 16, 8
        frames: list[Frame] = []
        async with CameraClient() as client:
            assert client.socket_path == socket_path
            async for frame in client.stream(width=width, height=height):
                frames.append(frame)
        assert len(frames) == _FRAME_COUNT
        for i, frame in enumerate(frames):
            assert frame.width == width
            assert frame.height == height
            assert frame.frame_id == i
            assert frame.unix_nanos > 0
            assert isinstance(frame.pixels, np.ndarray)
            assert frame.pixels.dtype == np.uint8
            assert frame.pixels.shape == (height, width, 4)
            # First byte = frame index (see _EchoCamera): proves the
            # bytes flow through unchanged, not just zero-allocated.
            assert int(frame.pixels[0, 0, 0]) == i

    async def test_default_resolution_when_zero(self, uds_server: UdsServer):
        await uds_server(_EchoCamera())
        async with CameraClient() as client:
            async for frame in client.stream(width=0, height=0):
                # Server filled in the default; reshape must agree.
                assert frame.width == _DEFAULT_W
                assert frame.height == _DEFAULT_H
                assert frame.pixels.shape == (_DEFAULT_H, _DEFAULT_W, 4)
                break

    async def test_raises_when_not_connected(self):
        client = CameraClient()
        with pytest.raises(RuntimeError, match="not connected"):
            async for _ in client.stream():
                pass
