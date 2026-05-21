"""Client for the Resonite IO ``Display`` unary RPCs (window resolution + fps
cap)."""

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
    """Snapshot of engine-side display settings.

    ``max_fps`` is the *background* fps cap; foreground control is not
    exposed by the engine public Settings API.
    """

    width: int
    height: int
    max_fps: float


def _info_from_state(state: DisplayState) -> DisplayInfo:
    return DisplayInfo(
        width=state.width,
        height=state.height,
        max_fps=state.max_fps,
    )


class DisplayClient:
    """Async client for the Resonite IO ``Display`` service over a UDS.

    Use as an async context manager so the gRPC channel closes
    deterministically.
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
    ) -> None:
        """Apply a (partial) display config. Returns ``None``.

        ``0`` / ``0.0`` mean "leave unchanged" (proto3 default semantics).
        The engine commits the change asynchronously (settings dispatch hops
        to the engine thread), so reading the post-apply snapshot from the
        same RPC was unreliable — instead call :meth:`get` afterwards if you
        need to observe the new state. Raises :class:`RuntimeError` if called
        outside ``async with``.
        """
        stub = self._stub
        if stub is None:
            raise RuntimeError(
                "DisplayClient is not connected. Use `async with DisplayClient(): ...`."
            )
        request = DisplayConfig(width=width, height=height, max_fps=max_fps)
        await stub.apply(request)

    async def get(self) -> DisplayInfo:
        """Return the engine-side display state without modifying it."""
        stub = self._stub
        if stub is None:
            raise RuntimeError(
                "DisplayClient is not connected. Use `async with DisplayClient(): ...`."
            )
        state = await stub.get(DisplayGetRequest())
        return _info_from_state(state)
