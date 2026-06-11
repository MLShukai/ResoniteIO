"""CLI tests for ``resoio dash``.

The CLI register/_run path is driven against a real ``grpclib.server.Server``
hosting an inline fake :class:`DashBase` over a real UDS (no mocking of
grpclib/betterproto2). Each test asserts that the chosen action invokes the
correct RPC with the correct arguments and that the result is printed in the
documented format.

Per the subparser contract, ``dash invoke`` takes a required ``ref_id``
positional: omitting it, omitting the subcommand, or passing an unknown
subcommand is an argparse usage error (SystemExit with code 2 at
``parse_args`` time). ``set-screen`` requires either the positional key or
``--ref-id``; omitting both is pinned by exit code only (``_run_cli``
normalizes parse-time SystemExit and runtime return codes).
"""

from pathlib import Path

import pytest
from grpclib.server import Server

from resoio._generated.resonite_io.v1 import (
    DashActionResult as PbDashActionResult,
    DashBase,
    DashCloseRequest,
    DashElement as PbDashElement,
    DashGetStateRequest,
    DashGetTreeRequest,
    DashHighlightRequest,
    DashInvokeRequest,
    DashListScreensRequest,
    DashOpenRequest,
    DashRect as PbDashRect,
    DashScreen as PbDashScreen,
    DashScreenList as PbDashScreenList,
    DashScrollRequest,
    DashSetScreenRequest,
    DashState as PbDashState,
    DashTree as PbDashTree,
)
from resoio.cli import _amain, _build_parser


async def _run_cli(argv: list[str]) -> int:
    """Run the CLI and return its exit code.

    Normalizes the two contractual error loci: an argparse usage error
    (SystemExit raised by ``parse_args``) and a runtime return code from
    ``_amain``. The contract pins the exit code, not the locus.
    """
    try:
        args = _build_parser().parse_args(argv)
    except SystemExit as exc:
        assert isinstance(exc.code, int)
        return exc.code
    return await _amain(args)


def _parse_error_code(argv: list[str]) -> int:
    """Return the SystemExit code raised by ``parse_args`` for ``argv``."""
    with pytest.raises(SystemExit) as excinfo:
        _build_parser().parse_args(argv)
    assert isinstance(excinfo.value.code, int)
    return excinfo.value.code


_ELEMENT = PbDashElement(
    ref_id="s-1",
    type="Button",
    slot_name="AudioButton",
    locale_key="Settings.Audio",
    label="Audio",
    enabled=True,
    interactable=True,
    rect=PbDashRect(x=10.0, y=20.0, width=100.0, height=30.0, is_screen_space=False),
    parent_ref_id="",
    depth=0,
)

_SCREENS = [
    PbDashScreen(
        ref_id="sc-1",
        key="Dash.Screens.Worlds",
        name="Worlds",
        label="Worlds",
        is_current=True,
        enabled=True,
    ),
    PbDashScreen(
        ref_id="sc-2",
        key="Dash.Screens.Contacts",
        name="Contacts",
        label="Contacts",
        is_current=False,
        enabled=False,
    ),
]


