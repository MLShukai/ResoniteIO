"""Tests for the ``resoio info`` CLI command over a real tmp_path UDS.

Per testing-strategy: a real ``grpclib.server.Server`` with a self-owned
``InfoBase`` fake; the command is driven through the real parser + ``_amain``
entry point. The command prints one ``key=value`` line per ``ServerInfo``
field (``mod_version`` / ``engine_version`` / ``platform`` / ``is_wine``,
in that order); against a server without the Info service (a mod predating
this modality) it reports guidance on stderr and exits 1.
"""

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
        )


class _PreInfoMod(InfoBase):
    """A pre-Info mod: ``GetServerInfo`` answers ``UNIMPLEMENTED`` via the
    un-overridden generated base (omitting the service entirely would trip
    grpclib's client-side missing-content-type quirk instead, which the real
    C# Kestrel server does not share)."""


async def test_info_prints_four_key_value_lines(
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
        assert len(lines) == 4
        assert lines[0] == "mod_version=9.9.9-mod"
        assert lines[1] == "engine_version=2025.1.1.1"
        # The platform / bool rendering case is not part of the contract;
        # the value itself (linux / true) is.
        assert lines[2].lower() == "platform=linux"
        assert lines[3].lower() == "is_wine=true"
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
