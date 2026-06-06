"""Integration-real tests for :class:`resoio.manipulation.ManipulationClient`.

A real ``grpclib.server.Server`` hosting an inline fake
:class:`ManipulationBase` handler is bound to a real UDS under ``tmp_path``
and driven by the real ``ManipulationClient`` over the wire (no mocking of
grpclib/betterproto2 internals). This verifies that each of the three unary
RPCs (``grab`` / ``release`` / ``get_state``) reaches the server with the
correct ``hand`` enum, ``point`` (``WorldPoint`` or absent) and ``radius``,
and that the returned ``GrabResult`` / ``GrabState`` dataclasses round-trip
every field — including the ``object_names`` repeated-string ordering and
the ``hand`` decode path.
"""

from pathlib import Path

import pytest
from grpclib import GRPCError, Status
from grpclib.exceptions import GRPCError as ClientGRPCError
from grpclib.server import Server

from resoio._generated.resonite_io.v1 import (
    ManipulationBase,
    ManipulationGetStateRequest,
    ManipulationGrabRequest,
    ManipulationGrabResult as PbManipulationGrabResult,
    ManipulationGrabState as PbManipulationGrabState,
    ManipulationHand,
    ManipulationReleaseRequest,
)
from resoio.manipulation import GrabResult, GrabState, ManipulationClient

# Coordinates / radius chosen to be exactly representable in float32 so the
# wire round-trip carries them without precision drift (radius is a proto
# `float`, i.e. 32-bit).
_POINT = (1.0, 2.0, 3.0)
_RADIUS = 0.25


class _EchoManipulation(ManipulationBase):
    """In-process fake recording each request and echoing it into the reply.

    Every RPC stores the request it received (so a test can assert the
    ``hand`` enum, ``point`` and ``radius`` that reached the server) and
    returns a deterministic ``ManipulationGrabState`` whose ``hand`` echoes
    the request hand — letting a test verify the client-side hand-decode
    path end-to-end. ``unix_nanos`` is stamped with a fixed positive value
    so the decode of the timestamp field is observable.
    """

    def __init__(self) -> None:
        self.grab_requests: list[ManipulationGrabRequest] = []
        self.release_requests: list[ManipulationReleaseRequest] = []
        self.get_state_requests: list[ManipulationGetStateRequest] = []

    async def grab(self, message: ManipulationGrabRequest) -> PbManipulationGrabResult:
        self.grab_requests.append(message)
        return PbManipulationGrabResult(
            grabbed=True,
            state=PbManipulationGrabState(
                hand=message.hand,
                is_holding=True,
                object_names=["Cube"],
                unix_nanos=1234,
            ),
        )

    async def release(
        self, message: ManipulationReleaseRequest
    ) -> PbManipulationGrabState:
        self.release_requests.append(message)
        return PbManipulationGrabState(
            hand=message.hand,
            is_holding=False,
            object_names=[],
            unix_nanos=5678,
        )

    async def get_state(
        self, message: ManipulationGetStateRequest
    ) -> PbManipulationGrabState:
        self.get_state_requests.append(message)
        return PbManipulationGrabState(
            hand=message.hand,
            is_holding=True,
            object_names=["Cube", "Sphere", "Cone"],
            unix_nanos=9012,
        )


class _FailingManipulation(ManipulationBase):
    """Fake whose ``grab`` always fails with FAILED_PRECONDITION."""

    async def grab(self, message: ManipulationGrabRequest) -> PbManipulationGrabResult:
        raise GRPCError(Status.FAILED_PRECONDITION, "no world is focused")

    async def release(
        self, message: ManipulationReleaseRequest
    ) -> PbManipulationGrabState:
        raise GRPCError(Status.FAILED_PRECONDITION, "no world is focused")

    async def get_state(
        self, message: ManipulationGetStateRequest
    ) -> PbManipulationGrabState:
        raise GRPCError(Status.FAILED_PRECONDITION, "no world is focused")


