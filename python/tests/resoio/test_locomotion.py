import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import TYPE_CHECKING

import grpclib
import pytest
from grpclib.const import Status

from resoio._generated.resonite_io.v1 import (
    LocomotionBase,
    LocomotionCommand,
    LocomotionDriveSummary,
    LocomotionResetRequest,
    LocomotionResetSummary,
)
from resoio.locomotion import (
    DriveSummary,
    LocomotionClient,
    ResetSummary,
)

if TYPE_CHECKING:
    from grpclib._typing import IServable

UdsServer = Callable[["IServable"], Awaitable[str]]


class _EchoLocomotion(LocomotionBase):
    """In-process fake that records every received command.

    With ``fail_on_index`` set, the fake raises ``GRPCError`` with the
    given status once it sees the N-th command (0-indexed) so the test
    can exercise the failure path mid-stream.
    """

    def __init__(
        self,
        *,
        fail_on_index: int | None = None,
        fail_status: Status = Status.FAILED_PRECONDITION,
    ) -> None:
        self.received: list[LocomotionCommand] = []
        self.reset_requests: list[LocomotionResetRequest] = []
        self._fail_on_index = fail_on_index
        self._fail_status = fail_status

    async def drive(
        self, messages: AsyncIterator[LocomotionCommand]
    ) -> LocomotionDriveSummary:
        async for msg in messages:
            if (
                self._fail_on_index is not None
                and len(self.received) == self._fail_on_index
            ):
                raise grpclib.GRPCError(self._fail_status, "engine not ready")
            self.received.append(msg)
        return LocomotionDriveSummary(
            received_count=len(self.received),
            dropped_count=0,
            unix_nanos=time.time_ns(),
        )

    async def reset(self, message: LocomotionResetRequest) -> LocomotionResetSummary:
        self.reset_requests.append(message)
        # Echo the wire flags verbatim. The "all-false → full reset"
        # service-layer expansion is covered by the C# Core tests; this
        # fake stays minimal so Python tests assert only proto-wire shape.
        return LocomotionResetSummary(
            move=message.move,
            look=message.look,
            crouch=message.crouch,
            jump=message.jump,
            unix_nanos=time.time_ns(),
        )


