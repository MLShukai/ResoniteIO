from pathlib import Path

import pytest
from grpclib.server import Server

from resoio._generated.resonite_io.v1 import (
    DisplayApplyResponse,
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

    async def apply(self, message: DisplayConfig) -> DisplayApplyResponse:
        self.last_apply = message
        self.current = DisplayState(
            width=message.width or self.current.width,
            height=message.height or self.current.height,
            max_fps=message.max_fps or self.current.max_fps,
        )
        return DisplayApplyResponse()

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
            ["display", "--width", "1920", "--height", "1080"]
        )
        rc = await _amain(args)
        assert rc == 0
        # Apply path returns Empty -> stdout must be silent (rc=0 only signal).
        assert capsys.readouterr().out == ""
        assert fake.last_apply is not None
        assert fake.last_apply.width == 1920
        assert fake.last_apply.height == 1080
        # Unset fields propagate as 0.0 (proto3 default = "leave unchanged").
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
        args = _build_parser().parse_args(["display", "--max-fps", "120"])
        rc = await _amain(args)
        assert rc == 0
        # Apply path returns Empty -> stdout must be silent (rc=0 only signal).
        assert capsys.readouterr().out == ""
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
        # No display-affecting flags -> Get path.
        args = _build_parser().parse_args(["display"])
        rc = await _amain(args)
        assert rc == 0
        out = capsys.readouterr().out.strip()
        assert out == "width=2560 height=1440 max_fps=144.0"
        # Get must not record an Apply on the server side.
        assert fake.last_apply is None
    finally:
        server.close()
        await server.wait_closed()


async def test_socket_only_invokes_get_not_apply(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """``-s SOCK`` alone counts as "no display flags" -> Get, not Apply."""
    socket_path = tmp_path / "rio-display.sock"
    fake = _FakeDisplay(DisplayState(width=1024, height=768, max_fps=75.0))
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        # Clear the env var so we know -s is the only thing routing the socket.
        monkeypatch.delenv("RESONITE_IO_SOCKET", raising=False)
        args = _build_parser().parse_args(["display", "-s", str(socket_path)])
        rc = await _amain(args)
        assert rc == 0
        out = capsys.readouterr().out.strip()
        assert out == "width=1024 height=768 max_fps=75.0"
        assert fake.last_apply is None
    finally:
        server.close()
        await server.wait_closed()


async def test_explicit_max_fps_zero_is_apply_not_get(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """``--max-fps 0`` is an explicit value (default=None sentinel), so the
    CLI dispatches to Apply and forwards ``0.0`` to the server. The "0 =
    unchanged" collapse is a separate, server-side semantic layer — the
    CLI does not second-guess it here.
    """
    socket_path = tmp_path / "rio-display.sock"
    fake = _FakeDisplay(DisplayState(width=640, height=480, max_fps=60.0))
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(["display", "--max-fps", "0"])
        rc = await _amain(args)
        assert rc == 0
        # Apply path -> silent stdout.
        assert capsys.readouterr().out == ""
        assert fake.last_apply is not None
        assert fake.last_apply.max_fps == 0.0
    finally:
        server.close()
        await server.wait_closed()


def test_socket_flag_accepted_with_and_without_apply_flags(tmp_path: Path):
    """``-s/--socket`` parses both bare and with apply flags."""
    parser = _build_parser()
    sock = str(tmp_path / "x.sock")
    a = parser.parse_args(["display", "--width", "1920", "-s", sock])
    assert a.socket == sock
    g = parser.parse_args(["display", "-s", sock])
    assert g.socket == sock
