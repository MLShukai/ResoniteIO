"""Client for the Resonite IO ``Cursor`` unary RPCs (desktop cursor).

The Cursor service controls the Resonite desktop cursor (mouse pointer).
Each RPC is a one-shot unary request/response. Positions use normalized
window coordinates in ``[0, 1]`` (center is ``(0.5, 0.5)``).

A common use is to center the cursor before opening a context menu: on
desktop the radial menu opens at the cursor's laser hit point, so
``await cursor.set_position(0.5, 0.5)`` followed by ``context_menu.open()``
yields a centered menu that still auto-closes on view movement.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from types import TracebackType
from typing import Self

from grpclib.client import Channel

from resoio._generated.resonite_io.v1 import (
    CursorGetPositionRequest,
    CursorSetPositionRequest,
    CursorState as _PbCursorState,
    CursorStub,
)
from resoio._socket import resolve_socket_path

__all__ = [
    "CursorClient",
    "CursorState",
]

_logger = logging.getLogger("resoio.cursor")


@dataclass(frozen=True, slots=True)
class CursorState:
    """Snapshot of the desktop cursor position.

    ``x`` / ``y`` are normalized window coordinates in ``[0, 1]`` (center
    is ``(0.5, 0.5)``). ``window_width`` / ``window_height`` are the
    window resolution in pixels, the basis for normalized <-> pixel.
    """

    x: float
    y: float
    window_width: int
    window_height: int


def _state_from_proto(pb: _PbCursorState) -> CursorState:
    return CursorState(
        x=pb.x,
        y=pb.y,
        window_width=pb.window_width,
        window_height=pb.window_height,
    )


class CursorClient:
    """Async client for the Resonite IO ``Cursor`` service over a UDS.

    Use as an async context manager so the gRPC channel is closed
    deterministically. Socket resolution mirrors
    :class:`resoio.SessionClient`.
    """

    def __init__(self, socket_path: str | None = None) -> None:
        self._explicit_path: str | None = socket_path
        self._channel: Channel | None = None
        self._stub: CursorStub | None = None
        self._resolved_path: str | None = None

    @property
    def socket_path(self) -> str | None:
        """Resolved UDS path, or ``None`` before ``__aenter__``."""
        return self._resolved_path

    async def __aenter__(self) -> Self:
        path = self._explicit_path or resolve_socket_path()
        _logger.debug("Opening Cursor channel on UDS path: %s", path)
        channel = Channel(path=path)
        self._channel = channel
        self._stub = CursorStub(channel)
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

    def _require_stub(self) -> CursorStub:
        stub = self._stub
        if stub is None:
            raise RuntimeError(
                "CursorClient is not connected. Use `async with CursorClient(): ...`."
            )
        return stub

    async def set_position(self, x: float, y: float) -> CursorState:
        """Move the cursor to normalized ``(x, y)`` and return the result.

        ``x`` and ``y`` must be in ``[0, 1]`` (center is ``(0.5, 0.5)``);
        out-of-range values surface as a
        :class:`grpclib.exceptions.GRPCError` (``INVALID_ARGUMENT``). The
        cursor is held at the requested position until moved again.
        """
        stub = self._require_stub()
        request = CursorSetPositionRequest(x=x, y=y)
        return _state_from_proto(await stub.set_position(request))

    async def get_position(self) -> CursorState:
        """Return the current cursor position without moving it."""
        stub = self._require_stub()
        return _state_from_proto(await stub.get_position(CursorGetPositionRequest()))