class _FakeDash(DashBase):
    """In-process fake recording each request and returning fixed values."""

    def __init__(self) -> None:
        self.open_requests: list[DashOpenRequest] = []
        self.close_requests: list[DashCloseRequest] = []
        self.get_state_requests: list[DashGetStateRequest] = []
        self.get_tree_requests: list[DashGetTreeRequest] = []
        self.invoke_requests: list[DashInvokeRequest] = []
        self.highlight_requests: list[DashHighlightRequest] = []
        self.scroll_requests: list[DashScrollRequest] = []
        self.list_screens_requests: list[DashListScreensRequest] = []
        self.set_screen_requests: list[DashSetScreenRequest] = []

    async def open(self, message: DashOpenRequest) -> PbDashState:
        self.open_requests.append(message)
        return PbDashState(is_open=True, open_lerp=1.0)

    async def close(self, message: DashCloseRequest) -> PbDashState:
        self.close_requests.append(message)
        return PbDashState(is_open=False, open_lerp=0.0)

    async def get_state(self, message: DashGetStateRequest) -> PbDashState:
        self.get_state_requests.append(message)
        return PbDashState(is_open=True, open_lerp=0.5)

    async def get_tree(self, message: DashGetTreeRequest) -> PbDashTree:
        self.get_tree_requests.append(message)
        return PbDashTree(elements=[_ELEMENT], screen_width=1920, screen_height=1080)

    async def invoke(self, message: DashInvokeRequest) -> PbDashActionResult:
        self.invoke_requests.append(message)
        return PbDashActionResult(ok=True, found=True, ref_id=message.ref_id, detail="")

    async def highlight(self, message: DashHighlightRequest) -> PbDashActionResult:
        self.highlight_requests.append(message)
        return PbDashActionResult(ok=True, found=True, ref_id=message.ref_id)

    async def scroll(self, message: DashScrollRequest) -> PbDashActionResult:
        self.scroll_requests.append(message)
        return PbDashActionResult(ok=True, found=True, ref_id=message.ref_id)

    async def list_screens(self, message: DashListScreensRequest) -> PbDashScreenList:
        self.list_screens_requests.append(message)
        return PbDashScreenList(screens=_SCREENS)

    async def set_screen(self, message: DashSetScreenRequest) -> PbDashActionResult:
        self.set_screen_requests.append(message)
        resolved = message.ref_id or message.key
        return PbDashActionResult(
            ok=True, found=True, ref_id=resolved, detail="navigated"
        )


async def test_open_invokes_open_rpc_and_prints_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    socket_path = tmp_path / "rio-dash.sock"
    fake = _FakeDash()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(["dash", "open"])
        rc = await _amain(args)
        assert rc == 0

        assert len(fake.open_requests) == 1
        out = capsys.readouterr().out.strip()
        assert out == "is_open=True\nopen_lerp=1.0"
    finally:
        server.close()
        await server.wait_closed()


async def test_close_invokes_close_rpc_and_prints_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    socket_path = tmp_path / "rio-dash.sock"
    fake = _FakeDash()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(["dash", "close"])
        rc = await _amain(args)
        assert rc == 0

        assert len(fake.close_requests) == 1
        out = capsys.readouterr().out.strip()
        assert out == "is_open=False\nopen_lerp=0.0"
    finally:
        server.close()
        await server.wait_closed()


async def test_state_invokes_get_state_rpc_read_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    socket_path = tmp_path / "rio-dash.sock"
    fake = _FakeDash()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(["dash", "state"])
        rc = await _amain(args)
        assert rc == 0

        assert len(fake.get_state_requests) == 1
        # `state` must be read-only: no open/close/invoke was issued.
        assert fake.open_requests == []
        assert fake.close_requests == []
        assert fake.invoke_requests == []

        out = capsys.readouterr().out.strip()
        assert out == "is_open=True\nopen_lerp=0.5"
    finally:
        server.close()
        await server.wait_closed()


