"""Client for the Resonite IO ``Cursor`` modality (Python -> Resonite).

Unary RPCs controlling the Resonite desktop cursor (mouse pointer). Each
RPC is a one-shot request/response. Positions use normalized window
coordinates in ``[0, 1]`` (center is ``(0.5, 0.5)``).

A common use is to center the cursor before opening a context menu: on
desktop the radial menu opens at the cursor's laser hit point, so
``await cursor.set_position(0.5, 0.5)`` followed by ``context_menu.open()``
aims for a centered menu. Note that ``set_position`` is a one-shot warp
that does not hold the cursor afterwards; under Wine/Proton the OS pointer
cannot be moved, so the position may revert before a follow-up call and
position-dependent flows are only reliable within the same operation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import override

from grpclib.client import Channel

from resoio._client import _BaseClient
from resoio._generated.resonite_io.v1 import (
    CursorGetPositionRequest,
    CursorSetPositionRequest,
    CursorState as _PbCursorState,
    CursorStub,
)

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


class CursorClient(_BaseClient[CursorStub]):
    """Async client for the Resonite IO ``Cursor`` service over a UDS.

    Use as an async context manager so the gRPC channel is closed
    deterministically. Socket resolution mirrors
    :class:`resoio.ConnectionClient`.
    """

    _logger = _logger
    _log_label = "Cursor"

    @override
    def _make_stub(self, channel: Channel) -> CursorStub:
        return CursorStub(channel)

    async def set_position(self, x: float, y: float) -> CursorState:
        """Move the cursor to normalized ``(x, y)`` and return the result.

        ``x`` and ``y`` must be in ``[0, 1]`` (center is ``(0.5, 0.5)``);
        out-of-range values surface as a
        :class:`grpclib.exceptions.GRPCError` (``INVALID_ARGUMENT``). The
        move is a one-shot warp: the cursor is not held at the requested
        position and the mouse stays free after the call returns. Under
        Wine/Proton the OS pointer cannot be moved, so the cursor may
        revert to the real pointer position on the next frame.
        """
        stub = self._require_stub()
        request = CursorSetPositionRequest(x=x, y=y)
        return _state_from_proto(await stub.set_position(request))

    async def get_position(self) -> CursorState:
        """Return the current cursor position without moving it."""
        stub = self._require_stub()
        return _state_from_proto(await stub.get_position(CursorGetPositionRequest()))