class TestLocomotionSend:
    async def test_partial_sends_only_set_fields_reach_the_wire(
        self, uds_server: UdsServer
    ):
        # Partial-update contract: each send() enqueues exactly one
        # LocomotionCommand carrying only the fields the caller named.
        # Unset optional fields must read back as None on the server so
        # the stateful bridge can hold the previous value.
        fake = _EchoLocomotion()
        socket_path = await uds_server(fake)

        async with LocomotionClient() as client:
            assert client.socket_path == socket_path
            await client.send(move_forward=1.0)
            await client.send(yaw_rate=0.5)

        assert len(fake.received) == 2

        first = fake.received[0]
        assert first.move_forward == 1.0
        # Every field the caller did not name is omitted on the wire and
        # reads back as None (proto3 optional presence).
        assert first.move_right is None
        assert first.move_up is None
        assert first.yaw_rate is None
        assert first.pitch_rate is None
        assert first.jump is None
        assert first.velocity is None
        assert first.crouch is None

        second = fake.received[1]
        assert second.yaw_rate == 0.5
        # move_forward set on the *previous* send must not leak into this
        # command — the bridge, not the client, holds prior state.
        assert second.move_forward is None
        assert second.move_right is None
        assert second.move_up is None
        assert second.pitch_rate is None
        assert second.jump is None
        assert second.velocity is None
        assert second.crouch is None

    async def test_drive_summary_reflects_received_count_after_exit(
        self, uds_server: UdsServer
    ):
        # drive_summary is None until the persistent Drive stream is
        # closed on __aexit__; afterwards it carries the server summary.
        fake = _EchoLocomotion()
        await uds_server(fake)

        client = LocomotionClient()
        async with client:
            assert client.drive_summary is None
            await client.send(move_forward=1.0)
            await client.send(yaw_rate=0.5)

        summary = client.drive_summary
        assert isinstance(summary, DriveSummary)
        assert summary.received_count == 2
        assert summary.dropped_count == 0
        assert summary.unix_nanos > 0

    async def test_unix_nanos_is_auto_stamped(self, uds_server: UdsServer):
        # The client stamps unix_nanos at send time; callers never set it,
        # so every command must reach the server with a positive value.
        fake = _EchoLocomotion()
        await uds_server(fake)

        async with LocomotionClient() as client:
            await client.send(move_forward=1.0)

        assert len(fake.received) == 1
        assert fake.received[0].unix_nanos > 0

    async def test_each_move_axis_is_independent(self, uds_server: UdsServer):
        # The three move axes (forward / right / up) map to distinct wire
        # fields; sending one must not bleed into the others. move_up is
        # the view-independent absolute world-up axis.
        fake = _EchoLocomotion()
        await uds_server(fake)

        async with LocomotionClient() as client:
            await client.send(move_forward=1.0)
            await client.send(move_right=-0.5)
            await client.send(move_up=0.25)

        forward, right, up = fake.received
        assert forward.move_forward == 1.0
        assert forward.move_right is None
        assert forward.move_up is None
        assert right.move_right == -0.5
        assert right.move_forward is None
        assert right.move_up is None
        assert up.move_up == 0.25
        assert up.move_forward is None
        assert up.move_right is None

    async def test_no_send_means_no_commands_and_zero_summary(
        self, uds_server: UdsServer
    ):
        # A context with no send() still opens/closes cleanly. The Drive
        # stream is opened lazily, so an unused client produces no
        # commands; drive_summary may be None (stream never opened) — the
        # contract is only that no commands reached the server.
        fake = _EchoLocomotion()
        await uds_server(fake)

        async with LocomotionClient():
            pass

        assert fake.received == []

    async def test_failed_precondition_surfaces_as_grpcerror(
        self, uds_server: UdsServer
    ):
        # Server accepts one command then raises FAILED_PRECONDITION on
        # the second (mirrors a mid-stream engine-not-ready transition).
        # The error must surface to the caller (on send or on exit).
        fake = _EchoLocomotion(fail_on_index=1)
        await uds_server(fake)

        with pytest.raises(grpclib.GRPCError) as excinfo:
            async with LocomotionClient() as client:
                await client.send(move_forward=1.0)
                await client.send(move_forward=1.0)
                await client.send(move_forward=1.0)
        assert excinfo.value.status == Status.FAILED_PRECONDITION

    async def test_send_raises_when_not_connected(self):
        client = LocomotionClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.send(move_forward=1.0)


class TestLocomotionReset:
    async def test_reset_round_trip(self, uds_server: UdsServer):
        fake = _EchoLocomotion()
        await uds_server(fake)
        async with LocomotionClient() as client:
            summary = await client.reset(move=True, look=True)

        assert isinstance(summary, ResetSummary)
        assert summary.move is True
        assert summary.look is True
        # Partial reset — server fake mirrors the request flags
        # verbatim (not an all-false expansion).
        assert summary.crouch is False
        assert summary.jump is False
        assert summary.unix_nanos > 0

        assert len(fake.reset_requests) == 1
        wire = fake.reset_requests[0]
        assert wire.move is True
        assert wire.look is True
        assert wire.crouch is False
        assert wire.jump is False
        # Client stamps unix_nanos at send time.
        assert wire.unix_nanos > 0

    async def test_reset_default_means_all(self, uds_server: UdsServer):
        fake = _EchoLocomotion()
        await uds_server(fake)
        async with LocomotionClient() as client:
            # No args: every bool must hit the wire as false. The
            # service-layer "all-false → full reset" expansion is
            # covered by the C# Core tests, so Python only asserts
            # the proto-wire shape here.
            await client.reset()

        assert len(fake.reset_requests) == 1
        wire = fake.reset_requests[0]
        assert wire.move is False
        assert wire.look is False
        assert wire.crouch is False
        assert wire.jump is False

    async def test_reset_raises_when_not_connected(self):
        client = LocomotionClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.reset(move=True)


class TestResetSummary:
    def test_frozen_and_slotted(self):
        summary = ResetSummary(
            move=True, look=False, crouch=False, jump=False, unix_nanos=42
        )
        assert summary.__slots__ == ("move", "look", "crouch", "jump", "unix_nanos")
        with pytest.raises(AttributeError):
            summary.move = False  # type: ignore[misc]
