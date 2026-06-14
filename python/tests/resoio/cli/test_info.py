"""Tests for the ``resoio info`` CLI command over a real tmp_path UDS.

Per testing-strategy: a real ``grpclib.server.Server`` with a self-owned
``InfoBase`` fake; the command is driven through the real parser + ``_amain``
entry point. The command prints one ``key=value`` line per ``ServerInfo``
field (``mod_version`` / ``engine_version`` / ``platform`` / ``is_wine`` /
``resonite_pid`` / ``renderer_pid``, in that order); against a server without
the Info service (a mod predating this modality) it reports guidance on stderr
and exits 1.
"""

import json
from pathlib import Path

import pytest
from grpclib.server import Server

from resoio._generated.resonite_io.v1 import (
    GetServerInfoRequest,
    InfoBase,
    ServerInfo as PbServerInfo,
    ServerPlatform as PbServerPlatform,
)
from resoio.cli import _amain, _build_parser


class _FakeInfo(InfoBase):
    async def get_server_info(self, message: GetServerInfoRequest) -> PbServerInfo:
        return PbServerInfo(
            mod_version="9.9.9-mod",
            engine_version="2025.1.1.1",
            platform=PbServerPlatform.LINUX,
            is_wine=True,
            resonite_pid=4242,
            renderer_pid=4343,
        )


class _PreInfoMod(InfoBase):
    """A pre-Info mod: ``GetServerInfo`` answers ``UNIMPLEMENTED`` via the
    un-overridden generated base (omitting the service entirely would trip
    grpclib's client-side missing-content-type quirk instead, which the real
    C# Kestrel server does not share)."""


async def test_info_prints_six_key_value_lines(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    socket_path = tmp_path / "rio.sock"
    server = Server([_FakeInfo()])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(["info"])
        rc = await _amain(args)
        assert rc == 0
        lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
        assert len(lines) == 6
        assert lines[0] == "mod_version=9.9.9-mod"
        assert lines[1] == "engine_version=2025.1.1.1"
        # The platform / bool rendering case is not part of the contract;
        # the value itself (linux / true) is.
        assert lines[2].lower() == "platform=linux"
        assert lines[3].lower() == "is_wine=true"
        assert lines[4] == "resonite_pid=4242"
        assert lines[5] == "renderer_pid=4343"
    finally:
        server.close()
        await server.wait_closed()


async def test_info_against_pre_info_mod_prints_guidance_and_exits_1(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    socket_path = tmp_path / "rio.sock"
    server = Server([_PreInfoMod()])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(["info"])
        rc = await _amain(args)
        assert rc == 1
        captured = capsys.readouterr()
        # Guidance goes to stderr (substring check only — exact wording is
        # not contract); nothing useful lands on stdout.
        assert "mod" in captured.err.lower()
    finally:
        server.close()
        await server.wait_closed()


async def test_info_json_emits_single_object_with_documented_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """``--format json`` emits ONE json object with exactly the six
    documented fields. ``platform`` is the same lowercase string the human
    path prints (``info.platform.value``, ``"linux"``) — NOT the enum's int
    value or name. ``is_wine`` is a real json bool; pids are ints."""
    socket_path = tmp_path / "rio.sock"
    server = Server([_FakeInfo()])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(["info", "--format", "json"])
        rc = await _amain(args)
        assert rc == 0

        stdout = capsys.readouterr().out
        payload = json.loads(stdout)  # one and only one json document
        assert payload == {
            "mod_version": "9.9.9-mod",
            "engine_version": "2025.1.1.1",
            "platform": "linux",
            "is_wine": True,
            "resonite_pid": 4242,
            "renderer_pid": 4343,
        }
        # `is_wine` must be a json boolean, not an int (guards against
        # bool->int collapse in the serializer dispatch order).
        assert payload["is_wine"] is True
    finally:
        server.close()
        await server.wait_closed()


async def test_info_json_against_pre_info_mod_exits_1_with_no_stdout_document(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """In json mode the UNIMPLEMENTED guidance still goes to stderr and exit is
    1; stdout must NOT carry a stray json document."""
    socket_path = tmp_path / "rio.sock"
    server = Server([_PreInfoMod()])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(["info", "--format", "json"])
        rc = await _amain(args)
        assert rc == 1
        captured = capsys.readouterr()
        assert "mod" in captured.err.lower()
        assert captured.out.strip() == ""
    finally:
        server.close()
        await server.wait_closed()
