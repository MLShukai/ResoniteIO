from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

import pytest

from resoio import get_server_info
from resoio._client import resolve_socket_path, socket_path_for_pid
from resoio.connection import ConnectionClient, wait_for_ready
from tests.helpers import mark_e2e


class TestConnectionPing:
    @mark_e2e
    def test_smoke(self, resonite_session: Path) -> None:
        async def call() -> None:
            async with ConnectionClient() as client:
                response = await client.ping("e2e-smoke")
            assert response.message == "e2e-smoke"
            assert response.server_unix_nanos > 0

        asyncio.run(call())


class TestWaitForReady:
    @mark_e2e
    def test_returns_live_path_and_ping_works(self, resonite_session: Path) -> None:
        socket_path = resonite_session

        async def call() -> None:
            # The engine is already up (the fixture waited), so readiness is
            # immediate; this pins that wait_for_ready resolves to the live
            # socket and that the path it returns actually answers Ping.
            resolved = await wait_for_ready(timeout=120.0, interval=0.5)
            assert resolved == str(socket_path)
            async with ConnectionClient() as client:
                response = await client.ping("e2e-wait")
            assert response.message == "e2e-wait"

        asyncio.run(call())

    @mark_e2e
    def test_socket_path_for_pid_targets_live_engine(
        self, resonite_session: Path
    ) -> None:
        socket_path = resonite_session

        async def call() -> None:
            info = await get_server_info()
            # The mod names the socket by the engine host PID
            # (Environment.ProcessId), so targeting that PID resolves to the
            # exact live socket — the contract `resoio wait <pid>` relies on.
            target = socket_path_for_pid(info.resonite_pid)
            assert target == str(socket_path)
            resolved = await wait_for_ready(target, timeout=60.0, interval=0.5)
            assert resolved == str(socket_path)

        asyncio.run(call())


class TestDeadSocketFilterLive:
    @mark_e2e
    def test_stale_socket_beside_live_engine_is_ignored(
        self, resonite_session: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        live = resonite_session
        # A reaped child PID is guaranteed dead, so a socket named after it is
        # stale. Without the liveness filter it would collide with the live
        # socket and raise AmbiguousSocketError; the filter must skip it.
        proc = subprocess.Popen([sys.executable, "-c", ""])
        proc.wait()
        stale = live.parent / f"resonite-{proc.pid}.sock"
        stale.touch()
        try:
            monkeypatch.delenv("RESONITE_IO_SOCKET", raising=False)
            monkeypatch.setenv("RESONITE_IO_SOCKET_DIR", str(live.parent))
            assert resolve_socket_path() == str(live)
        finally:
            stale.unlink(missing_ok=True)
