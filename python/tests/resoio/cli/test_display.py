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


# ===========================================================================
# Parser-only tests: subcommand structure + flag -> namespace mapping.
# ===========================================================================


def test_display_without_subcommand_is_rejected():
    """``display`` is now a command group (get/set), not a leaf — bare
    ``display`` must error out at parse time (argparse exit code 2)."""
    parser = _build_parser()
    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["display"])
    assert excinfo.value.code == 2


def test_set_short_flags_map_to_width_height_max_fps():
    parser = _build_parser()
    args = parser.parse_args(["display", "set", "-W", "1280", "-H", "720", "-F", "30"])
    assert args.width == 1280
    assert args.height == 720
    assert args.max_fps == 30.0


def test_set_long_flags_map_to_width_height_max_fps():
    parser = _build_parser()
    args = parser.parse_args(
        ["display", "set", "--width", "1280", "--height", "720", "--max-fps", "30"]
    )
    assert args.width == 1280
    assert args.height == 720
    assert args.max_fps == 30.0


def test_socket_flag_parses_on_both_get_and_set_leaves(tmp_path: Path):
    """``-s/--socket`` must be accepted by both leaf subcommands."""
    parser = _build_parser()
    sock = str(tmp_path / "x.sock")
    g = parser.parse_args(["display", "get", "-s", sock])
    assert g.socket == sock
    a = parser.parse_args(["display", "set", "-W", "1920", "--socket", sock])
    assert a.socket == sock


# ===========================================================================
# Behavior tests: real UDS grpclib server + fake Display handler.
# ===========================================================================


async def test_get_prints_current_snapshot_without_applying(
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
        assert fake.last_apply is None
    finally:
        server.close()
        await server.wait_closed()


async def test_get_via_socket_flag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    socket_path = tmp_path / "rio-display.sock"
    fake = _FakeDisplay(DisplayState(width=1024, height=768, max_fps=75.0))
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        # -s must be the sole socket route: env var would mask test intent.
        monkeypatch.delenv("RESONITE_IO_SOCKET", raising=False)
        args = _build_parser().parse_args(["display", "get", "-s", str(socket_path)])
        rc = await _amain(args)
        assert rc == 0
        out = capsys.readouterr().out.strip()
        assert out == "width=1024 height=768 max_fps=75.0"
        assert fake.last_apply is None
    finally:
        server.close()
        await server.wait_closed()


async def test_set_applies_all_fields_and_prints_post_apply_snapshot(
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
            ["display", "set", "-W", "1920", "-H", "1080", "-F", "60"]
        )
        rc = await _amain(args)
        assert rc == 0
        assert fake.last_apply is not None
        assert fake.last_apply.width == 1920
        assert fake.last_apply.height == 1080
        assert fake.last_apply.max_fps == 60.0
        # set must re-fetch and print the post-apply snapshot (same format
        # as get), not echo the requested values.
        out = capsys.readouterr().out.strip()
        assert out == "width=1920 height=1080 max_fps=60.0"
    finally:
        server.close()
        await server.wait_closed()


async def test_set_partial_forwards_zero_for_unspecified_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """Only ``-F`` given: width/height go out as 0 (proto3 "leave unchanged")
    and the printed snapshot reflects the server-side merged state, proving the
    output comes from a post-apply get()."""
    socket_path = tmp_path / "rio-display.sock"
    fake = _FakeDisplay(DisplayState(width=1280, height=720, max_fps=60.0))
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(["display", "set", "--max-fps", "120"])
        rc = await _amain(args)
        assert rc == 0
        assert fake.last_apply is not None
        assert fake.last_apply.width == 0
        assert fake.last_apply.height == 0
        assert fake.last_apply.max_fps == 120.0
        # width/height never crossed the wire — they appear in the output
        # only because get() observed the server's retained state.
        out = capsys.readouterr().out.strip()
        assert out == "width=1280 height=720 max_fps=120.0"
    finally:
        server.close()
        await server.wait_closed()


async def test_set_explicit_max_fps_zero_counts_as_a_flag_and_forwards_zero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """``-F 0`` is an explicitly provided flag: it must NOT trip the "set
    without flags" error, and 0.0 is forwarded as-is.

    The "0 = unchanged" collapse is a server-side semantic layer — the
    CLI does not second-guess it.
    """
    socket_path = tmp_path / "rio-display.sock"
    fake = _FakeDisplay(DisplayState(width=640, height=480, max_fps=60.0))
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(["display", "set", "--max-fps", "0"])
        rc = await _amain(args)
        assert rc == 0
        assert fake.last_apply is not None
        assert fake.last_apply.max_fps == 0.0
        # Server kept its state (0 = unchanged), so the snapshot is intact.
        out = capsys.readouterr().out.strip()
        assert out == "width=640 height=480 max_fps=60.0"
    finally:
        server.close()
        await server.wait_closed()


# ===========================================================================
# "set without flags" rejection. The spec pins SystemExit code 2; whether
# the implementation rejects at parse time or at dispatch is not part of
# the contract, so parse + dispatch run inside one raises-block.
# ===========================================================================


async def test_set_without_flags_exits_with_code_2(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("RESONITE_IO_SOCKET", raising=False)
    parser = _build_parser()
    with pytest.raises(SystemExit) as excinfo:
        args = parser.parse_args(["display", "set"])
        await _amain(args)
    assert excinfo.value.code == 2


async def test_set_with_only_socket_flag_exits_with_code_2(tmp_path: Path):
    """``-s`` selects the transport, it is not a display field — set still has
    zero fields to apply and must be rejected with code 2."""
    parser = _build_parser()
    sock = str(tmp_path / "x.sock")
    with pytest.raises(SystemExit) as excinfo:
        args = parser.parse_args(["display", "set", "-s", sock])
        await _amain(args)
    assert excinfo.value.code == 2
