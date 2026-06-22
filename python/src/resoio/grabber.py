"""Client for the Resonite IO ``Grabber`` modality (Python -> Resonite).

Unary RPCs controlling what a hand holds and how it operates the held /
equipped item.

The Grabber service lets a Python client grab and release grabbable
objects in Resonite via a chosen hand (``primary`` / ``left`` /
``right``), then drive the post-grab interactions an avatar can perform:
left / right "click" with hold semantics, and equip / dequip of tools.

* :meth:`GrabberClient.grab` tries to grab a grabbable within a
  radius of the current desktop cursor ray's hit point and returns a
  :class:`GrabResult` (whether something was newly grabbed plus the
  resulting :class:`GrabState`). VR mode is rejected with
  ``FAILED_PRECONDITION``.
* :meth:`GrabberClient.release` releases everything the hand holds.
* :meth:`GrabberClient.get_state` returns the current hold state.
* :meth:`GrabberClient.use` presses a button (``primary`` left-click /
  ``secondary`` right-click) and *holds* it down — while grabbing this
  aligns the object, while a tool is equipped it activates the tool.
  The hold continues until :meth:`GrabberClient.unuse`, so a Pen can be
  pressed, dragged via the cursor, then released to draw a stroke.
* :meth:`GrabberClient.click` is a convenience that calls ``use`` then
  ``unuse`` for a single press (e.g. one-shot align).
* :meth:`GrabberClient.equip` / :meth:`GrabberClient.dequip` equip a
  grabbed tool into the hand / remove the equipped tool.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal, override

from grpclib.client import Channel

from resoio._client import _BaseClient
from resoio._generated.resonite_io.v1 import (
    GrabberButton,
    GrabberDequipRequest,
    GrabberEquipRequest,
    GrabberGetStateRequest,
    GrabberGrabRequest,
    GrabberGrabResult as _PbGrabberGrabResult,
    GrabberGrabState as _PbGrabberGrabState,
    GrabberHand,
    GrabberReleaseRequest,
    GrabberStub,
    GrabberUnuseRequest,
    GrabberUseRequest,
)

__all__ = [
    "GrabResult",
    "GrabState",
    "GrabberClient",
]

_logger = logging.getLogger(__name__)

GrabberHandArg = Literal["primary", "left", "right"]
GrabberButtonArg = Literal["primary", "secondary"]


@dataclass(frozen=True, slots=True)
class GrabState:
    """Snapshot of what a hand is currently holding / operating.

    ``hand`` echoes back which hand the server actually acted on, so a
    caller that passed ``"primary"`` learns whether it resolved to left
    or right (it is never ``"unspecified"`` — ``UNSPECIFIED`` decodes as
    ``"primary"``). ``object_names`` is a best-effort list of held
    grabbable slot names and may be empty even when ``is_holding`` is
    ``True``. ``is_tool_equipped`` / ``equipped_tool_name`` describe the
    tool currently equipped on the hand (``equipped_tool_name`` is empty
    when nothing is equipped). ``held_buttons`` lists the buttons
    currently held down via :meth:`GrabberClient.use` (cleared by
    :meth:`GrabberClient.unuse`).
    """

    hand: GrabberHandArg
    is_holding: bool
    object_names: tuple[str, ...]
    unix_nanos: int
    is_tool_equipped: bool
    equipped_tool_name: str
    held_buttons: tuple[GrabberButtonArg, ...]


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


def _button_to_proto(button: GrabberButtonArg) -> GrabberButton:
    if button == "secondary":
        return GrabberButton.SECONDARY
    return GrabberButton.PRIMARY


def _button_from_proto(button: GrabberButton) -> GrabberButtonArg:
    if button == GrabberButton.SECONDARY:
        return "secondary"
    # PRIMARY and UNSPECIFIED both map to "primary".
    return "primary"


def _state_from_proto(pb: _PbGrabberGrabState) -> GrabState:
    return GrabState(
        hand=_hand_from_proto(pb.hand),
        is_holding=pb.is_holding,
        object_names=tuple(pb.object_names),
        unix_nanos=pb.unix_nanos,
        is_tool_equipped=pb.is_tool_equipped,
        equipped_tool_name=pb.equipped_tool_name,
        held_buttons=tuple(_button_from_proto(b) for b in pb.held_buttons),
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

    async def use(
        self,
        *,
        hand: GrabberHandArg = "primary",
        button: GrabberButtonArg = "primary",
        strength: float = 1.0,
    ) -> GrabState:
        """Press ``button`` and hold it down until :meth:`unuse`.

        ``button="primary"`` is a left-click, ``"secondary"`` a
        right-click. While grabbing, a primary press aligns the held
        object; while a tool is equipped it activates the tool. The
        button stays held (re-injected every engine frame), so a Pen can
        be pressed, dragged via
        :meth:`resoio.CursorClient.set_position`, then released with
        :meth:`unuse` to draw a stroke.

        ``strength`` is the analog press strength (0..1) of the primary
        button, e.g. the pen pressure a ``BrushTool`` reads (default
        ``1.0``). It is held at the same value for the duration of the
        hold and is ignored for ``button="secondary"`` (which is digital
        only). Out-of-range values are clamped by the server.

        gRPC failures surface as :class:`grpclib.exceptions.GRPCError`.
        """
        request = GrabberUseRequest(
            hand=_hand_to_proto(hand),
            button=_button_to_proto(button),
            strength=strength,
        )
        return await self._dispatch(lambda stub: stub.use(request), _state_from_proto)

    async def unuse(
        self,
        *,
        hand: GrabberHandArg = "primary",
        button: GrabberButtonArg = "primary",
    ) -> GrabState:
        """Release ``button`` previously held via :meth:`use` (no-op if not
        held).

        gRPC failures surface as :class:`grpclib.exceptions.GRPCError`.
        """
        request = GrabberUnuseRequest(
            hand=_hand_to_proto(hand), button=_button_to_proto(button)
        )
        return await self._dispatch(lambda stub: stub.unuse(request), _state_from_proto)

    async def click(
        self,
        *,
        hand: GrabberHandArg = "primary",
        button: GrabberButtonArg = "primary",
        strength: float = 1.0,
    ) -> GrabState:
        """Press and release ``button`` once (a :meth:`use` then
        :meth:`unuse`).

        A convenience for single-shot interactions such as aligning a
        grabbed object, where the hold of :meth:`use` is not needed. The
        two RPCs run on separate engine ticks so the press registers
        before the release. Returns the state after :meth:`unuse`.

        ``strength`` is forwarded to the :meth:`use` press (analog
        primary press strength 0..1, default ``1.0``, ignored for
        secondary); :meth:`unuse` carries no strength.

        gRPC failures surface as :class:`grpclib.exceptions.GRPCError`.
        """
        await self.use(hand=hand, button=button, strength=strength)
        return await self.unuse(hand=hand, button=button)

    async def equip(self, *, hand: GrabberHandArg = "primary") -> GrabState:
        """Equip the grabbed tool into the hand (no-op if no tool is grabbed).

        Searches the hand's grabbed objects for an ``ITool`` component
        and equips the first one found. After equipping, :meth:`use`
        activates the tool's function.

        gRPC failures surface as :class:`grpclib.exceptions.GRPCError`.
        """
        request = GrabberEquipRequest(hand=_hand_to_proto(hand))
        return await self._dispatch(lambda stub: stub.equip(request), _state_from_proto)

    async def dequip(self, *, hand: GrabberHandArg = "primary") -> GrabState:
        """Remove the tool currently equipped on the hand (no-op if none).

        gRPC failures surface as :class:`grpclib.exceptions.GRPCError`.
        """
        request = GrabberDequipRequest(hand=_hand_to_proto(hand))
        return await self._dispatch(
            lambda stub: stub.dequip(request), _state_from_proto
        )
