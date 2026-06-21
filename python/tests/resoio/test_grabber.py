"""Integration-real tests for :class:`resoio.grabber.GrabberClient`.

A real ``grpclib.server.Server`` hosting an inline fake
:class:`GrabberBase` handler is bound to a real UDS under ``tmp_path``
and driven by the real ``GrabberClient`` over the wire (no mocking of
grpclib/betterproto2 internals). This verifies that each of the three unary
RPCs (``grab`` / ``release`` / ``get_state``) reaches the server with the
correct ``hand`` enum and ``radius`` (grab is always a proximity grab around
the desktop cursor-ray hit point, so there is no point argument), and that
the returned ``GrabResult`` / ``GrabState`` dataclasses round-trip every
field — including the ``object_names`` repeated-string ordering and the
``hand`` decode path.
"""

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

import pytest
from grpclib import GRPCError, Status
from grpclib.exceptions import GRPCError as ClientGRPCError

from resoio._generated.resonite_io.v1 import (
    GrabberBase,
    GrabberButton,
    GrabberDequipRequest,
    GrabberEquipRequest,
    GrabberGetStateRequest,
    GrabberGrabRequest,
    GrabberGrabResult as PbGrabberGrabResult,
    GrabberGrabState as PbGrabberGrabState,
    GrabberHand,
    GrabberReleaseRequest,
    GrabberUnuseRequest,
    GrabberUseRequest,
)
from resoio.grabber import GrabberClient, GrabResult, GrabState

if TYPE_CHECKING:
    from grpclib._typing import IServable

UdsServer = Callable[["IServable"], Awaitable[str]]

# Radius chosen to be exactly representable in float32 so the wire
# round-trip carries it without precision drift (radius is a proto
# `float`, i.e. 32-bit).
_RADIUS = 0.25


class _EchoGrabber(GrabberBase):
    """In-process fake recording each request and echoing it into the reply.

    Every RPC stores the request it received (so a test can assert the
    ``hand`` enum, ``point`` and ``radius`` that reached the server) and
    returns a deterministic ``GrabberGrabState`` whose ``hand`` echoes
    the request hand — letting a test verify the client-side hand-decode
    path end-to-end. ``unix_nanos`` is stamped with a fixed positive value
    so the decode of the timestamp field is observable.
    """

    def __init__(self) -> None:
        self.grab_requests: list[GrabberGrabRequest] = []
        self.release_requests: list[GrabberReleaseRequest] = []
        self.get_state_requests: list[GrabberGetStateRequest] = []
        self.use_requests: list[GrabberUseRequest] = []
        self.unuse_requests: list[GrabberUnuseRequest] = []
        self.equip_requests: list[GrabberEquipRequest] = []
        self.dequip_requests: list[GrabberDequipRequest] = []

    async def grab(self, message: GrabberGrabRequest) -> PbGrabberGrabResult:
        self.grab_requests.append(message)
        return PbGrabberGrabResult(
            grabbed=True,
            state=PbGrabberGrabState(
                hand=message.hand,
                is_holding=True,
                object_names=["Cube"],
                unix_nanos=1234,
            ),
        )

    async def release(self, message: GrabberReleaseRequest) -> PbGrabberGrabState:
        self.release_requests.append(message)
        return PbGrabberGrabState(
            hand=message.hand,
            is_holding=False,
            object_names=[],
            unix_nanos=5678,
        )

    async def get_state(self, message: GrabberGetStateRequest) -> PbGrabberGrabState:
        self.get_state_requests.append(message)
        return PbGrabberGrabState(
            hand=message.hand,
            is_holding=True,
            object_names=["Cube", "Sphere", "Cone"],
            unix_nanos=9012,
        )

    async def use(self, message: GrabberUseRequest) -> PbGrabberGrabState:
        self.use_requests.append(message)
        # Echo the pressed button as currently held, so a test can verify the
        # button enum reached the server and the held_buttons decode path.
        return PbGrabberGrabState(
            hand=message.hand,
            is_holding=True,
            object_names=["Cube"],
            unix_nanos=2468,
            held_buttons=[message.button],
        )

    async def unuse(self, message: GrabberUnuseRequest) -> PbGrabberGrabState:
        self.unuse_requests.append(message)
        return PbGrabberGrabState(
            hand=message.hand,
            is_holding=True,
            object_names=["Cube"],
            unix_nanos=1357,
            held_buttons=[],
        )

    async def equip(self, message: GrabberEquipRequest) -> PbGrabberGrabState:
        self.equip_requests.append(message)
        return PbGrabberGrabState(
            hand=message.hand,
            is_holding=False,
            object_names=[],
            unix_nanos=3690,
            is_tool_equipped=True,
            equipped_tool_name="Pen",
        )

    async def dequip(self, message: GrabberDequipRequest) -> PbGrabberGrabState:
        self.dequip_requests.append(message)
        return PbGrabberGrabState(
            hand=message.hand,
            is_holding=False,
            object_names=[],
            unix_nanos=4812,
            is_tool_equipped=False,
            equipped_tool_name="",
        )


