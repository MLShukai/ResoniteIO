"""Integration-real tests for :class:`resoio.cursor.CursorClient`.

A real ``grpclib.server.Server`` hosting an inline fake :class:`CursorBase`
handler is bound to a real UDS under ``tmp_path`` and driven by the real
``CursorClient`` over the wire (no mocking of grpclib/betterproto2
internals). This verifies that ``set_position`` forwards ``(x, y)`` to the
server, that ``release`` issues the new Release RPC, and that all three
RPCs decode the returned ``CursorState`` (every field, including the
``held`` hold flag introduced by the persistent-hold semantics:
``set_position`` holds until ``release``).
"""

from pathlib import Path

import pytest
from grpclib.server import Server

from resoio._generated.resonite_io.v1 import (
    CursorBase,
    CursorGetPositionRequest,
    CursorReleaseRequest,
    CursorSetPositionRequest,
    CursorState as PbCursorState,
)
from resoio.cursor import CursorClient, CursorState


class _FakeCursor(CursorBase):
    """In-process fake recording each request and returning a fixed state.

    Mirrors the spec's hold contract on the wire: ``set_position`` echoes
    the requested ``(x, y)`` back with ``held=True`` (a successful set
    establishes the hold), ``get_position`` returns ``self.state``
    verbatim, and ``release`` returns the same position with
    ``held=False`` (the hold has been dropped).
    """

    def __init__(self) -> None:
        self.set_requests: list[CursorSetPositionRequest] = []
        self.get_requests: list[CursorGetPositionRequest] = []
        self.release_requests: list[CursorReleaseRequest] = []
        self.state = PbCursorState(
            x=0.5, y=0.25, window_width=1920, window_height=1080, held=True
        )

    async def set_position(self, message: CursorSetPositionRequest) -> PbCursorState:
        self.set_requests.append(message)
        return PbCursorState(
            x=message.x, y=message.y, window_width=1920, window_height=1080, held=True
        )

    async def get_position(self, message: CursorGetPositionRequest) -> PbCursorState:
        self.get_requests.append(message)
        return self.state

    async def release(self, message: CursorReleaseRequest) -> PbCursorState:
        self.release_requests.append(message)
        return PbCursorState(
            x=0.5, y=0.25, window_width=1920, window_height=1080, held=False
        )


class TestCursorClient:
    async def test_set_position_sends_xy_and_decodes_held_state(
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
            # Spec: a successful set_position establishes the hold and
            # returns held=True.
            assert state.held is True
        finally:
            server.close()
            await server.wait_closed()

    async def test_get_position_is_read_only_and_decodes_held_state(
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
            # `get_position` must not move or release the cursor.
            assert fake.set_requests == []
            assert fake.release_requests == []

            assert state.x == pytest.approx(0.5)
            assert state.y == pytest.approx(0.25)
            assert state.window_width == 1920
            assert state.window_height == 1080
            # The hold state observed by the server must reach the caller.
            assert state.held is True
        finally:
            server.close()
            await server.wait_closed()

    async def test_release_sends_release_rpc_and_decodes_unheld_state(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        socket_path = tmp_path / "rio-cursor.sock"
        fake = _FakeCursor()
        server = Server([fake])
        await server.start(path=str(socket_path))
        try:
            monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
            async with CursorClient() as client:
                state = await client.release()

            assert len(fake.release_requests) == 1
            # `release` must not issue set/get RPCs.
            assert fake.set_requests == []
            assert fake.get_requests == []

            assert isinstance(state, CursorState)
            assert state.x == pytest.approx(0.5)
            assert state.y == pytest.approx(0.25)
            assert state.window_width == 1920
            assert state.window_height == 1080
            # Spec: release drops the hold and returns held=False.
            assert state.held is False
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

    async def test_release_raises_when_not_connected(self):
        client = CursorClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.release()
