import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from resoio._generated.resonite_io.v1 import (
    ConnectionBase,
    PingRequest,
    PingResponse,
)
from resoio.connection import (
    AmbiguousSocketError,
    ConnectionClient,
    SocketNotFoundError,
)

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