class _VrModeGrabber(GrabberBase):
    """Fake server in VR mode: ``grab`` fails with FAILED_PRECONDITION.

    Mirrors the C# contract: grab requires desktop (screen) mode, so a VR
    server rejects it with FAILED_PRECONDITION (it is *not* grabbed=False).
    """

    _VR_MESSAGE = "Grab requires desktop (screen) mode; VR is active."

    async def grab(self, message: GrabberGrabRequest) -> PbGrabberGrabResult:
        raise GRPCError(Status.FAILED_PRECONDITION, self._VR_MESSAGE)

    async def release(self, message: GrabberReleaseRequest) -> PbGrabberGrabState:
        raise GRPCError(Status.FAILED_PRECONDITION, self._VR_MESSAGE)

    async def get_state(self, message: GrabberGetStateRequest) -> PbGrabberGrabState:
        raise GRPCError(Status.FAILED_PRECONDITION, self._VR_MESSAGE)


class TestGrabberClient:
    async def test_grab_sends_hand_and_radius_and_round_trips_result(
        self, uds_server: UdsServer
    ):
        # Grab carries only hand + radius on the wire (the grab centre is
        # the desktop cursor-ray hit point, resolved server-side); the
        # GrabResult / GrabState decode every field.
        fake = _EchoGrabber()
        socket_path = await uds_server(fake)
        async with GrabberClient() as client:
            assert client.socket_path == socket_path
            result = await client.grab(hand="left", radius=_RADIUS)

        assert len(fake.grab_requests) == 1
        wire = fake.grab_requests[0]
        assert wire.hand == GrabberHand.LEFT
        assert wire.radius == _RADIUS

        assert isinstance(result, GrabResult)
        assert result.grabbed is True
        assert isinstance(result.state, GrabState)
        assert result.state.is_holding is True
        assert result.state.object_names == ("Cube",)
        assert result.state.unix_nanos == 1234
        # Appended fields decode to their proto3 defaults when unset by server.
        assert result.state.is_tool_equipped is False
        assert result.state.equipped_tool_name == ""
        assert result.state.held_buttons == ()

    async def test_grab_sends_radius_verbatim_including_zero_default(
        self, uds_server: UdsServer
    ):
        fake = _EchoGrabber()
        await uds_server(fake)
        async with GrabberClient() as client:
            # Client default radius is 0.0. Expanding `<= 0` to the
            # server-side default (0.1m) is a C#-Core concern; here we
            # only pin that the client transmits exactly what it was
            # given (0.0), not a silently substituted value.
            await client.grab()

        assert len(fake.grab_requests) == 1
        assert fake.grab_requests[0].radius == 0.0

    async def test_grab_default_hand_is_primary_on_wire(self, uds_server: UdsServer):
        fake = _EchoGrabber()
        await uds_server(fake)
        async with GrabberClient() as client:
            await client.grab()

        assert fake.grab_requests[0].hand == GrabberHand.PRIMARY

    async def test_grab_primary_hand_round_trips(self, uds_server: UdsServer):
        fake = _EchoGrabber()
        await uds_server(fake)
        async with GrabberClient() as client:
            result = await client.grab(hand="primary")

        assert fake.grab_requests[0].hand == GrabberHand.PRIMARY
        # Fake echoes the request hand; PRIMARY must decode to "primary".
        assert result.state.hand == "primary"

    async def test_grab_left_hand_round_trips(self, uds_server: UdsServer):
        fake = _EchoGrabber()
        await uds_server(fake)
        async with GrabberClient() as client:
            result = await client.grab(hand="left")

        assert fake.grab_requests[0].hand == GrabberHand.LEFT
        assert result.state.hand == "left"

    async def test_grab_right_hand_round_trips(self, uds_server: UdsServer):
        fake = _EchoGrabber()
        await uds_server(fake)
        async with GrabberClient() as client:
            result = await client.grab(hand="right")

        assert fake.grab_requests[0].hand == GrabberHand.RIGHT
        assert result.state.hand == "right"

    async def test_unspecified_hand_decodes_as_primary(self, uds_server: UdsServer):
        """A server reply carrying ``UNSPECIFIED`` (the proto default for an
        unset enum) must surface to callers as ``"primary"`` — the documented
        fold of UNSPECIFIED/PRIMARY onto a single public literal."""

        class _UnspecifiedHand(GrabberBase):
            async def grab(self, message: GrabberGrabRequest) -> PbGrabberGrabResult:
                return PbGrabberGrabResult(
                    grabbed=False,
                    state=PbGrabberGrabState(
                        hand=GrabberHand.UNSPECIFIED,
                        is_holding=False,
                        object_names=[],
                        unix_nanos=1,
                    ),
                )

            async def release(
                self, message: GrabberReleaseRequest
            ) -> PbGrabberGrabState:
                raise NotImplementedError

            async def get_state(
                self, message: GrabberGetStateRequest
            ) -> PbGrabberGrabState:
                raise NotImplementedError

        await uds_server(_UnspecifiedHand())
        async with GrabberClient() as client:
            result = await client.grab()

        assert result.state.hand == "primary"

    async def test_release_returns_not_holding_state(self, uds_server: UdsServer):
        fake = _EchoGrabber()
        await uds_server(fake)
        async with GrabberClient() as client:
            state = await client.release(hand="left")

        assert len(fake.release_requests) == 1
        assert fake.release_requests[0].hand == GrabberHand.LEFT
        # release must not issue a grab/get_state RPC.
        assert fake.grab_requests == []
        assert fake.get_state_requests == []

        assert isinstance(state, GrabState)
        assert state.hand == "left"
        assert state.is_holding is False
        assert state.object_names == ()
        assert state.unix_nanos == 5678

    async def test_get_state_decodes_repeated_object_names_in_order(
        self, uds_server: UdsServer
    ):
        fake = _EchoGrabber()
        await uds_server(fake)
        async with GrabberClient() as client:
            state = await client.get_state(hand="right")

        assert len(fake.get_state_requests) == 1
        assert fake.get_state_requests[0].hand == GrabberHand.RIGHT
        # get_state must be read-only: no mutating RPC issued.
        assert fake.grab_requests == []
        assert fake.release_requests == []

        assert state.hand == "right"
        assert state.is_holding is True
        # >1 distinct names, in declared order, as an immutable tuple —
        # proves repeated-string decode preserves count and ordering.
        assert state.object_names == ("Cube", "Sphere", "Cone")
        assert isinstance(state.object_names, tuple)

    async def test_grab_in_vr_mode_surfaces_failed_precondition(
        self, uds_server: UdsServer
    ):
        # Spec: grab in VR mode (screen not active) is FAILED_PRECONDITION,
        # not grabbed=False. The message is pinned only by the "desktop"
        # substring (exact wording is not part of the contract).
        await uds_server(_VrModeGrabber())
        async with GrabberClient() as client:
            with pytest.raises(ClientGRPCError) as exc_info:
                await client.grab(radius=_RADIUS)

        assert exc_info.value.status is Status.FAILED_PRECONDITION
        assert "desktop" in (exc_info.value.message or "")

    # --- use / unuse / click (button hold) ---------------------------------

    async def test_use_sends_hand_and_default_primary_button(
        self, uds_server: UdsServer
    ):
        fake = _EchoGrabber()
        await uds_server(fake)
        async with GrabberClient() as client:
            state = await client.use(hand="left")

        assert len(fake.use_requests) == 1
        wire = fake.use_requests[0]
        assert wire.hand == GrabberHand.LEFT
        # No button arg -> default primary (left-click).
        assert wire.button == GrabberButton.PRIMARY
        # The pressed button surfaces as held; PRIMARY decodes to "primary".
        assert state.held_buttons == ("primary",)

    async def test_use_sends_secondary_button(self, uds_server: UdsServer):
        fake = _EchoGrabber()
        await uds_server(fake)
        async with GrabberClient() as client:
            state = await client.use(hand="right", button="secondary")

        assert fake.use_requests[0].button == GrabberButton.SECONDARY
        assert state.held_buttons == ("secondary",)

    async def test_unuse_sends_button_and_returns_released_state(
        self, uds_server: UdsServer
    ):
        fake = _EchoGrabber()
        await uds_server(fake)
        async with GrabberClient() as client:
            state = await client.unuse(button="secondary")

        assert len(fake.unuse_requests) == 1
        assert fake.unuse_requests[0].button == GrabberButton.SECONDARY
        # unuse must not issue a use RPC.
        assert fake.use_requests == []
        assert state.held_buttons == ()

    async def test_click_sends_use_then_unuse_with_same_hand_and_button(
        self, uds_server: UdsServer
    ):
        fake = _EchoGrabber()
        await uds_server(fake)
        async with GrabberClient() as client:
            state = await client.click(hand="left", button="secondary")

        # click = press (use) then release (unuse), same hand + button.
        assert len(fake.use_requests) == 1
        assert len(fake.unuse_requests) == 1
        assert fake.use_requests[0].hand == GrabberHand.LEFT
        assert fake.use_requests[0].button == GrabberButton.SECONDARY
        assert fake.unuse_requests[0].hand == GrabberHand.LEFT
        assert fake.unuse_requests[0].button == GrabberButton.SECONDARY
        # Returned state is the one after unuse (button released).
        assert state.held_buttons == ()
        assert state.unix_nanos == 1357

    # --- equip / dequip (tool lifecycle) -----------------------------------

    async def test_equip_returns_tool_equipped_state(self, uds_server: UdsServer):
        fake = _EchoGrabber()
        await uds_server(fake)
        async with GrabberClient() as client:
            state = await client.equip(hand="right")

        assert len(fake.equip_requests) == 1
        assert fake.equip_requests[0].hand == GrabberHand.RIGHT
        assert state.is_tool_equipped is True
        assert state.equipped_tool_name == "Pen"

    async def test_dequip_returns_not_equipped_state(self, uds_server: UdsServer):
        fake = _EchoGrabber()
        await uds_server(fake)
        async with GrabberClient() as client:
            state = await client.dequip(hand="left")

        assert len(fake.dequip_requests) == 1
        assert fake.dequip_requests[0].hand == GrabberHand.LEFT
        # dequip must not issue an equip RPC.
        assert fake.equip_requests == []
        assert state.is_tool_equipped is False
        assert state.equipped_tool_name == ""

    async def test_grab_raises_when_not_connected(self):
        client = GrabberClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.grab()

    async def test_release_raises_when_not_connected(self):
        client = GrabberClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.release()

    async def test_get_state_raises_when_not_connected(self):
        client = GrabberClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.get_state()

    async def test_use_raises_when_not_connected(self):
        client = GrabberClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.use()

    async def test_unuse_raises_when_not_connected(self):
        client = GrabberClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.unuse()

    async def test_equip_raises_when_not_connected(self):
        client = GrabberClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.equip()

    async def test_dequip_raises_when_not_connected(self):
        client = GrabberClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.dequip()
