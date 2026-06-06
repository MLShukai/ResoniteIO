import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from resoio._generated.resonite_io.v1 import (
    PingRequest,
    PingResponse,
    SessionBase,
)
from resoio.session import (
    AmbiguousSocketError,
    SessionClient,
    SocketNotFoundError,
)

if TYPE_CHECKING:
    from grpclib._typing import IServable

UdsServer = Callable[["IServable"], Awaitable[str]]


class _EchoSession(SessionBase):
    async def ping(self, message: PingRequest) -> PingResponse:
        return PingResponse(
            message=message.message,
            server_unix_nanos=time.time_ns(),
        )


class TestSessionClient:
    async def test_round_trip_over_uds(self, uds_server: UdsServer):
        socket_path = await uds_server(_EchoSession())
        async with SessionClient() as client:
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
            async with SessionClient():
                pass

    async def test_raises_when_socket_ambiguous(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        (tmp_path / "resonite-1.sock").touch()
        (tmp_path / "resonite-2.sock").touch()
        monkeypatch.delenv("RESONITE_IO_SOCKET", raising=False)
        monkeypatch.setenv("RESONITE_IO_SOCKET_DIR", str(tmp_path))
        with pytest.raises(AmbiguousSocketError):
            async with SessionClient():
                pass
