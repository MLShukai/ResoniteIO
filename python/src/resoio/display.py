"""Client for the Resonite IO ``Display`` gRPC unary service.

``DisplayClient`` lets a Python caller read and write engine-side
display settings (window resolution + background framerate cap) through
the unary ``Apply`` / ``Get`` RPCs defined in
``proto/resonite_io/v1/display.proto``. Camera v2 streams hit the
engine-side fps cap, so callers typically pair this with
:class:`resoio.CameraClient` to raise the cap before opening a stream.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from types import TracebackType
from typing import Self

from grpclib.client import Channel

from resoio._generated.resonite_io.v1 import (
    DisplayConfig,
    DisplayGetRequest,
    DisplayState,
    DisplayStub,
)
from resoio._socket import resolve_socket_path

__all__ = [
    "DisplayClient",
    "DisplayInfo",
]

_logger = logging.getLogger("resoio.display")


@dataclass(frozen=True, slots=True)
class DisplayInfo:
    """Snapshot of the actual engine-side display settings.

    ``width`` / ``height`` are the current target window resolution in
    pixels. ``max_fps`` is the engine-applied framerate cap (currently
    the background-FPS cap; foreground control is not exposed by the
    engine public Settings API as of FrooxEngine 2025.x).
    """

    width: int
    height: int
    max_fps: float


def _info_from_state(state: DisplayState) -> DisplayInfo:
    """Build a public :class:`DisplayInfo` from the generated proto type.

    Kept module-private so callers depend on :class:`DisplayInfo` rather
    than the generated ``DisplayState``.
    """
    return DisplayInfo(
        width=state.width,
        height=state.height,
        max_fps=state.max_fps,
    )


class DisplayClient:
    """Async client for the Resonite IO ``Display`` service over a UDS.

    Use as an async context manager so the gRPC channel is closed
    deterministically. Socket resolution mirrors
    :class:`resoio.SessionClient` / :class:`resoio.CameraClient`.
    """

    def __init__(self, socket_path: str | None = None) -> None:
        self._explicit_path: str | None = socket_path
        self._channel: Channel | None = None
        self._stub: DisplayStub | None = None
        self._resolved_path: str | None = None

    @property
    def socket_path(self) -> str | None:
        """Resolved UDS path, or ``None`` before ``__aenter__``."""
        return self._resolved_path

    async def __aenter__(self) -> Self:
        path = self._explicit_path or resolve_socket_path()
        _logger.debug("Opening Display channel on UDS path: %s", path)
        channel = Channel(path=path)
        self._channel = channel
        self._stub = DisplayStub(channel)
        self._resolved_path = path
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        channel = self._channel
        self._channel = None
        self._stub = None
        self._resolved_path = None
        if channel is not None:
            channel.close()

    async def apply(
        self,
        *,
        width: int = 0,
        height: int = 0,
        max_fps: float = 0.0,
    ) -> DisplayInfo:
        """Apply a (partial) display config and return the resulting state.

        Zero values are passed through to the server, which interprets
        ``0`` / ``0.0`` as "leave the field unchanged" (proto3 default
        value semantics). Returned ``DisplayInfo`` reflects the
        engine-side state *after* the partial update.

        Raises :class:`RuntimeError` if called outside ``async with``.
        """
        stub = self._stub
        if stub is None:
            raise RuntimeError(
                "DisplayClient is not connected. Use `async with DisplayClient(): ...`."
            )
        request = DisplayConfig(width=width, height=height, max_fps=max_fps)
        state = await stub.apply(request)
        return _info_from_state(state)

    async def get(self) -> DisplayInfo:
        """Return the engine-side display state without modifying it.

        Raises :class:`RuntimeError` if called outside ``async with``.
        """
        stub = self._stub
        if stub is None:
            raise RuntimeError(
                "DisplayClient is not connected. Use `async with DisplayClient(): ...`."
            )
        state = await stub.get(DisplayGetRequest())
        return _info_from_state(state)