async def test_tree_forwards_filters_and_prints_elements(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    socket_path = tmp_path / "rio-dash.sock"
    fake = _FakeDash()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(
            ["dash", "tree", "--interactable-only", "--root-ref-id", "slot-1"]
        )
        rc = await _amain(args)
        assert rc == 0

        assert len(fake.get_tree_requests) == 1
        wire = fake.get_tree_requests[0]
        assert wire.interactable_only is True
        assert wire.root_ref_id == "slot-1"

        out = capsys.readouterr().out.strip().splitlines()
        assert out[0] == "screen=1920x1080"
        assert out[1] == (
            "[s-1] Button locale='Settings.Audio' label='Audio' "
            "enabled=True interactable=True rect=(10.0, 20.0, 100.0, 30.0, canvas)"
        )
    finally:
        server.close()
        await server.wait_closed()


async def test_tree_defaults_send_unfiltered_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    socket_path = tmp_path / "rio-dash.sock"
    fake = _FakeDash()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(["dash", "tree"])
        rc = await _amain(args)
        assert rc == 0

        wire = fake.get_tree_requests[0]
        assert wire.interactable_only is False
        assert wire.root_ref_id == ""
    finally:
        server.close()
        await server.wait_closed()


async def test_invoke_forwards_ref_id_and_prints_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    socket_path = tmp_path / "rio-dash.sock"
    fake = _FakeDash()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(["dash", "invoke", "s-7"])
        rc = await _amain(args)
        assert rc == 0

        assert len(fake.invoke_requests) == 1
        assert fake.invoke_requests[0].ref_id == "s-7"

        out = capsys.readouterr().out.strip()
        assert out == "ok=True found=True ref_id=s-7 detail=''"
    finally:
        server.close()
        await server.wait_closed()


async def test_socket_flag_routes_to_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """``-s SOCK`` is the sole socket route (env var would mask intent)."""
    socket_path = tmp_path / "rio-dash.sock"
    fake = _FakeDash()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.delenv("RESONITE_IO_SOCKET", raising=False)
        args = _build_parser().parse_args(["dash", "state", "-s", str(socket_path)])
        rc = await _amain(args)
        assert rc == 0
        assert len(fake.get_state_requests) == 1
    finally:
        server.close()
        await server.wait_closed()


def test_invoke_without_ref_id_is_a_parse_error():
    """``invoke`` requires a ref_id positional; omitting it exits 2 at
    parse."""
    assert _parse_error_code(["dash", "invoke"]) == 2


def test_missing_subcommand_is_a_parse_error():
    """``dash`` without a subcommand is a usage error (exit 2)."""
    assert _parse_error_code(["dash"]) == 2


def test_unknown_subcommand_is_a_parse_error():
    """An unknown ``dash`` subcommand is a usage error (exit 2)."""
    assert _parse_error_code(["dash", "toggle"]) == 2


async def test_screens_invokes_list_screens_rpc_and_prints_one_line_per_screen(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    socket_path = tmp_path / "rio-dash.sock"
    fake = _FakeDash()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(["dash", "screens"])
        rc = await _amain(args)
        assert rc == 0

        assert len(fake.list_screens_requests) == 1
        # `screens` is browse-only: it must not navigate.
        assert fake.set_screen_requests == []

        out = capsys.readouterr().out.strip().splitlines()
        # One line per screen, no header, in the documented field order.
        assert out == [
            "[sc-1] Dash.Screens.Worlds Worlds is_current=True enabled=True "
            "label='Worlds'",
            "[sc-2] Dash.Screens.Contacts Contacts is_current=False "
            "enabled=False label='Contacts'",
        ]
    finally:
        server.close()
        await server.wait_closed()


async def test_set_screen_with_positional_key_forwards_key_and_prints_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    socket_path = tmp_path / "rio-dash.sock"
    fake = _FakeDash()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(["dash", "set-screen", "Dash.Screens.Worlds"])
        rc = await _amain(args)
        assert rc == 0

        assert len(fake.set_screen_requests) == 1
        wire = fake.set_screen_requests[0]
        # The positional target is the screen key; ref_id stays empty.
        assert wire.key == "Dash.Screens.Worlds"
        assert wire.ref_id == ""

        out = capsys.readouterr().out.strip()
        assert out == (
            "ok=True found=True ref_id=Dash.Screens.Worlds detail='navigated'"
        )
    finally:
        server.close()
        await server.wait_closed()


async def test_set_screen_with_ref_id_option_forwards_ref_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    socket_path = tmp_path / "rio-dash.sock"
    fake = _FakeDash()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(["dash", "set-screen", "--ref-id", "sc-7"])
        rc = await _amain(args)
        assert rc == 0

        assert len(fake.set_screen_requests) == 1
        wire = fake.set_screen_requests[0]
        # --ref-id supplies the exact selector; the positional key is empty.
        assert wire.ref_id == "sc-7"
        assert wire.key == ""

        out = capsys.readouterr().out.strip()
        assert out == "ok=True found=True ref_id=sc-7 detail='navigated'"
    finally:
        server.close()
        await server.wait_closed()


async def test_set_screen_without_key_or_ref_id_exits_2():
    """``set-screen`` requires a key or --ref-id; omitting both exits 2."""
    assert await _run_cli(["dash", "set-screen"]) == 2
