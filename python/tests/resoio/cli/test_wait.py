"""Tests for the ``resoio wait`` CLI command.

The readiness polling itself is covered by ``test_connection.py`` against a
real grpclib server. Here we pin the CLI dispatch contract: it resolves the
target socket (explicit ``-s`` / env, or a pid → ``resonite-{pid}.sock``),
prints the resolved path on success, and maps failures to exit codes.
"""

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


async def test_wait_prints_resolved_path_on_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    socket_path = tmp_path / "rio.sock"
    server = Server([_EchoConnection()])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(["wait", "-T", "5"])
        rc = await _amain(args)
        assert rc == 0
        assert capsys.readouterr().out.strip() == str(socket_path)
    finally:
        server.close()
        await server.wait_closed()


async def test_wait_with_pid_resolves_socket_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    # Stub the readiness wait so we exercise pure CLI dispatch: a pid must be
    # turned into <dir>/resonite-{pid}.sock and forwarded to wait_for_ready.
    async def _fake_wait(
        socket_path: str | None = None, *, timeout: float | None, interval: float
    ) -> str:
        assert socket_path is not None
        return socket_path

    monkeypatch.setattr("resoio.connection.wait_for_ready", _fake_wait)
    monkeypatch.delenv("RESONITE_IO_SOCKET", raising=False)
    monkeypatch.setenv("RESONITE_IO_SOCKET_DIR", str(tmp_path))

    args = _build_parser().parse_args(["wait", "1234"])
    rc = await _amain(args)

    assert rc == 0
    assert capsys.readouterr().out.strip() == str(tmp_path / "resonite-1234.sock")


async def test_wait_pid_and_socket_conflict_is_usage_error(
    capsys: pytest.CaptureFixture[str],
):
    args = _build_parser().parse_args(["wait", "1234", "-s", "/tmp/x.sock"])
    rc = await _amain(args)

    assert rc == 2
    assert "not both" in capsys.readouterr().err


async def test_wait_timeout_reports_error_and_exits_1(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    # No server: the explicit socket never answers, so the wait times out.
    monkeypatch.setenv("RESONITE_IO_SOCKET", str(tmp_path / "never.sock"))
    args = _build_parser().parse_args(["wait", "-T", "0.1", "--interval", "0.02"])
    rc = await _amain(args)

    captured = capsys.readouterr()
    assert rc == 1
    assert "did not become ready" in captured.err
    assert captured.out == ""
