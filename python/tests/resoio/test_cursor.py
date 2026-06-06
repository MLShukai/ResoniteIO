"""Integration-real tests for :class:`resoio.cursor.CursorClient`.

A real ``grpclib.server.Server`` hosting an inline fake :class:`CursorBase`
handler is bound to a real UDS under ``tmp_path`` and driven by the real
``CursorClient`` over the wire (no mocking of grpclib/betterproto2
internals). This verifies that ``set_position`` forwards ``(x, y)`` to the
server and that both RPCs decode the returned ``CursorState`` (every
field, including window resolution).
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
from resoio.cursor import CursorClient, CursorState


class _FakeCursor(CursorBase):
    """In-process fake recording each request and returning a fixed state.

    ``set_position`` echoes the requested ``(x, y)`` back (with a fixed
    resolution) so a test can prove the coordinates reached the server;
    ``get_position`` returns a deterministic state without recording any
    movement.
    """

    def __init__(self) -> None:
        self.set_requests: list[CursorSetPositionRequest] = []
        self.get_requests: list[CursorGetPositionRequest] = []
        self.state = PbCursorState(x=0.5, y=0.25, window_width=1920, window_height=1080)

    async def set_position(self, message: CursorSetPositionRequest) -> PbCursorState:
        self.set_requests.append(message)
        return PbCursorState(
            x=message.x, y=message.y, window_width=1920, window_height=1080
        )

    async def get_position(self, message: CursorGetPositionRequest) -> PbCursorState:
        self.get_requests.append(message)
        return self.state


class TestCursorClient:
    async def test_set_position_sends_xy_and_decodes_state(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        socket_path = tmp_path / "rio-cursor.sock"
        fake = _FakeCursor()
        server = Server([fake])
        await server.start(path=str(socket_path))
        try:
            monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
            async with CursorClient() as client:
                assert client.socket_path == str(socket_path)
                state = await client.set_position(0.5, 0.25)

            assert len(fake.set_requests) == 1
            assert fake.set_requests[0].x == pytest.approx(0.5)
            assert fake.set_requests[0].y == pytest.approx(0.25)

            assert isinstance(state, CursorState)
            assert state.x == pytest.approx(0.5)
            assert state.y == pytest.approx(0.25)
            assert state.window_width == 1920
            assert state.window_height == 1080
        finally:
            server.close()
            await server.wait_closed()

    async def test_get_position_is_read_only_and_decodes_state(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        socket_path = tmp_path / "rio-cursor.sock"
        fake = _FakeCursor()
        server = Server([fake])
        await server.start(path=str(socket_path))
        try:
            monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
            async with CursorClient() as client:
                state = await client.get_position()

            assert len(fake.get_requests) == 1
            # `get_position` must not move the cursor.
            assert fake.set_requests == []

            assert state.x == pytest.approx(0.5)
            assert state.y == pytest.approx(0.25)
            assert state.window_width == 1920
            assert state.window_height == 1080
        finally:
            server.close()
            await server.wait_closed()

    async def test_set_position_raises_when_not_connected(self):
        client = CursorClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.set_position(0.5, 0.5)

    async def test_get_position_raises_when_not_connected(self):
        client = CursorClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.get_position()
