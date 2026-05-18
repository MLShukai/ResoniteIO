import asyncio
from pathlib import Path

import pytest
from grpclib.server import Server

from resoio._generated.resonite_io.v1 import (
    DisplayBase,
    DisplayConfig,
    DisplayGetRequest,
    DisplayState,
)
from resoio.cli import _amain, _build_parser


class _FakeDisplay(DisplayBase):
    """In-process fake mirroring server-side "0 = unchanged" semantics."""

    def __init__(self, initial: DisplayState) -> None:
        self.current = initial
        self.last_apply: DisplayConfig | None = None

    async def apply(self, message: DisplayConfig) -> DisplayState:
        self.last_apply = message
        new = DisplayState(
            width=message.width or self.current.width,
            height=message.height or self.current.height,
            max_fps=message.max_fps or self.current.max_fps,
        )
        self.current = new
        return new

    async def get(self, message: DisplayGetRequest) -> DisplayState:
        return self.current


async def test_apply_with_width_and_height(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    socket_path = tmp_path / "rio-display.sock"
    fake = _FakeDisplay(DisplayState(width=800, height=600, max_fps=30.0))
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(
            ["display", "apply", "--width", "1920", "--height", "1080"]
        )
        rc = await _amain(args)
        assert rc == 0
        out = capsys.readouterr().out.strip()
        # Server fills in unchanged max_fps from current state (30.0).
        assert out == "width=1920 height=1080 max_fps=30.0"
        assert fake.last_apply is not None
        assert fake.last_apply.width == 1920
        assert fake.last_apply.height == 1080
        # Unset fields propagate as 0 / 0.0 (proto3 default).
        assert fake.last_apply.max_fps == 0.0
    finally:
        server.close()
        await server.wait_closed()


async def test_apply_with_only_max_fps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    socket_path = tmp_path / "rio-display.sock"
    fake = _FakeDisplay(DisplayState(width=1280, height=720, max_fps=60.0))
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(["display", "apply", "--max-fps", "120"])
        rc = await _amain(args)
        assert rc == 0
        out = capsys.readouterr().out.strip()
        # width/height untouched (server keeps current), max_fps updated.
        assert out == "width=1280 height=720 max_fps=120.0"
        assert fake.last_apply is not None
        assert fake.last_apply.width == 0
        assert fake.last_apply.height == 0
        assert fake.last_apply.max_fps == 120.0
    finally:
        server.close()
        await server.wait_closed()


async def test_get_prints_current_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    socket_path = tmp_path / "rio-display.sock"
    fake = _FakeDisplay(DisplayState(width=2560, height=1440, max_fps=144.0))
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(["display", "get"])
        rc = await _amain(args)
        assert rc == 0
        out = capsys.readouterr().out.strip()
        assert out == "width=2560 height=1440 max_fps=144.0"
        # `get` must not record an Apply on the server side.
        assert fake.last_apply is None
    finally:
        server.close()
        await server.wait_closed()


def test_apply_without_any_field_is_rejected():
    parser = _build_parser()
    with pytest.raises(SystemExit) as excinfo:
        args = parser.parse_args(["display", "apply"])
        # _run_apply uses parser.error -> SystemExit before any I/O.
        asyncio.run(_amain(args))
    assert excinfo.value.code == 2


def test_display_without_subcommand_is_rejected():
    parser = _build_parser()
    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["display"])
    assert excinfo.value.code == 2


def test_socket_flag_accepted_on_both_subsubs(tmp_path: Path):
    """`-s/--socket` must work after both `display apply` and `display get`."""
    parser = _build_parser()
    sock = str(tmp_path / "x.sock")
    a = parser.parse_args(["display", "apply", "--width", "1920", "-s", sock])
    assert a.socket == sock
    g = parser.parse_args(["display", "get", "-s", sock])
    assert g.socket == sock
