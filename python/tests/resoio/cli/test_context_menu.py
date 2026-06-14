"""CLI tests for ``resoio context-menu``.

The CLI register/_run path is driven against a real ``grpclib.server.Server``
hosting an inline fake :class:`ContextMenuBase` over a real UDS (no mocking
of grpclib/betterproto2). Each test asserts that the chosen action invokes
the correct RPC with the correct ``hand`` (and ``index`` for
highlight/invoke) and that the resulting menu state is printed in the
documented format.

Per the subparser contract, ``highlight`` / ``invoke`` take a required int
``index`` positional: a missing or non-numeric index, a missing subcommand,
or an unknown subcommand is an argparse usage error (SystemExit with code 2
at ``parse_args`` time). A negative index is pinned by exit code only
(``_run_cli`` normalizes parse-time SystemExit and runtime return codes).
"""

import json
from pathlib import Path

import pytest
from grpclib.server import Server

from resoio._generated.resonite_io.v1 import (
    ContextMenuBase,
    ContextMenuCloseRequest,
    ContextMenuGetStateRequest,
    ContextMenuHand,
    ContextMenuHighlightRequest,
    ContextMenuInvokeRequest,
    ContextMenuItem as PbContextMenuItem,
    ContextMenuOpenRequest,
    ContextMenuState as PbContextMenuState,
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


# Color components chosen to be exactly representable as float32 so the
# printed `color=(...)` tuple is stable across the proto round-trip.
_ITEM = PbContextMenuItem(
    index=0,
    label="Move",
    enabled=True,
    has_icon=False,
    color_r=0.5,
    color_g=0.25,
    color_b=1.0,
    color_a=0.0,
)


def _open_state(highlighted_index: int = -1) -> PbContextMenuState:
    return PbContextMenuState(
        is_open=True, items=[_ITEM], highlighted_index=highlighted_index
    )


class _FakeContextMenu(ContextMenuBase):
    """In-process fake recording each request and returning a fixed state."""

    def __init__(self) -> None:
        self.open_requests: list[ContextMenuOpenRequest] = []
        self.close_requests: list[ContextMenuCloseRequest] = []
        self.get_state_requests: list[ContextMenuGetStateRequest] = []
        self.highlight_requests: list[ContextMenuHighlightRequest] = []
        self.invoke_requests: list[ContextMenuInvokeRequest] = []

    async def open(self, message: ContextMenuOpenRequest) -> PbContextMenuState:
        self.open_requests.append(message)
        return _open_state()

    async def close(self, message: ContextMenuCloseRequest) -> PbContextMenuState:
        self.close_requests.append(message)
        return PbContextMenuState(is_open=False, items=[], highlighted_index=-1)

    async def get_state(
        self, message: ContextMenuGetStateRequest
    ) -> PbContextMenuState:
        self.get_state_requests.append(message)
        return _open_state(highlighted_index=0)

    async def highlight(
        self, message: ContextMenuHighlightRequest
    ) -> PbContextMenuState:
        self.highlight_requests.append(message)
        return _open_state(highlighted_index=message.index)

    async def invoke(self, message: ContextMenuInvokeRequest) -> PbContextMenuState:
        self.invoke_requests.append(message)
        return _open_state(highlighted_index=message.index)


async def test_open_invokes_open_rpc_and_prints_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    socket_path = tmp_path / "rio-context-menu.sock"
    fake = _FakeContextMenu()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(["context-menu", "open"])
        rc = await _amain(args)
        assert rc == 0

        assert len(fake.open_requests) == 1
        assert fake.open_requests[0].hand == ContextMenuHand.PRIMARY

        out = capsys.readouterr().out.strip().splitlines()
        assert out[0] == "is_open=True"
        assert (
            out[1] == "[0] 'Move' enabled=True icon=False color=(0.5, 0.25, 1.0, 0.0)"
        )
        assert out[2] == "highlighted_index=-1"
    finally:
        server.close()
        await server.wait_closed()


async def test_close_invokes_close_rpc_with_hand(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    socket_path = tmp_path / "rio-context-menu.sock"
    fake = _FakeContextMenu()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(["context-menu", "close", "--hand", "left"])
        rc = await _amain(args)
        assert rc == 0

        assert len(fake.close_requests) == 1
        assert fake.close_requests[0].hand == ContextMenuHand.LEFT

        out = capsys.readouterr().out.strip()
        assert out == "is_open=False\nhighlighted_index=-1"
    finally:
        server.close()
        await server.wait_closed()


async def test_list_invokes_get_state_rpc(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    socket_path = tmp_path / "rio-context-menu.sock"
    fake = _FakeContextMenu()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(["context-menu", "list"])
        rc = await _amain(args)
        assert rc == 0

        assert len(fake.get_state_requests) == 1
        assert fake.get_state_requests[0].hand == ContextMenuHand.PRIMARY
        # `list` must be read-only: no open/highlight/invoke was issued.
        assert fake.open_requests == []
        assert fake.highlight_requests == []
        assert fake.invoke_requests == []

        out = capsys.readouterr().out.strip().splitlines()
        assert out[0] == "is_open=True"
        assert out[-1] == "highlighted_index=0"
    finally:
        server.close()
        await server.wait_closed()


async def test_highlight_forwards_index_and_hand(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    socket_path = tmp_path / "rio-context-menu.sock"
    fake = _FakeContextMenu()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(
            ["context-menu", "highlight", "0", "--hand", "right"]
        )
        rc = await _amain(args)
        assert rc == 0

        assert len(fake.highlight_requests) == 1
        wire = fake.highlight_requests[0]
        assert wire.index == 0
        assert wire.hand == ContextMenuHand.RIGHT

        out = capsys.readouterr().out.strip().splitlines()
        assert out[-1] == "highlighted_index=0"
    finally:
        server.close()
        await server.wait_closed()


async def test_invoke_forwards_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    socket_path = tmp_path / "rio-context-menu.sock"
    fake = _FakeContextMenu()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(["context-menu", "invoke", "0"])
        rc = await _amain(args)
        assert rc == 0

        assert len(fake.invoke_requests) == 1
        assert fake.invoke_requests[0].index == 0
        assert fake.invoke_requests[0].hand == ContextMenuHand.PRIMARY
    finally:
        server.close()
        await server.wait_closed()


async def test_socket_flag_routes_to_get_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """``-s SOCK`` is the sole socket route (env var would mask intent)."""
    socket_path = tmp_path / "rio-context-menu.sock"
    fake = _FakeContextMenu()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.delenv("RESONITE_IO_SOCKET", raising=False)
        args = _build_parser().parse_args(
            ["context-menu", "list", "-s", str(socket_path)]
        )
        rc = await _amain(args)
        assert rc == 0
        assert len(fake.get_state_requests) == 1
    finally:
        server.close()
        await server.wait_closed()


def test_highlight_without_index_is_a_parse_error():
    """``highlight`` requires an item index; omitting it exits 2 at parse."""
    assert _parse_error_code(["context-menu", "highlight"]) == 2


def test_invoke_without_index_is_a_parse_error():
    """``invoke`` requires an item index; omitting it exits 2 at parse."""
    assert _parse_error_code(["context-menu", "invoke"]) == 2


def test_invoke_with_non_numeric_index_is_a_parse_error():
    """The index is an argparse int; non-numeric input exits 2 at parse."""
    assert _parse_error_code(["context-menu", "invoke", "first"]) == 2


async def test_invoke_with_negative_index_exits_2():
    """A negative index is rejected with exit code 2."""
    assert await _run_cli(["context-menu", "invoke", "-1"]) == 2


def test_missing_subcommand_is_a_parse_error():
    """``context-menu`` without a subcommand is a usage error (exit 2)."""
    assert _parse_error_code(["context-menu"]) == 2


def test_unknown_subcommand_is_a_parse_error():
    """An unknown ``context-menu`` subcommand is a usage error (exit 2)."""
    assert _parse_error_code(["context-menu", "toggle"]) == 2


# --- --format json --------------------------------------------------------
#
# ``--format json`` emits the ContextMenuState as a single document on
# stdout: ``{is_open, highlighted_index, items:[...]}`` where each item's
# ``color`` tuple becomes a 4-element array (``to_jsonable`` collapses the
# tuple). The colour components are exactly representable in float32 so they
# survive the proto round-trip unchanged.

_ITEM_JSON = {
    "index": 0,
    "label": "Move",
    "enabled": True,
    "has_icon": False,
    "color": [0.5, 0.25, 1.0, 0.0],
}


def _sole_json_document(out: str) -> object:
    """Parse ``out`` as exactly one JSON document and return it.

    Pins the "stdout holds exactly ONE json document" contract: the
    captured output must decode as a single top-level value with nothing
    but trailing whitespace after it.
    """
    decoded, end = json.JSONDecoder().raw_decode(out)
    assert out[end:].strip() == ""
    return decoded


async def test_open_json_emits_context_menu_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    socket_path = tmp_path / "rio-context-menu.sock"
    fake = _FakeContextMenu()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(["context-menu", "open", "--format", "json"])
        rc = await _amain(args)
        assert rc == 0

        payload = _sole_json_document(capsys.readouterr().out)
        # The item color tuple is rendered as a 4-element array.
        assert payload == {
            "is_open": True,
            "items": [_ITEM_JSON],
            "highlighted_index": -1,
        }
    finally:
        server.close()
        await server.wait_closed()


async def test_close_json_emits_closed_state_with_empty_items(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    socket_path = tmp_path / "rio-context-menu.sock"
    fake = _FakeContextMenu()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(["context-menu", "close", "--format", "json"])
        rc = await _amain(args)
        assert rc == 0

        payload = _sole_json_document(capsys.readouterr().out)
        assert payload == {"is_open": False, "items": [], "highlighted_index": -1}
    finally:
        server.close()
        await server.wait_closed()


async def test_list_json_emits_state_with_highlighted_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    socket_path = tmp_path / "rio-context-menu.sock"
    fake = _FakeContextMenu()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(["context-menu", "list", "--format", "json"])
        rc = await _amain(args)
        assert rc == 0

        assert len(fake.get_state_requests) == 1
        payload = _sole_json_document(capsys.readouterr().out)
        assert payload == {
            "is_open": True,
            "items": [_ITEM_JSON],
            "highlighted_index": 0,
        }
    finally:
        server.close()
        await server.wait_closed()


async def test_highlight_json_reflects_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    socket_path = tmp_path / "rio-context-menu.sock"
    fake = _FakeContextMenu()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(
            ["context-menu", "highlight", "0", "--format", "json"]
        )
        rc = await _amain(args)
        assert rc == 0

        payload = _sole_json_document(capsys.readouterr().out)
        assert isinstance(payload, dict)
        assert payload["highlighted_index"] == 0
        assert payload["items"] == [_ITEM_JSON]
    finally:
        server.close()
        await server.wait_closed()


async def test_invoke_json_emits_context_menu_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    socket_path = tmp_path / "rio-context-menu.sock"
    fake = _FakeContextMenu()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(
            ["context-menu", "invoke", "0", "--format", "json"]
        )
        rc = await _amain(args)
        assert rc == 0

        assert len(fake.invoke_requests) == 1
        payload = _sole_json_document(capsys.readouterr().out)
        assert payload == {
            "is_open": True,
            "items": [_ITEM_JSON],
            "highlighted_index": 0,
        }
    finally:
        server.close()
        await server.wait_closed()
