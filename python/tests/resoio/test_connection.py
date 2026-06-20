"""Connection client + socket-resolution tests over a real tmp_path UDS.

After the API refinement the socket-resolution surface (``resolve_socket_path``
plus ``SocketNotFoundError`` / ``AmbiguousSocketError``) moved out of the
deleted ``_socket.py`` into ``resoio._client``, and the two exceptions are now
re-exported from the ``resoio`` top level (NOT from ``resoio.connection``).
These tests import the exceptions from that stable public path.

Per testing-strategy: a real ``grpclib.server.Server`` on a real UDS with a
self-owned ``ConnectionBase`` fake; no mocking of grpclib / asyncio /
betterproto internals. The resolution tests use real files under ``tmp_path``
and real env vars (via ``monkeypatch``).
"""

import asyncio
import os
import socket as socket_mod
import subprocess
import sys
import time
from collections.abc import Awaitable, Callable, Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from grpclib.const import Status
from grpclib.exceptions import GRPCError
from grpclib.server import Server

from resoio import (
    AmbiguousSocketError,
    SocketNotFoundError,
)
from resoio._client import resolve_socket_path
from resoio._generated.resonite_io.v1 import (
    ConnectionBase,
    PingRequest,
    PingResponse,
)
from resoio.connection import ConnectionClient, wait_for_ready

if TYPE_CHECKING:
    from grpclib._typing import IServable

UdsServer = Callable[["IServable"], Awaitable[str]]


class _EchoConnection(ConnectionBase):
    async def ping(self, message: PingRequest) -> PingResponse:
        return PingResponse(
            message=message.message,
            server_unix_nanos=time.time_ns(),
        )


class TestConnectionClient:
    async def test_round_trip_over_uds(self, uds_server: UdsServer):
        socket_path = await uds_server(_EchoConnection())
        async with ConnectionClient() as client:
            assert client.socket_path == socket_path
            resp = await client.ping("hi")
        assert resp.message == "hi"
        assert resp.server_unix_nanos > 0

    async def test_raises_when_socket_not_found(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.delenv("RESONITE_IO_SOCKET", raising=False)
        monkeypatch.setenv("RESONITE_IO_SOCKET_DIR", str(tmp_path))
        with pytest.raises(SocketNotFoundError):
            async with ConnectionClient():
                pass

    async def test_raises_when_socket_ambiguous(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, live_pid: int
    ):
        # Two *live* PIDs so both survive the dead-socket filter and the
        # ambiguity is genuine (not a coincidence of which PIDs happen to run).
        (tmp_path / f"resonite-{os.getpid()}.sock").touch()
        (tmp_path / f"resonite-{live_pid}.sock").touch()
        monkeypatch.delenv("RESONITE_IO_SOCKET", raising=False)
        monkeypatch.setenv("RESONITE_IO_SOCKET_DIR", str(tmp_path))
        with pytest.raises(AmbiguousSocketError):
            async with ConnectionClient():
                pass


class TestResolveSocketPath:
    """Socket-resolution precedence is the contract every modality client
    shares.

    It now lives in ``resoio._client.resolve_socket_path``; these
    exercise the public resolution order against real env vars + real files
    under ``tmp_path`` (no I/O mocking).
    """

    def test_explicit_socket_env_takes_precedence_over_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        # Both env vars set: the explicit RESONITE_IO_SOCKET must win, even
        # though RESONITE_IO_SOCKET_DIR points at a directory with a single
        # matching socket.
        explicit = tmp_path / "explicit.sock"
        explicit.touch()
        dir_with_sock = tmp_path / "dir"
        dir_with_sock.mkdir()
        (dir_with_sock / "resonite-x.sock").touch()
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(explicit))
        monkeypatch.setenv("RESONITE_IO_SOCKET_DIR", str(dir_with_sock))

        assert resolve_socket_path() == str(explicit)

    def test_dir_env_used_when_explicit_absent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        sock = tmp_path / "resonite-only.sock"
        sock.touch()
        monkeypatch.delenv("RESONITE_IO_SOCKET", raising=False)
        monkeypatch.setenv("RESONITE_IO_SOCKET_DIR", str(tmp_path))

        assert resolve_socket_path() == str(sock)

    def test_empty_explicit_env_falls_through_to_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        # A stray empty RESONITE_IO_SOCKET= must not resolve to an empty path;
        # resolution falls through to the directory search.
        sock = tmp_path / "resonite-fallthrough.sock"
        sock.touch()
        monkeypatch.setenv("RESONITE_IO_SOCKET", "")
        monkeypatch.setenv("RESONITE_IO_SOCKET_DIR", str(tmp_path))

        assert resolve_socket_path() == str(sock)

    def test_raises_socket_not_found_for_empty_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.delenv("RESONITE_IO_SOCKET", raising=False)
        monkeypatch.setenv("RESONITE_IO_SOCKET_DIR", str(tmp_path))

        with pytest.raises(SocketNotFoundError):
            resolve_socket_path()

    def test_raises_ambiguous_when_multiple_sockets_match(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, live_pid: int
    ):
        # Two *live* PIDs so both survive the dead-socket filter.
        (tmp_path / f"resonite-{os.getpid()}.sock").touch()
        (tmp_path / f"resonite-{live_pid}.sock").touch()
        monkeypatch.delenv("RESONITE_IO_SOCKET", raising=False)
        monkeypatch.setenv("RESONITE_IO_SOCKET_DIR", str(tmp_path))

        with pytest.raises(AmbiguousSocketError):
            resolve_socket_path()


