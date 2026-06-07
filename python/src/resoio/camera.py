"""Client for the Resonite IO ``Camera`` gRPC streaming service."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import override

import numpy as np
from grpclib.client import Channel
from numpy.typing import NDArray

from resoio._client import _BaseClient
from resoio._generated.resonite_io.v1 import CameraStreamRequest, CameraStub

__all__ = [
    "CameraClient",
    "Frame",
]

_logger = logging.getLogger("resoio.camera")


@dataclass(frozen=True, slots=True)
class Frame:
    """One decoded camera frame.

    ``pixels`` is an ``(H, W, 4)`` RGBA8 view over the protobuf payload
    bytes (read-only; call ``.copy()`` for a writable array). Row 0 is
    the image top. ``unix_nanos`` is the server-side capture timestamp
    in UTC nanos since the Unix epoch. ``frame_id`` is a server-side
    monotonic counter that restarts at 0 per ``stream()`` call.
    """

    pixels: NDArray[np.uint8]
    width: int
    height: int
    unix_nanos: int
    frame_id: int


class CameraClient(_BaseClient[CameraStub]):
    """Async client for the Resonite IO ``Camera`` service over a UDS.

    Use as an async context manager so the gRPC channel is closed
    deterministically. Socket resolution mirrors
    :class:`resoio.ConnectionClient`.
    """

    _logger = _logger
    _log_label = "Camera"

    @override
    def _make_stub(self, channel: Channel) -> CameraStub:
        return CameraStub(channel)

    async def stream(
        self,
        width: int = 0,
        height: int = 0,
        fps_limit: float = 0.0,
    ) -> AsyncIterator[Frame]:
        """Stream camera frames from the server.

        ``width`` / ``height`` of 0 request the server default
        (640×480); ``fps_limit`` of 0 means uncapped (best-effort native
        fps). Raises :class:`RuntimeError` if called outside
        ``async with``.
        """
        stub = self._require_stub()
        request = CameraStreamRequest(
            width=width,
            height=height,
            fps_limit=fps_limit,
        )
        async for raw in stub.stream_frames(request):
            pixels = np.frombuffer(raw.pixels, dtype=np.uint8).reshape(
                raw.height, raw.width, 4
            )
            yield Frame(
                pixels=pixels,
                width=raw.width,
                height=raw.height,
                unix_nanos=raw.unix_nanos,
                frame_id=raw.frame_id,
            )
