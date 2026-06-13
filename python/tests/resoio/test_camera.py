import dataclasses
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

# The server owns the resolution now (Display modality); stream() carries no
# width/height. The fake emits a fixed, non-square size so width != height and
# the property-derivation assertions cannot pass by coincidence.
_FRAME_W = 16
_FRAME_H = 8
_FRAME_COUNT = 3


class _EchoCamera(CameraBase):
    """In-process fake yielding ``_FRAME_COUNT`` synthetic RGBA8 frames.

    Records every received request so the test can prove ``stream()`` sends a
    default (zero-valued) ``CameraStreamRequest`` end-to-end over the wire.
    """

    def __init__(self) -> None:
        self.requests: list[CameraStreamRequest] = []

    async def stream_frames(
        self, message: CameraStreamRequest
    ) -> AsyncIterator[CameraFrame]:
        self.requests.append(message)
        for i in range(_FRAME_COUNT):
            # Deterministic payload: byte i encodes the frame index so the
            # test can prove pixels are propagated, not merely zero-filled.
            pixels = bytes([i & 0xFF]) * (_FRAME_W * _FRAME_H * 4)
            yield CameraFrame(
                width=_FRAME_W,
                height=_FRAME_H,
                format=CameraFrameFormat.RGBA8,
                unix_nanos=time.time_ns(),
                frame_id=i,
                pixels=pixels,
            )


class TestCameraClient:
    async def test_round_trip_over_uds(self, uds_server: UdsServer):
        socket_path = await uds_server(_EchoCamera())
        frames: list[Frame] = []
        async with CameraClient() as client:
            assert client.socket_path == socket_path
            async for frame in client.stream():
                frames.append(frame)
        assert len(frames) == _FRAME_COUNT
        for i, frame in enumerate(frames):
            assert frame.frame_id == i
            assert frame.unix_nanos > 0
            assert isinstance(frame.pixels, np.ndarray)
            assert frame.pixels.dtype == np.uint8
            assert frame.pixels.shape == (_FRAME_H, _FRAME_W, 4)
            # First byte = frame index (see _EchoCamera): proves the
            # bytes flow through unchanged, not just zero-allocated.
            assert int(frame.pixels[0, 0, 0]) == i

    async def test_stream_sends_default_request(self, uds_server: UdsServer):
        # stream() takes no arguments; the wire request must be a plain
        # default CameraStreamRequest (no width/height/fps_limit).
        fake = _EchoCamera()
        await uds_server(fake)
        async with CameraClient() as client:
            async for _ in client.stream():
                break
        assert len(fake.requests) == 1
        request = fake.requests[0]
        assert request.width == 0
        assert request.height == 0
        assert request.fps_limit == 0.0

    async def test_dimensions_derive_from_pixels_shape(self, uds_server: UdsServer):
        # width / height / channels are read-only properties computed from
        # pixels.shape == (H, W, 4), not stored fields.
        await uds_server(_EchoCamera())
        async with CameraClient() as client:
            frame = await client.shot()
        assert frame.height == frame.pixels.shape[0]
        assert frame.width == frame.pixels.shape[1]
        assert frame.channels == frame.pixels.shape[2]
        assert frame.channels == 4

    async def test_frame_is_immutable(self, uds_server: UdsServer):
        # Frame is a frozen dataclass: assigning a stored field raises.
        # The derived dimensions are read-only by construction (the
        # property descriptors have no setter), asserted separately below.
        await uds_server(_EchoCamera())
        async with CameraClient() as client:
            frame = await client.shot()
        with pytest.raises(dataclasses.FrozenInstanceError):
            frame.frame_id = 99  # type: ignore[misc]
        assert type(frame).width.fset is None
        assert type(frame).height.fset is None
        assert type(frame).channels.fset is None

    async def test_shot_returns_first_frame(self, uds_server: UdsServer):
        # shot() is the one-shot wrapper: it returns the first streamed
        # frame (frame_id 0) and stops, rather than draining all
        # _FRAME_COUNT frames the way stream() does.
        await uds_server(_EchoCamera())
        async with CameraClient() as client:
            frame = await client.shot()
        assert frame.frame_id == 0
        assert frame.pixels.dtype == np.uint8
        assert frame.pixels.shape == (_FRAME_H, _FRAME_W, 4)
        # First byte = frame index (see _EchoCamera): proves shot()
        # returned the first frame, not a later one.
        assert int(frame.pixels[0, 0, 0]) == 0

    async def test_raises_when_not_connected(self):
        client = CameraClient()
        with pytest.raises(RuntimeError, match="not connected"):
            async for _ in client.stream():
                pass