@pytest.fixture
def dead_pid() -> int:
    """A PID guaranteed dead: a child spawned and then reaped.

    Reaping (``wait``) matters — a zombie would still report alive to
    ``psutil.pid_exists``, so the child must be fully collected.
    """
    proc = subprocess.Popen([sys.executable, "-c", ""])
    proc.wait()
    return proc.pid


@pytest.fixture
def live_pid() -> Iterator[int]:
    """A PID of a real, alive process distinct from the test process."""
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        yield proc.pid
    finally:
        proc.terminate()
        proc.wait()


class _NotReadyThenEcho(ConnectionBase):
    """Replies FAILED_PRECONDITION for the first ``fail_times`` pings, then
    echoes.

    Models an engine that has bound the UDS but is still warming up.
    """

    def __init__(self, fail_times: int) -> None:
        self._remaining = fail_times
        self.calls = 0

    async def ping(self, message: PingRequest) -> PingResponse:
        self.calls += 1
        if self._remaining > 0:
            self._remaining -= 1
            raise GRPCError(Status.FAILED_PRECONDITION, "warming up")
        return PingResponse(
            message=message.message,
            server_unix_nanos=time.time_ns(),
        )


class _AlwaysInternal(ConnectionBase):
    async def ping(self, message: PingRequest) -> PingResponse:
        raise GRPCError(Status.INTERNAL, "boom")


