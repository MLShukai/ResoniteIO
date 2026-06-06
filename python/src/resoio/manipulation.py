"""Client for the Resonite IO ``Manipulation`` unary RPCs (grab / release).

The Manipulation service lets a Python client grab and release grabbable
objects in Resonite via a chosen hand (``primary`` / ``left`` /
``right``). Each RPC is a one-shot unary request/response. Step 6 covers
grab/release only — there is no hand-pose / fine-articulation control.

* :meth:`ManipulationClient.grab` tries to grab a grabbable within a
  radius of a world point (or the hand's current position) and returns a
  :class:`GrabResult` (whether something was newly grabbed plus the
  resulting :class:`GrabState`).
* :meth:`ManipulationClient.release` releases everything the hand holds.
* :meth:`ManipulationClient.get_state` returns the current hold state.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from types import TracebackType
from typing import Literal, Self, TypeVar

from grpclib.client import Channel

from resoio._generated.resonite_io.v1 import (
    ManipulationGetStateRequest,
    ManipulationGrabRequest,
    ManipulationGrabResult as _PbManipulationGrabResult,
    ManipulationGrabState as _PbManipulationGrabState,
    ManipulationHand,
    ManipulationReleaseRequest,
    ManipulationStub,
    WorldPoint,
)
from resoio._socket import resolve_socket_path

__all__ = [
    "GrabResult",
    "GrabState",
    "ManipulationClient",
]

_logger = logging.getLogger("resoio.manipulation")

ManipulationHandArg = Literal["primary", "left", "right"]

_T = TypeVar("_T")
_R = TypeVar("_R")


@dataclass(frozen=True, slots=True)
class GrabState:
    """Snapshot of what a hand is currently holding.

    ``hand`` is the resolved target hand (never ``"unspecified"`` —
    ``UNSPECIFIED`` is decoded as ``"primary"``). ``object_names`` is a
    best-effort list of held grabbable slot names and may be empty even
    when ``is_holding`` is ``True``.
    """

    hand: ManipulationHandArg
    is_holding: bool
    object_names: tuple[str, ...]
    unix_nanos: int


@dataclass(frozen=True, slots=True)
class GrabResult:
    """Result of a :meth:`ManipulationClient.grab` call.

    ``grabbed`` is ``True`` only when this call newly grabbed something;
    an empty radius (nothing grabbable in range) is reported as
    ``grabbed=False`` rather than an error. ``state`` is the hold state
    after the call.
    """

    grabbed: bool
    state: GrabState


def _hand_to_proto(hand: ManipulationHandArg) -> ManipulationHand:
    if hand == "primary":
        return ManipulationHand.PRIMARY
    if hand == "left":
        return ManipulationHand.LEFT
    return ManipulationHand.RIGHT


def _hand_from_proto(hand: ManipulationHand) -> ManipulationHandArg:
    if hand == ManipulationHand.LEFT:
        return "left"
    if hand == ManipulationHand.RIGHT:
        return "right"
    # PRIMARY and UNSPECIFIED both map to "primary".
    return "primary"


def _state_from_proto(pb: _PbManipulationGrabState) -> GrabState:
    return GrabState(
        hand=_hand_from_proto(pb.hand),
        is_holding=pb.is_holding,
        object_names=tuple(pb.object_names),
        unix_nanos=pb.unix_nanos,
    )


def _result_from_proto(pb: _PbManipulationGrabResult) -> GrabResult:
    state = pb.state if pb.state is not None else _PbManipulationGrabState()
    return GrabResult(grabbed=pb.grabbed, state=_state_from_proto(state))


class ManipulationClient:
    """Async client for the Resonite IO ``Manipulation`` service over a UDS.

    Use as an async context manager so the gRPC channel is closed
    deterministically. Socket resolution mirrors
    :class:`resoio.SessionClient`.
    """

    def __init__(self, socket_path: str | None = None) -> None:
        self._explicit_path: str | None = socket_path
        self._channel: Channel | None = None
        self._stub: ManipulationStub | None = None
        self._resolved_path: str | None = None

    @property
    def socket_path(self) -> str | None:
        """Resolved UDS path, or ``None`` before ``__aenter__``."""
        return self._resolved_path

    async def __aenter__(self) -> Self:
        path = self._explicit_path or resolve_socket_path()
        _logger.debug("Opening Manipulation channel on UDS path: %s", path)
        channel = Channel(path=path)
        self._channel = channel
        self._stub = ManipulationStub(channel)
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

    async def _dispatch(
        self,
        rpc: Callable[[ManipulationStub], Awaitable[_T]],
        decode: Callable[[_T], _R],
    ) -> _R:
        """Run a unary RPC against the connected stub and decode the result.

        Centralises the not-connected guard shared by every RPC. ``rpc``
        selects the stub method and supplies its request; ``decode``
        turns the proto reply into the public dataclass (the reply type
        differs per RPC). gRPC failures surface as
        :class:`grpclib.exceptions.GRPCError`.
        """
        stub = self._stub
        if stub is None:
            raise RuntimeError(
                "ManipulationClient is not connected. "
                "Use `async with ManipulationClient(): ...`."
            )
        return decode(await rpc(stub))

    async def grab(
        self,
        *,
        hand: ManipulationHandArg = "primary",
        point: tuple[float, float, float] | None = None,
        radius: float = 0.0,
    ) -> GrabResult:
        """Grab a grabbable in range and return the resulting state.

        ``point`` is the world-space grab centre; when ``None`` the
        server uses the hand's current position. ``radius`` is the grab
        sphere radius in metres — a value ``<= 0`` lets the server apply
        its default. Finding nothing grabbable in range is reported as
        ``GrabResult.grabbed == False``, not an error.

        gRPC failures surface as :class:`grpclib.exceptions.GRPCError`.
        """
        request = ManipulationGrabRequest(hand=_hand_to_proto(hand), radius=radius)
        if point is not None:
            request.point = WorldPoint(x=point[0], y=point[1], z=point[2])
        return await self._dispatch(lambda stub: stub.grab(request), _result_from_proto)

    async def release(self, *, hand: ManipulationHandArg = "primary") -> GrabState:
        """Release everything the hand is holding and return the new state.

        gRPC failures surface as :class:`grpclib.exceptions.GRPCError`.
        """
        request = ManipulationReleaseRequest(hand=_hand_to_proto(hand))
        return await self._dispatch(
            lambda stub: stub.release(request), _state_from_proto
        )

    async def get_state(self, *, hand: ManipulationHandArg = "primary") -> GrabState:
        """Return the hand's current hold state without modifying it.

        gRPC failures surface as :class:`grpclib.exceptions.GRPCError`.
        """
        request = ManipulationGetStateRequest(hand=_hand_to_proto(hand))
        return await self._dispatch(
            lambda stub: stub.get_state(request), _state_from_proto
        )
