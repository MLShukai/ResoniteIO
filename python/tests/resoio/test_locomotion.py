import time
from collections.abc import AsyncIterator
from pathlib import Path

import grpclib
import pytest
from grpclib.const import Status
from grpclib.server import Server

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
    LocomotionCmd,
    ResetSummary,
)


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


async def _cmds(
    items: list[LocomotionCmd],
) -> AsyncIterator[LocomotionCmd]:
    for cmd in items:
        yield cmd


class TestLocomotionClient:
    async def test_round_trip_over_uds(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        socket_path = tmp_path / "rio-locomotion.sock"
        fake = _EchoLocomotion()
        server = Server([fake])
        await server.start(path=str(socket_path))
        try:
            monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
            # Move 3 軸 (forward / right / up) を別々の値で送り、特に視点独立の
            # 絶対ワールド上下軸 move_up が独立フィールドとして wire を通ることを
            # 確認する (取り違えで right や forward に紛れ込まないこと)。
            scenario = [
                LocomotionCmd(move_forward=1.0),
                LocomotionCmd(move_right=1.0, velocity=2.5),
                LocomotionCmd(move_up=1.0),
                LocomotionCmd(move_forward=0.25, move_right=-0.5, move_up=-0.75),
                LocomotionCmd(yaw_rate=0.5, pitch_rate=-0.25, crouch=1.0, jump=True),
            ]
            async with LocomotionClient() as client:
                assert client.socket_path == str(socket_path)
                summary = await client.drive(_cmds(scenario))

            assert isinstance(summary, DriveSummary)
            assert summary.received_count == len(scenario)
            assert summary.dropped_count == 0
            assert summary.unix_nanos > 0

            assert len(fake.received) == len(scenario)
            for sent, got in zip(scenario, fake.received, strict=True):
                assert got.move_forward == sent.move_forward
                assert got.move_right == sent.move_right
                assert got.move_up == sent.move_up
                assert got.yaw_rate == sent.yaw_rate
                assert got.pitch_rate == sent.pitch_rate
                assert got.jump == sent.jump
                assert got.velocity == sent.velocity
                assert got.crouch == sent.crouch
                # Client stamps unix_nanos at send time, so the server
                # must always see a positive value (proof of the wire
                # stamping, independent of the user-facing LocomotionCmd).
                assert got.unix_nanos > 0
        finally:
            server.close()
            await server.wait_closed()

    async def test_failed_precondition_surfaces_as_grpcerror(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        socket_path = tmp_path / "rio-locomotion.sock"
        # Server accepts one command then raises FAILED_PRECONDITION on
        # the second (mirrors a mid-stream engine-not-ready transition).
        fake = _EchoLocomotion(fail_on_index=1)
        server = Server([fake])
        await server.start(path=str(socket_path))
        try:
            monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
            scenario = [
                LocomotionCmd(move_forward=1.0),
                LocomotionCmd(move_forward=1.0),
                LocomotionCmd(move_forward=1.0),
            ]
            async with LocomotionClient() as client:
                with pytest.raises(grpclib.GRPCError) as excinfo:
                    await client.drive(_cmds(scenario))
            assert excinfo.value.status == Status.FAILED_PRECONDITION
        finally:
            server.close()
            await server.wait_closed()

    async def test_raises_when_not_connected(self):
        client = LocomotionClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.drive(_cmds([LocomotionCmd()]))

    async def test_reset_round_trip(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        socket_path = tmp_path / "rio-locomotion.sock"
        fake = _EchoLocomotion()
        server = Server([fake])
        await server.start(path=str(socket_path))
        try:
            monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
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
        finally:
            server.close()
            await server.wait_closed()

    async def test_reset_default_means_all(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        socket_path = tmp_path / "rio-locomotion.sock"
        fake = _EchoLocomotion()
        server = Server([fake])
        await server.start(path=str(socket_path))
        try:
            monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
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
        finally:
            server.close()
            await server.wait_closed()

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

    def test_value_equality(self):
        a = ResetSummary(move=True, look=False, crouch=False, jump=False, unix_nanos=1)
        b = ResetSummary(move=True, look=False, crouch=False, jump=False, unix_nanos=1)
        c = ResetSummary(move=True, look=False, crouch=False, jump=False, unix_nanos=2)
        assert a == b
        assert a != c
