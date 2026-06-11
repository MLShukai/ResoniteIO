"""Client for the Resonite IO ``Cursor`` modality (Python -> Resonite).

Unary RPCs controlling the Resonite desktop cursor (mouse pointer).
Positions use normalized window coordinates in ``[0, 1]`` (center is
``(0.5, 0.5)``).

``set_position`` moves the in-engine cursor and **holds** it there until
``release`` is called; the hold acts on the engine cursor only and never
grabs the OS mouse pointer. A typical flow is: ``set_position`` to aim
(e.g. ``(0.5, 0.5)`` so a context menu opens centered, or aiming the
cursor ray for a grab), perform the position-dependent operation, then
``release()`` to let the cursor follow the OS pointer again.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import override

from grpclib.client import Channel

from resoio._client import _BaseClient
from resoio._generated.resonite_io.v1 import (
    CursorGetPositionRequest,
    CursorReleaseRequest,
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
    ``held`` reports whether a ``set_position`` hold is in effect at the
    time of this snapshot.
    """

    x: float
    y: float
    window_width: int
    window_height: int
    held: bool


def _state_from_proto(pb: _PbCursorState) -> CursorState:
    return CursorState(
        x=pb.x,
        y=pb.y,
        window_width=pb.window_width,
        window_height=pb.window_height,
        held=pb.held,
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
        """Move the cursor to normalized ``(x, y)`` and hold it there.

        The cursor is held at the requested position until
        :meth:`release` is called; the returned state has
        ``held=True``. Calling again while held updates the held
        position. The hold acts on the in-engine cursor only and never
        grabs the OS mouse pointer. Side effect to be aware of: while
        held, human mouse movement does not reach the in-engine cursor,
        but clicks fire at the held position. Switching world focus
        deactivates the hold on the engine side and ``held`` becomes
        ``False`` (it is not re-applied automatically).

        ``x`` and ``y`` must be in ``[0, 1]`` (center is ``(0.5, 0.5)``);
        out-of-range values surface as a
        :class:`grpclib.exceptions.GRPCError` (``INVALID_ARGUMENT``).
        """
        stub = self._require_stub()
        request = CursorSetPositionRequest(x=x, y=y)
        return _state_from_proto(await stub.set_position(request))

    async def get_position(self) -> CursorState:
        """Return the current cursor position and hold state (no side
        effects)."""
        stub = self._require_stub()
        return _state_from_proto(await stub.get_position(CursorGetPositionRequest()))

    async def release(self) -> CursorState:
        """Release a :meth:`set_position` hold and return the new state.

        Idempotent: succeeds even when nothing is held. The returned
        state has ``held=False``. gRPC failures surface as
        :class:`grpclib.exceptions.GRPCError`.
        """
        stub = self._require_stub()
        return _state_from_proto(await stub.release(CursorReleaseRequest()))
