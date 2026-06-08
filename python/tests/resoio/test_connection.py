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

import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

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
from resoio.connection import ConnectionClient

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
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        (tmp_path / "resonite-1.sock").touch()
        (tmp_path / "resonite-2.sock").touch()
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
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        (tmp_path / "resonite-1.sock").touch()
        (tmp_path / "resonite-2.sock").touch()
        monkeypatch.delenv("RESONITE_IO_SOCKET", raising=False)
        monkeypatch.setenv("RESONITE_IO_SOCKET_DIR", str(tmp_path))

        with pytest.raises(AmbiguousSocketError):
            resolve_socket_path()
