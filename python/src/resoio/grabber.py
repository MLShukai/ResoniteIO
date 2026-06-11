"""Client for the Resonite IO ``Grabber`` modality (Python -> Resonite).

Unary RPCs (grab / release / get-state) controlling what a hand holds.

The Grabber service lets a Python client grab and release grabbable
objects in Resonite via a chosen hand (``primary`` / ``left`` /
``right``). Each RPC is a one-shot unary request/response. Step 6 covers
grab/release only — there is no hand-pose / fine-articulation control.

* :meth:`GrabberClient.grab` tries to grab a grabbable within a
  radius of the current desktop cursor ray's hit point and returns a
  :class:`GrabResult` (whether something was newly grabbed plus the
  resulting :class:`GrabState`). VR mode is rejected with
  ``FAILED_PRECONDITION``.
* :meth:`GrabberClient.release` releases everything the hand holds.
* :meth:`GrabberClient.get_state` returns the current hold state.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal, override

from grpclib.client import Channel

from resoio._client import _BaseClient
from resoio._generated.resonite_io.v1 import (
    GrabberGetStateRequest,
    GrabberGrabRequest,
    GrabberGrabResult as _PbGrabberGrabResult,
    GrabberGrabState as _PbGrabberGrabState,
    GrabberHand,
    GrabberReleaseRequest,
    GrabberStub,
)

__all__ = [
    "GrabResult",
    "GrabState",
    "GrabberClient",
]

_logger = logging.getLogger(__name__)

GrabberHandArg = Literal["primary", "left", "right"]


@dataclass(frozen=True, slots=True)
class GrabState:
    """Snapshot of what a hand is currently holding.

    ``hand`` echoes back which hand the server actually acted on, so a
    caller that passed ``"primary"`` learns whether it resolved to left
    or right (it is never ``"unspecified"`` — ``UNSPECIFIED`` decodes as
    ``"primary"``). ``object_names`` is a best-effort list of held
    grabbable slot names and may be empty even when ``is_holding`` is
    ``True``.
    """

    hand: GrabberHandArg
    is_holding: bool
    object_names: tuple[str, ...]
    unix_nanos: int


@dataclass(frozen=True, slots=True)
class GrabResult:
    """Result of a :meth:`GrabberClient.grab` call.

    ``grabbed`` is ``True`` only when this call newly grabbed something;
    a ray miss or nothing grabbable in range is reported as
    ``grabbed=False`` rather than an error. ``state`` is the hold state
    after the call.
    """

    grabbed: bool
    state: GrabState


def _hand_to_proto(hand: GrabberHandArg) -> GrabberHand:
    if hand == "primary":
        return GrabberHand.PRIMARY
    if hand == "left":
        return GrabberHand.LEFT
    return GrabberHand.RIGHT


def _hand_from_proto(hand: GrabberHand) -> GrabberHandArg:
    if hand == GrabberHand.LEFT:
        return "left"
    if hand == GrabberHand.RIGHT:
        return "right"
    # PRIMARY and UNSPECIFIED both map to "primary".
    return "primary"


def _state_from_proto(pb: _PbGrabberGrabState) -> GrabState:
    return GrabState(
        hand=_hand_from_proto(pb.hand),
        is_holding=pb.is_holding,
        object_names=tuple(pb.object_names),
        unix_nanos=pb.unix_nanos,
    )


def _result_from_proto(pb: _PbGrabberGrabResult) -> GrabResult:
    state = pb.state if pb.state is not None else _PbGrabberGrabState()
    return GrabResult(grabbed=pb.grabbed, state=_state_from_proto(state))


class GrabberClient(_BaseClient[GrabberStub]):
    """Async client for the Resonite IO ``Grabber`` service over a UDS.

    Use as an async context manager so the gRPC channel is closed
    deterministically. Socket resolution mirrors
    :class:`resoio.ConnectionClient`.
    """

    _logger = _logger
    _log_label = "Grabber"

    @override
    def _make_stub(self, channel: Channel) -> GrabberStub:
        return GrabberStub(channel)

    async def _dispatch[T, R](
        self,
        rpc: Callable[[GrabberStub], Awaitable[T]],
        decode: Callable[[T], R],
    ) -> R:
        """Run a unary RPC against the connected stub and decode the result.

        Centralises the not-connected guard shared by every RPC. ``rpc``
        selects the stub method and supplies its request; ``decode``
        turns the proto reply into the public dataclass (the reply type
        differs per RPC). gRPC failures surface as
        :class:`grpclib.exceptions.GRPCError`.
        """
        return decode(await rpc(self._require_stub()))

    async def grab(
        self,
        *,
        hand: GrabberHandArg = "primary",
        radius: float = 0.0,
    ) -> GrabResult:
        """Grab a grabbable near the cursor ray hit point.

        Grabs a grabbable within ``radius`` metres (``<= 0`` lets the
        server apply its default, 0.1m) of the current desktop cursor
        ray's hit point. Aim beforehand with
        :meth:`resoio.CursorClient.set_position`. A ray miss or nothing
        grabbable in range is reported as
        ``GrabResult.grabbed == False``, not an error. In VR mode the
        call fails with :class:`grpclib.exceptions.GRPCError`
        (``FAILED_PRECONDITION``).

        gRPC failures surface as :class:`grpclib.exceptions.GRPCError`.
        """
        request = GrabberGrabRequest(hand=_hand_to_proto(hand), radius=radius)
        return await self._dispatch(lambda stub: stub.grab(request), _result_from_proto)

    async def release(self, *, hand: GrabberHandArg = "primary") -> GrabState:
        """Release everything the hand is holding and return the new state.

        gRPC failures surface as :class:`grpclib.exceptions.GRPCError`.
        """
        request = GrabberReleaseRequest(hand=_hand_to_proto(hand))
        return await self._dispatch(
            lambda stub: stub.release(request), _state_from_proto
        )

    async def get_state(self, *, hand: GrabberHandArg = "primary") -> GrabState:
        """Return the hand's current hold state without modifying it.

        gRPC failures surface as :class:`grpclib.exceptions.GRPCError`.
        """
        request = GrabberGetStateRequest(hand=_hand_to_proto(hand))
        return await self._dispatch(
            lambda stub: stub.get_state(request), _state_from_proto
        )
