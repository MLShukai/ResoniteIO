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
)
from resoio.locomotion import DriveSummary, LocomotionClient, LocomotionCmd


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
            scenario = [
                LocomotionCmd(move_y=1.0),
                LocomotionCmd(move_x=1.0, sprint=True, sprint_multiplier=2.5),
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
                assert got.move_x == sent.move_x
                assert got.move_y == sent.move_y
                assert got.yaw_rate == sent.yaw_rate
                assert got.pitch_rate == sent.pitch_rate
                assert got.jump == sent.jump
                assert got.sprint == sent.sprint
                assert got.crouch == sent.crouch
                assert got.sprint_multiplier == sent.sprint_multiplier
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
                LocomotionCmd(move_y=1.0),
                LocomotionCmd(move_y=1.0),
                LocomotionCmd(move_y=1.0),
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
