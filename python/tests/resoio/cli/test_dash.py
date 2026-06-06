"""CLI tests for ``resoio dash``.

The CLI register/_run path is driven against a real ``grpclib.server.Server``
hosting an inline fake :class:`DashBase` over a real UDS (no mocking of
grpclib/betterproto2). Each test asserts that the chosen action invokes the
correct RPC with the correct arguments and that the result is printed in the
documented format. Argparse-level errors (missing ref_id for invoke) are
checked for exit code / stderr.
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
    DashOpenRequest,
    DashRect as PbDashRect,
    DashScrollRequest,
    DashState as PbDashState,
    DashTree as PbDashTree,
)
from resoio.cli import _amain, _build_parser

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


async def test_invoke_without_ref_id_errors(
    capsys: pytest.CaptureFixture[str],
):
    """``invoke`` requires a ref_id; missing it is a usage error."""
    args = _build_parser().parse_args(["dash", "invoke"])
    rc = await _amain(args)
    assert rc == 2
    assert "ref_id" in capsys.readouterr().err