class TestManipulationClient:
    async def test_grab_with_point_sends_world_point_and_radius_on_wire(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        socket_path = tmp_path / "rio-manipulation.sock"
        fake = _EchoManipulation()
        server = Server([fake])
        await server.start(path=str(socket_path))
        try:
            monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
            async with ManipulationClient() as client:
                assert client.socket_path == str(socket_path)
                result = await client.grab(point=_POINT, radius=_RADIUS)

            assert len(fake.grab_requests) == 1
            wire = fake.grab_requests[0]
            # The point carried distinct x/y/z values, not a collapsed/zeroed
            # WorldPoint — a dropped component would change one of these.
            assert wire.point is not None
            assert (wire.point.x, wire.point.y, wire.point.z) == _POINT
            assert wire.radius == _RADIUS

            assert isinstance(result, GrabResult)
            assert result.grabbed is True
            assert isinstance(result.state, GrabState)
            assert result.state.is_holding is True
            assert result.state.object_names == ("Cube",)
            assert result.state.unix_nanos == 1234
        finally:
            server.close()
            await server.wait_closed()

    async def test_grab_without_point_omits_world_point_on_wire(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        socket_path = tmp_path / "rio-manipulation.sock"
        fake = _EchoManipulation()
        server = Server([fake])
        await server.start(path=str(socket_path))
        try:
            monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
            async with ManipulationClient() as client:
                await client.grab(point=None, radius=_RADIUS)

            assert len(fake.grab_requests) == 1
            # `point=None` must leave the optional WorldPoint unset on the
            # wire so the server falls back to the hand's current position.
            assert fake.grab_requests[0].point is None
        finally:
            server.close()
            await server.wait_closed()

    async def test_grab_sends_radius_verbatim_including_zero_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        socket_path = tmp_path / "rio-manipulation.sock"
        fake = _EchoManipulation()
        server = Server([fake])
        await server.start(path=str(socket_path))
        try:
            monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
            async with ManipulationClient() as client:
                # Client default radius is 0.0. Expanding `<= 0` to the
                # server-side default (0.1m) is a C#-Core concern; here we
                # only pin that the client transmits exactly what it was
                # given (0.0), not a silently substituted value.
                await client.grab()

            assert len(fake.grab_requests) == 1
            assert fake.grab_requests[0].radius == 0.0
        finally:
            server.close()
            await server.wait_closed()

    async def test_grab_default_hand_is_primary_on_wire(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        socket_path = tmp_path / "rio-manipulation.sock"
        fake = _EchoManipulation()
        server = Server([fake])
        await server.start(path=str(socket_path))
        try:
            monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
            async with ManipulationClient() as client:
                await client.grab()

            assert fake.grab_requests[0].hand == ManipulationHand.PRIMARY
        finally:
            server.close()
            await server.wait_closed()

    async def test_grab_primary_hand_round_trips(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        socket_path = tmp_path / "rio-manipulation.sock"
        fake = _EchoManipulation()
        server = Server([fake])
        await server.start(path=str(socket_path))
        try:
            monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
            async with ManipulationClient() as client:
                result = await client.grab(hand="primary")

            assert fake.grab_requests[0].hand == ManipulationHand.PRIMARY
            # Fake echoes the request hand; PRIMARY must decode to "primary".
            assert result.state.hand == "primary"
        finally:
            server.close()
            await server.wait_closed()

    async def test_grab_left_hand_round_trips(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        socket_path = tmp_path / "rio-manipulation.sock"
        fake = _EchoManipulation()
        server = Server([fake])
        await server.start(path=str(socket_path))
        try:
            monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
            async with ManipulationClient() as client:
                result = await client.grab(hand="left")

            assert fake.grab_requests[0].hand == ManipulationHand.LEFT
            assert result.state.hand == "left"
        finally:
            server.close()
            await server.wait_closed()

    async def test_grab_right_hand_round_trips(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        socket_path = tmp_path / "rio-manipulation.sock"
        fake = _EchoManipulation()
        server = Server([fake])
        await server.start(path=str(socket_path))
        try:
            monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
            async with ManipulationClient() as client:
                result = await client.grab(hand="right")

            assert fake.grab_requests[0].hand == ManipulationHand.RIGHT
            assert result.state.hand == "right"
        finally:
            server.close()
            await server.wait_closed()

    async def test_unspecified_hand_decodes_as_primary(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """A server reply carrying ``UNSPECIFIED`` (the proto default for an
        unset enum) must surface to callers as ``"primary"`` — the documented
        fold of UNSPECIFIED/PRIMARY onto a single public literal."""
        socket_path = tmp_path / "rio-manipulation.sock"

        class _UnspecifiedHand(ManipulationBase):
            async def grab(
                self, message: ManipulationGrabRequest
            ) -> PbManipulationGrabResult:
                return PbManipulationGrabResult(
                    grabbed=False,
                    state=PbManipulationGrabState(
                        hand=ManipulationHand.UNSPECIFIED,
                        is_holding=False,
                        object_names=[],
                        unix_nanos=1,
                    ),
                )

            async def release(
                self, message: ManipulationReleaseRequest
            ) -> PbManipulationGrabState:
                raise NotImplementedError

            async def get_state(
                self, message: ManipulationGetStateRequest
            ) -> PbManipulationGrabState:
                raise NotImplementedError

        server = Server([_UnspecifiedHand()])
        await server.start(path=str(socket_path))
        try:
            monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
            async with ManipulationClient() as client:
                result = await client.grab()

            assert result.state.hand == "primary"
        finally:
            server.close()
            await server.wait_closed()

    async def test_release_returns_not_holding_state(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        socket_path = tmp_path / "rio-manipulation.sock"
        fake = _EchoManipulation()
        server = Server([fake])
        await server.start(path=str(socket_path))
        try:
            monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
            async with ManipulationClient() as client:
                state = await client.release(hand="left")

            assert len(fake.release_requests) == 1
            assert fake.release_requests[0].hand == ManipulationHand.LEFT
            # release must not issue a grab/get_state RPC.
            assert fake.grab_requests == []
            assert fake.get_state_requests == []

            assert isinstance(state, GrabState)
            assert state.hand == "left"
            assert state.is_holding is False
            assert state.object_names == ()
            assert state.unix_nanos == 5678
        finally:
            server.close()
            await server.wait_closed()

    async def test_get_state_decodes_repeated_object_names_in_order(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        socket_path = tmp_path / "rio-manipulation.sock"
        fake = _EchoManipulation()
        server = Server([fake])
        await server.start(path=str(socket_path))
        try:
            monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
            async with ManipulationClient() as client:
                state = await client.get_state(hand="right")

            assert len(fake.get_state_requests) == 1
            assert fake.get_state_requests[0].hand == ManipulationHand.RIGHT
            # get_state must be read-only: no mutating RPC issued.
            assert fake.grab_requests == []
            assert fake.release_requests == []

            assert state.hand == "right"
            assert state.is_holding is True
            # >1 distinct names, in declared order, as an immutable tuple —
            # proves repeated-string decode preserves count and ordering.
            assert state.object_names == ("Cube", "Sphere", "Cone")
            assert isinstance(state.object_names, tuple)
        finally:
            server.close()
            await server.wait_closed()

    async def test_grab_surfaces_server_error_as_grpc_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        socket_path = tmp_path / "rio-manipulation.sock"
        server = Server([_FailingManipulation()])
        await server.start(path=str(socket_path))
        try:
            monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
            async with ManipulationClient() as client:
                with pytest.raises(ClientGRPCError) as exc_info:
                    await client.grab(point=_POINT, radius=_RADIUS)

            assert exc_info.value.status is Status.FAILED_PRECONDITION
        finally:
            server.close()
            await server.wait_closed()

    async def test_grab_raises_when_not_connected(self):
        client = ManipulationClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.grab()

    async def test_release_raises_when_not_connected(self):
        client = ManipulationClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.release()

    async def test_get_state_raises_when_not_connected(self):
        client = ManipulationClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.get_state()
