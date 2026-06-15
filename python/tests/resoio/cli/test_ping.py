import json
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

# A fixed nanosecond timestamp near the real epoch scale (~1.7e18) that
# exceeds JS Number.MAX_SAFE_INTEGER (2^53). Used to pin that the json
# branch round-trips big ints exactly rather than truncating to a float.
_BIG_UNIX_NANOS = 1_700_000_000_123_456_789


class _EchoConnection(ConnectionBase):
    async def ping(self, message: PingRequest) -> PingResponse:
        return PingResponse(
            message=message.message,
            server_unix_nanos=time.time_ns(),
        )


class _FixedTimestampConnection(ConnectionBase):
    """Echoes the message but returns a fixed large ``server_unix_nanos`` so
    the json round-trip of a >2^53 integer can be asserted exactly."""

    async def ping(self, message: PingRequest) -> PingResponse:
        return PingResponse(
            message=message.message,
            server_unix_nanos=_BIG_UNIX_NANOS,
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


async def test_ping_json_emits_single_array_of_one_object(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """``--format json`` for a single ping emits ONE json document that is an
    array (not a bare object), holding one ``{message, server_unix_nanos,
    rtt_ms}`` entry built across the loop and emitted once."""
    socket_path = tmp_path / "rio.sock"
    server = Server([_FixedTimestampConnection()])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(["ping", "-m", "hello", "--format", "json"])
        rc = await _amain(args)
        assert rc == 0

        stdout = capsys.readouterr().out
        payload = json.loads(stdout)  # one and only one json document
        assert isinstance(payload, list)
        assert len(payload) == 1
        entry = payload[0]
        assert set(entry) == {"message", "server_unix_nanos", "rtt_ms"}
        assert entry["message"] == "hello"
        assert entry["server_unix_nanos"] == _BIG_UNIX_NANOS
        assert isinstance(entry["rtt_ms"], float)
    finally:
        server.close()
        await server.wait_closed()


async def test_ping_json_with_count_emits_one_array_of_n_objects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """``--format json -n 3`` emits ONE array of 3 entries, not 3 separate
    documents per iteration: ``json.loads`` of the whole stdout must succeed
    and yield a length-3 list."""
    socket_path = tmp_path / "rio.sock"
    server = Server([_FixedTimestampConnection()])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(["ping", "-n", "3", "--format", "json"])
        rc = await _amain(args)
        assert rc == 0

        stdout = capsys.readouterr().out
        payload = json.loads(stdout)  # whole stdout is a single document
        assert isinstance(payload, list)
        assert len(payload) == 3
        for entry in payload:
            assert set(entry) == {"message", "server_unix_nanos", "rtt_ms"}
            assert entry["message"] == "ping"
            assert entry["server_unix_nanos"] == _BIG_UNIX_NANOS
    finally:
        server.close()
        await server.wait_closed()


async def test_ping_json_preserves_non_ascii_message(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """``ensure_ascii=False``: a non-ascii payload string survives the json
    round-trip as the literal characters (not ``\\uXXXX`` escapes)."""
    socket_path = tmp_path / "rio.sock"
    server = Server([_FixedTimestampConnection()])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(
            ["ping", "-m", "こんにちは", "--format", "json"]
        )
        rc = await _amain(args)
        assert rc == 0

        stdout = capsys.readouterr().out
        assert "こんにちは" in stdout  # preserved verbatim, not escaped
        payload = json.loads(stdout)
        assert payload[0]["message"] == "こんにちは"
    finally:
        server.close()
        await server.wait_closed()
