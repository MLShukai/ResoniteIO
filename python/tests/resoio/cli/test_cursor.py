"""CLI tests for ``resoio cursor``.

The CLI register/_run path is driven against a real ``grpclib.server.Server``
hosting an inline fake :class:`CursorBase` over a real UDS (no mocking of
grpclib/betterproto2). Each test asserts that the chosen action invokes the
correct RPC with the correct coordinates and that the resulting cursor
state is printed in the documented format. Argparse/validation errors
(missing or out-of-range coordinates) are checked for exit code / stderr.
"""

from pathlib import Path

import pytest
from grpclib.server import Server

from resoio._generated.resonite_io.v1 import (
    CursorBase,
    CursorGetPositionRequest,
    CursorSetPositionRequest,
    CursorState as PbCursorState,
)
from resoio.cli import _amain, _build_parser


class _FakeCursor(CursorBase):
    """In-process fake recording each request and returning a fixed state."""

    def __init__(self) -> None:
        self.set_requests: list[CursorSetPositionRequest] = []
        self.get_requests: list[CursorGetPositionRequest] = []

    async def set_position(self, message: CursorSetPositionRequest) -> PbCursorState:
        self.set_requests.append(message)
        return PbCursorState(
            x=message.x, y=message.y, window_width=1920, window_height=1080
        )

    async def get_position(self, message: CursorGetPositionRequest) -> PbCursorState:
        self.get_requests.append(message)
        return PbCursorState(x=0.5, y=0.25, window_width=1920, window_height=1080)


async def test_set_forwards_xy_and_prints_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    socket_path = tmp_path / "rio-cursor.sock"
    fake = _FakeCursor()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(["cursor", "set", "0.5", "0.25"])
        rc = await _amain(args)
        assert rc == 0

        assert len(fake.set_requests) == 1
        assert fake.set_requests[0].x == pytest.approx(0.5)
        assert fake.set_requests[0].y == pytest.approx(0.25)

        out = capsys.readouterr().out.strip()
        assert out == "x=0.5 y=0.25 window=1920x1080"
    finally:
        server.close()
        await server.wait_closed()


async def test_center_moves_to_half_half(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    socket_path = tmp_path / "rio-cursor.sock"
    fake = _FakeCursor()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(["cursor", "center"])
        rc = await _amain(args)
        assert rc == 0

        assert len(fake.set_requests) == 1
        assert fake.set_requests[0].x == pytest.approx(0.5)
        assert fake.set_requests[0].y == pytest.approx(0.5)
    finally:
        server.close()
        await server.wait_closed()


async def test_get_is_read_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    socket_path = tmp_path / "rio-cursor.sock"
    fake = _FakeCursor()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        args = _build_parser().parse_args(["cursor", "get"])
        rc = await _amain(args)
        assert rc == 0

        assert len(fake.get_requests) == 1
        assert fake.set_requests == []

        out = capsys.readouterr().out.strip()
        assert out == "x=0.5 y=0.25 window=1920x1080"
    finally:
        server.close()
        await server.wait_closed()


async def test_socket_flag_routes_to_get_position(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """``-s SOCK`` is the sole socket route (env var would mask intent)."""
    socket_path = tmp_path / "rio-cursor.sock"
    fake = _FakeCursor()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        monkeypatch.delenv("RESONITE_IO_SOCKET", raising=False)
        args = _build_parser().parse_args(["cursor", "get", "-s", str(socket_path)])
        rc = await _amain(args)
        assert rc == 0
        assert len(fake.get_requests) == 1
    finally:
        server.close()
        await server.wait_closed()


async def test_set_without_coords_errors(
    capsys: pytest.CaptureFixture[str],
):
    """``set`` requires x and y; missing them is a usage error."""
    args = _build_parser().parse_args(["cursor", "set"])
    rc = await _amain(args)
    assert rc == 2
    assert "x and y" in capsys.readouterr().err


async def test_set_out_of_range_errors(
    capsys: pytest.CaptureFixture[str],
):
    """Coordinates outside [0,1] are rejected before any RPC is issued."""
    args = _build_parser().parse_args(["cursor", "set", "1.5", "0.5"])
    rc = await _amain(args)
    assert rc == 2
    assert "[0,1]" in capsys.readouterr().err
