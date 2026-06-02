"""CLI tests for ``resoio context-menu``.

The CLI register/_run path is driven against a real ``grpclib.server.Server``
hosting an inline fake :class:`ContextMenuBase` over a real UDS (no mocking
of grpclib/betterproto2). Each test asserts that the chosen action invokes
the correct RPC with the correct ``hand`` (and ``index`` for
highlight/invoke) and that the resulting menu state is printed in the
documented format. Argparse-level errors (missing index) are checked
separately for exit code / stderr.
"""

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


async def test_highlight_without_index_errors(
    capsys: pytest.CaptureFixture[str],
):
    """``highlight`` requires an item index; missing it is a usage error."""
    args = _build_parser().parse_args(["context-menu", "highlight"])
    rc = await _amain(args)
    assert rc == 2
    assert "index" in capsys.readouterr().err


async def test_invoke_without_index_errors(
    capsys: pytest.CaptureFixture[str],
):
    args = _build_parser().parse_args(["context-menu", "invoke"])
    rc = await _amain(args)
    assert rc == 2
    assert "index" in capsys.readouterr().err
