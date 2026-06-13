"""Integration-real tests for :mod:`resoio.lifecycle`.

Per testing-strategy: a real ``grpclib.server.Server`` on a real tmp_path UDS
hosting self-owned ``LifecycleBase`` / ``InfoBase`` fakes; no mocking of grpclib
/ asyncio / betterproto internals. ``LifecycleClient.shutdown`` fires the unary
``Lifecycle.Shutdown`` RPC; ``terminate`` reads the engine PID from ``Info`` and
then schedules the shutdown (a pure gRPC stop — no OS signals).
"""

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from grpclib.server import Server

from resoio._generated.resonite_io.v1 import (
    GetServerInfoRequest,
    InfoBase,
    LifecycleBase,
    ServerInfo as PbServerInfo,
    ServerPlatform as PbServerPlatform,
    ShutdownRequest,
    ShutdownResponse,
)
from resoio.lifecycle import LifecycleClient, terminate

if TYPE_CHECKING:
    from grpclib._typing import IServable

UdsServer = Callable[["IServable"], Awaitable[str]]


class _FakeLifecycle(LifecycleBase):
    """Lifecycle fake returning a configurable ``accepted`` and recording
    calls."""

    def __init__(self, accepted: bool = True) -> None:
        self._accepted = accepted
        self.requests: list[ShutdownRequest] = []

    async def shutdown(self, message: ShutdownRequest) -> ShutdownResponse:
        self.requests.append(message)
        return ShutdownResponse(accepted=self._accepted)


class _FakeInfo(InfoBase):
    """Info fake reporting a configurable engine host PID."""

    def __init__(self, resonite_pid: int, renderer_pid: int = 0) -> None:
        self._resonite_pid = resonite_pid
        self._renderer_pid = renderer_pid

    async def get_server_info(self, message: GetServerInfoRequest) -> PbServerInfo:
        return PbServerInfo(
            mod_version="t",
            engine_version="e",
            platform=PbServerPlatform.LINUX,
            is_wine=False,
            resonite_pid=self._resonite_pid,
            renderer_pid=self._renderer_pid,
        )


# --- LifecycleClient.shutdown round-trip -----------------------------------


async def test_shutdown_round_trips_accepted_true(uds_server: UdsServer):
    """A scheduled shutdown round-trips ``accepted=True`` and the server sees
    exactly one request."""
    fake = _FakeLifecycle(accepted=True)
    await uds_server(fake)

    async with LifecycleClient() as client:
        response = await client.shutdown()

    assert response.accepted is True
    assert len(fake.requests) == 1


async def test_shutdown_round_trips_accepted_false_when_already_shutting_down(
    uds_server: UdsServer,
):
    """When the engine has already begun shutting down the bridge reports a no-
    op; the client surfaces ``accepted=False`` unchanged."""
    await uds_server(_FakeLifecycle(accepted=False))

    async with LifecycleClient() as client:
        response = await client.shutdown()

    assert response.accepted is False


# --- terminate (Info PID + graceful shutdown) ------------------------------


async def test_terminate_returns_engine_pid_and_schedules_shutdown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """``terminate`` reads the engine PID from Info, sends Lifecycle.Shutdown
    exactly once, and returns that PID."""
    lifecycle = _FakeLifecycle(accepted=True)
    server = Server([_FakeInfo(resonite_pid=4242, renderer_pid=4343), lifecycle])
    socket_path = tmp_path / "rio.sock"
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))

        pid = await terminate()

        assert pid == 4242
        assert len(lifecycle.requests) == 1
    finally:
        server.close()
        await server.wait_closed()


async def test_terminate_returns_none_when_engine_unreachable(tmp_path: Path):
    """With no reachable engine (Info fails), ``terminate`` is a no-op
    returning ``None``."""
    missing_socket = tmp_path / "absent.sock"

    assert await terminate(socket_path=str(missing_socket)) is None