class TestDeadSocketFilter:
    """Socket resolution skips sockets whose owning engine PID is gone."""

    def test_skips_dead_socket_and_returns_live(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        dead_pid: int,
        live_pid: int,
    ):
        (tmp_path / f"resonite-{dead_pid}.sock").touch()
        live = tmp_path / f"resonite-{live_pid}.sock"
        live.touch()
        monkeypatch.delenv("RESONITE_IO_SOCKET", raising=False)
        monkeypatch.setenv("RESONITE_IO_SOCKET_DIR", str(tmp_path))

        # The dead one is skipped, so resolution is unambiguous and picks live.
        assert resolve_socket_path() == str(live)

    def test_only_dead_socket_raises_not_found(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dead_pid: int
    ):
        (tmp_path / f"resonite-{dead_pid}.sock").touch()
        monkeypatch.delenv("RESONITE_IO_SOCKET", raising=False)
        monkeypatch.setenv("RESONITE_IO_SOCKET_DIR", str(tmp_path))

        with pytest.raises(SocketNotFoundError):
            resolve_socket_path()

    def test_keeps_socket_with_non_integer_name(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        # A name that does not encode an integer PID cannot be assessed for
        # liveness, so it is kept rather than silently hidden.
        sock = tmp_path / "resonite-not-a-pid.sock"
        sock.touch()
        monkeypatch.delenv("RESONITE_IO_SOCKET", raising=False)
        monkeypatch.setenv("RESONITE_IO_SOCKET_DIR", str(tmp_path))

        assert resolve_socket_path() == str(sock)


class TestWaitForReady:
    """``wait_for_ready`` polls Connection.Ping over a real UDS until it
    answers."""

    async def test_returns_path_when_already_up(self, uds_server: UdsServer):
        socket_path = await uds_server(_EchoConnection())
        # socket_path=None resolves via RESONITE_IO_SOCKET (set by the fixture).
        resolved = await wait_for_ready(timeout=5.0, interval=0.05)
        assert resolved == socket_path

    async def test_waits_for_late_server(self, tmp_path: Path):
        socket_path = tmp_path / "rio.sock"

        async def _start_later() -> Server:
            # A real (short) await — no fake clock; the wait must poll past it.
            await asyncio.sleep(0.15)
            server = Server([_EchoConnection()])
            await server.start(path=str(socket_path))
            return server

        task = asyncio.create_task(_start_later())
        resolved = await wait_for_ready(str(socket_path), timeout=5.0, interval=0.02)
        assert resolved == str(socket_path)

        server = await task
        server.close()
        await server.wait_closed()

    async def test_times_out_when_never_up(self, tmp_path: Path):
        missing = tmp_path / "never.sock"
        start = time.monotonic()
        with pytest.raises(TimeoutError):
            await wait_for_ready(str(missing), timeout=0.1, interval=0.02)
        # The interval is clamped to the deadline, so the wait does not
        # overshoot the timeout by a whole interval.
        assert time.monotonic() - start < 1.0

    async def test_ambiguous_propagates_without_retry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, live_pid: int
    ):
        (tmp_path / f"resonite-{os.getpid()}.sock").touch()
        (tmp_path / f"resonite-{live_pid}.sock").touch()
        monkeypatch.delenv("RESONITE_IO_SOCKET", raising=False)
        monkeypatch.setenv("RESONITE_IO_SOCKET_DIR", str(tmp_path))

        # Even with a generous timeout it raises at once: waiting cannot
        # disambiguate two live sockets.
        with pytest.raises(AmbiguousSocketError):
            await wait_for_ready(timeout=5.0, interval=0.02)

    async def test_dead_socket_is_not_treated_ready(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dead_pid: int
    ):
        # Only a stale socket present: the resolver filters it, so the wait
        # keeps polling and ultimately times out (file existence != ready).
        (tmp_path / f"resonite-{dead_pid}.sock").touch()
        monkeypatch.delenv("RESONITE_IO_SOCKET", raising=False)
        monkeypatch.setenv("RESONITE_IO_SOCKET_DIR", str(tmp_path))

        with pytest.raises(TimeoutError):
            await wait_for_ready(timeout=0.1, interval=0.02)

    async def test_stale_socket_file_times_out(self, tmp_path: Path):
        # An explicit path to a bound-but-unlistened socket file: connecting
        # is refused, so file existence alone never counts as ready.
        stale = tmp_path / "rio.sock"
        s = socket_mod.socket(socket_mod.AF_UNIX, socket_mod.SOCK_STREAM)
        s.bind(str(stale))
        s.close()  # leaves the path on disk with no listener
        assert stale.exists()

        with pytest.raises(TimeoutError):
            await wait_for_ready(str(stale), timeout=0.1, interval=0.02)

    async def test_retries_until_engine_ready(self, tmp_path: Path):
        socket_path = tmp_path / "rio.sock"
        fake = _NotReadyThenEcho(fail_times=2)
        server = Server([fake])
        await server.start(path=str(socket_path))
        try:
            resolved = await wait_for_ready(
                str(socket_path), timeout=5.0, interval=0.02
            )
            assert resolved == str(socket_path)
            # 2 FAILED_PRECONDITION attempts + 1 success.
            assert fake.calls == 3
        finally:
            server.close()
            await server.wait_closed()

    async def test_other_grpc_error_propagates(self, tmp_path: Path):
        socket_path = tmp_path / "rio.sock"
        server = Server([_AlwaysInternal()])
        await server.start(path=str(socket_path))
        try:
            with pytest.raises(GRPCError):
                await wait_for_ready(str(socket_path), timeout=5.0, interval=0.02)
        finally:
            server.close()
            await server.wait_closed()
