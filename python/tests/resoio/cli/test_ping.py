import time
from pathlib import Path

import pytest
from grpclib.server import Server

from resoio._generated.resonite_io.v1 import (
    ConnectionBase,
    PingRequest,
    PingResponse,
)
from resoio.cli import _amain, _build_parser


class _EchoConnection(ConnectionBase):
    async def ping(self, message: PingRequest) -> PingResponse:
        return PingResponse(
            message=message.message,
            server_unix_nanos=time.time_ns(),
        )


async def test_ping_round_trip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    socket_path = tmp_path / "rio.sock"
    server = Server([_EchoConnection()])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(["ping", "-m", "hello"])
        rc = await _amain(args)
        assert rc == 0
        captured = capsys.readouterr()
        assert "message=hello" in captured.out
        assert "server_unix_nanos=" in captured.out
        assert "rtt_ms=" in captured.out
    finally:
        server.close()
        await server.wait_closed()


async def test_ping_with_count(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    socket_path = tmp_path / "rio.sock"
    server = Server([_EchoConnection()])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(["ping", "--count", "3"])
        rc = await _amain(args)
        assert rc == 0
        out_lines = [
            line for line in capsys.readouterr().out.splitlines() if line.strip()
        ]
        assert len(out_lines) == 3
        for line in out_lines:
            assert line.startswith("message=ping ")
    finally:
        server.close()
        await server.wait_closed()
