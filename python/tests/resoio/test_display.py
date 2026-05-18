from pathlib import Path

import pytest
from grpclib.server import Server

from resoio._generated.resonite_io.v1 import (
    DisplayBase,
    DisplayConfig,
    DisplayGetRequest,
    DisplayState,
)
from resoio.display import DisplayClient, DisplayInfo


class _FakeDisplay(DisplayBase):
    """In-process fake that records the last Apply config and exposes a mutable
    current state for the test to assert against."""

    def __init__(self, initial: DisplayState) -> None:
        self.current = initial
        self.last_apply: DisplayConfig | None = None

    async def apply(self, message: DisplayConfig) -> DisplayState:
        self.last_apply = message
        # Mirror the server-side "0 = unchanged" semantics so the
        # returned snapshot reflects an engine that ignored zero fields.
        new = DisplayState(
            width=message.width or self.current.width,
            height=message.height or self.current.height,
            max_fps=message.max_fps or self.current.max_fps,
        )
        self.current = new
        return new

    async def get(self, message: DisplayGetRequest) -> DisplayState:
        return self.current


class TestDisplayClient:
    async def test_apply_returns_info(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        socket_path = tmp_path / "rio-display.sock"
        fake = _FakeDisplay(DisplayState(width=800, height=600, max_fps=30.0))
        server = Server([fake])
        await server.start(path=str(socket_path))
        try:
            monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
            async with DisplayClient() as client:
                assert client.socket_path == str(socket_path)
                info = await client.apply(width=1920, height=1080, max_fps=120.0)
            assert info == DisplayInfo(width=1920, height=1080, max_fps=120.0)
            assert fake.last_apply is not None
            assert fake.last_apply.width == 1920
            assert fake.last_apply.height == 1080
            assert fake.last_apply.max_fps == 120.0
        finally:
            server.close()
            await server.wait_closed()

    async def test_apply_with_zero_passes_zero_to_server(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """proto3 default value: 0 means "leave unchanged" and the client must
        forward it raw so the server can detect the omission."""
        socket_path = tmp_path / "rio-display.sock"
        fake = _FakeDisplay(DisplayState(width=1280, height=720, max_fps=60.0))
        server = Server([fake])
        await server.start(path=str(socket_path))
        try:
            monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
            async with DisplayClient() as client:
                info = await client.apply(max_fps=120.0)
            # Server saw width/height=0, max_fps=120.
            assert fake.last_apply is not None
            assert fake.last_apply.width == 0
            assert fake.last_apply.height == 0
            assert fake.last_apply.max_fps == 120.0
            # Returned state reflects the fake's "0 = keep" behavior.
            assert info == DisplayInfo(width=1280, height=720, max_fps=120.0)
        finally:
            server.close()
            await server.wait_closed()

    async def test_get_returns_current_state(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        socket_path = tmp_path / "rio-display.sock"
        fake = _FakeDisplay(DisplayState(width=2560, height=1440, max_fps=144.0))
        server = Server([fake])
        await server.start(path=str(socket_path))
        try:
            monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
            async with DisplayClient() as client:
                info = await client.get()
            assert info == DisplayInfo(width=2560, height=1440, max_fps=144.0)
            # `get` must not record an Apply.
            assert fake.last_apply is None
        finally:
            server.close()
            await server.wait_closed()

    async def test_raises_when_apply_outside_context(self):
        client = DisplayClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.apply(width=1920)

    async def test_raises_when_get_outside_context(self):
        client = DisplayClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.get()
