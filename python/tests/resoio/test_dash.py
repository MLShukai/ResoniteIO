"""Integration-real tests for :class:`resoio.dash.DashClient`.

A real ``grpclib.server.Server`` hosting an inline fake :class:`DashBase`
handler is bound to a real UDS under ``tmp_path`` and driven by the real
``DashClient`` over the wire (no mocking of grpclib/betterproto2
internals). This verifies that each of the seven unary RPCs reaches the
server with the correct request fields and that the returned
``DashState`` / ``DashTree`` / ``DashActionResult`` dataclasses round-trip
every field — including nested ``DashRect`` fields, element order, and the
``screen_width`` / ``screen_height`` grounding dimensions.

The fakes deliberately give every field a *distinct* value (and use both
``True`` and ``False`` for booleans such as ``is_screen_space``) so that a
swapped, dropped, or mis-mapped field would change an assertion result.
``float`` fields are compared with :func:`pytest.approx` because the proto
``float`` type is float32, so an exact ``==`` would be brittle across the
serialization round-trip.
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
from resoio.dash import (
    DashActionResult,
    DashClient,
    DashElement,
    DashRect,
    DashScreen,
    DashState,
    DashTree,
)

# A two-element tree used by the get_tree round-trip test. Every scalar
# field across both elements (and their nested rects) holds a different
# value, and the two rects use opposite ``is_screen_space`` flags, so any
# field swap/drop would surface as a mismatch.
_FIRST_ELEMENT = PbDashElement(
    ref_id="ref-1",
    type="Button",
    slot_name="OpenSettingsButton",
    locale_key="Settings.Open",
    label="Open Settings",
    enabled=True,
    interactable=True,
    rect=PbDashRect(
        x=1.0,
        y=2.0,
        width=3.0,
        height=4.0,
        is_screen_space=True,
    ),
    parent_ref_id="",
    depth=0,
)
_SECOND_ELEMENT = PbDashElement(
    ref_id="ref-2",
    type="ScrollRect",
    slot_name="ContentScroll",
    locale_key="",
    label="Content",
    enabled=False,
    interactable=False,
    rect=PbDashRect(
        x=5.0,
        y=6.0,
        width=7.0,
        height=8.0,
        is_screen_space=False,
    ),
    parent_ref_id="ref-1",
    depth=1,
)

_SCREEN_WIDTH = 1920
_SCREEN_HEIGHT = 1080


def _two_element_tree() -> PbDashTree:
    return PbDashTree(
        elements=[_FIRST_ELEMENT, _SECOND_ELEMENT],
        screen_width=_SCREEN_WIDTH,
        screen_height=_SCREEN_HEIGHT,
    )


_EXPECTED_TREE_ELEMENTS = (
    DashElement(
        ref_id="ref-1",
        type="Button",
        slot_name="OpenSettingsButton",
        locale_key="Settings.Open",
        label="Open Settings",
        enabled=True,
        interactable=True,
        rect=DashRect(
            x=pytest.approx(1.0),
            y=pytest.approx(2.0),
            width=pytest.approx(3.0),
            height=pytest.approx(4.0),
            is_screen_space=True,
        ),
        parent_ref_id="",
        depth=0,
    ),
    DashElement(
        ref_id="ref-2",
        type="ScrollRect",
        slot_name="ContentScroll",
        locale_key="",
        label="Content",
        enabled=False,
        interactable=False,
        rect=DashRect(
            x=pytest.approx(5.0),
            y=pytest.approx(6.0),
            width=pytest.approx(7.0),
            height=pytest.approx(8.0),
            is_screen_space=False,
        ),
        parent_ref_id="ref-1",
        depth=1,
    ),
)


# A two-screen list used by the list_screens round-trip test. Every scalar
# field on both screens holds a different value, and the two screens use
# opposite ``is_current`` / ``enabled`` flags, so any field swap/drop or a
# reordered list would surface as a mismatch.
_FIRST_SCREEN = PbDashScreen(
    ref_id="screen-ref-1",
    key="Dash.Screens.Worlds",
    name="Worlds",
    label="Worlds",
    is_current=True,
    enabled=True,
)
_SECOND_SCREEN = PbDashScreen(
    ref_id="screen-ref-2",
    key="Dash.Screens.Contacts",
    name="Contacts",
    label="Contacts (logged out)",
    is_current=False,
    enabled=False,
)


def _two_screen_list() -> PbDashScreenList:
    return PbDashScreenList(screens=[_FIRST_SCREEN, _SECOND_SCREEN])


_EXPECTED_SCREENS = [
    DashScreen(
        ref_id="screen-ref-1",
        key="Dash.Screens.Worlds",
        name="Worlds",
        label="Worlds",
        is_current=True,
        enabled=True,
    ),
    DashScreen(
        ref_id="screen-ref-2",
        key="Dash.Screens.Contacts",
        name="Contacts",
        label="Contacts (logged out)",
        is_current=False,
        enabled=False,
    ),
]


class _FakeDash(DashBase):
    """In-process fake that records each request and returns fixed protos.

    Each RPC stores the request it received so a test can assert the
    fields that reached the server, then returns a deterministic proto
    so the client-side decoding can be checked end-to-end.
    """

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
        return _two_element_tree()

    async def invoke(self, message: DashInvokeRequest) -> PbDashActionResult:
        self.invoke_requests.append(message)
        return PbDashActionResult(
            ok=True,
            found=True,
            ref_id=message.ref_id,
            detail="invoked",
        )

    async def highlight(self, message: DashHighlightRequest) -> PbDashActionResult:
        self.highlight_requests.append(message)
        return PbDashActionResult(
            ok=True,
            found=True,
            ref_id=message.ref_id,
            detail="highlighted",
        )

    async def scroll(self, message: DashScrollRequest) -> PbDashActionResult:
        self.scroll_requests.append(message)
        return PbDashActionResult(
            ok=True,
            found=True,
            ref_id=message.ref_id,
            detail="scrolled",
        )

    async def list_screens(self, message: DashListScreensRequest) -> PbDashScreenList:
        self.list_screens_requests.append(message)
        return _two_screen_list()

    async def set_screen(self, message: DashSetScreenRequest) -> PbDashActionResult:
        self.set_screen_requests.append(message)
        # Echo whichever selector arrived (ref_id takes precedence) so a test
        # can prove the chosen field crossed the wire; mirrors the bridge
        # returning the post-navigation current screen's ref_id.
        resolved = message.ref_id or message.key
        return PbDashActionResult(
            ok=True,
            found=True,
            ref_id=resolved,
            detail="navigated",
        )


class TestDashClient:
    async def test_open_calls_open_rpc_and_decodes_state(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        socket_path = tmp_path / "rio-dash.sock"
        fake = _FakeDash()
        server = Server([fake])
        await server.start(path=str(socket_path))
        try:
            monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
            async with DashClient() as client:
                assert client.socket_path == str(socket_path)
                state = await client.open()

            assert len(fake.open_requests) == 1
            # open is a mutating RPC: no other RPC should have fired.
            assert fake.close_requests == []
            assert fake.get_state_requests == []

            assert isinstance(state, DashState)
            assert state.is_open is True
            assert state.open_lerp == pytest.approx(1.0)
        finally:
            server.close()
            await server.wait_closed()

    async def test_close_calls_close_rpc_and_decodes_state(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        socket_path = tmp_path / "rio-dash.sock"
        fake = _FakeDash()
        server = Server([fake])
        await server.start(path=str(socket_path))
        try:
            monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
            async with DashClient() as client:
                state = await client.close()

            assert len(fake.close_requests) == 1
            assert fake.open_requests == []
            assert fake.get_state_requests == []

            assert isinstance(state, DashState)
            assert state.is_open is False
            assert state.open_lerp == pytest.approx(0.0)
        finally:
            server.close()
            await server.wait_closed()

    async def test_get_state_calls_get_state_rpc_and_is_read_only(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        socket_path = tmp_path / "rio-dash.sock"
        fake = _FakeDash()
        server = Server([fake])
        await server.start(path=str(socket_path))
        try:
            monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
            async with DashClient() as client:
                state = await client.get_state()

            assert len(fake.get_state_requests) == 1
            assert isinstance(state, DashState)
            assert state.is_open is True
            assert state.open_lerp == pytest.approx(0.5)

            # get_state must be read-only: no mutating/other RPC fired.
            assert fake.open_requests == []
            assert fake.close_requests == []
            assert fake.get_tree_requests == []
            assert fake.invoke_requests == []
            assert fake.highlight_requests == []
            assert fake.scroll_requests == []
        finally:
            server.close()
            await server.wait_closed()

    async def test_get_tree_forwards_filters_and_round_trips_every_field(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        socket_path = tmp_path / "rio-dash.sock"
        fake = _FakeDash()
        server = Server([fake])
        await server.start(path=str(socket_path))
        try:
            monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
            async with DashClient() as client:
                tree = await client.get_tree(
                    interactable_only=True, root_ref_id="slot-1"
                )

            # The filter arguments must reach the server on the wire.
            assert len(fake.get_tree_requests) == 1
            wire = fake.get_tree_requests[0]
            assert wire.interactable_only is True
            assert wire.root_ref_id == "slot-1"

            assert isinstance(tree, DashTree)
            assert tree.screen_width == _SCREEN_WIDTH
            assert tree.screen_height == _SCREEN_HEIGHT
            # Element order plus every element field and every nested rect
            # field survive the round-trip.
            assert tree.elements == _EXPECTED_TREE_ELEMENTS
            assert all(isinstance(el, DashElement) for el in tree.elements)
            assert all(isinstance(el.rect, DashRect) for el in tree.elements)
        finally:
            server.close()
            await server.wait_closed()

    async def test_get_tree_defaults_send_unfiltered_request(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        socket_path = tmp_path / "rio-dash.sock"
        fake = _FakeDash()
        server = Server([fake])
        await server.start(path=str(socket_path))
        try:
            monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
            async with DashClient() as client:
                await client.get_tree()

            assert len(fake.get_tree_requests) == 1
            wire = fake.get_tree_requests[0]
            # Defaults: full tree, interactable filter off.
            assert wire.interactable_only is False
            assert wire.root_ref_id == ""
        finally:
            server.close()
            await server.wait_closed()

    async def test_invoke_forwards_ref_id_and_decodes_result(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        socket_path = tmp_path / "rio-dash.sock"
        fake = _FakeDash()
        server = Server([fake])
        await server.start(path=str(socket_path))
        try:
            monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
            async with DashClient() as client:
                result = await client.invoke("ref-42")

            assert len(fake.invoke_requests) == 1
            # ref_id must reach the server; the fake echoes it back so a
            # mismatch would prove the id never crossed the wire.
            assert fake.invoke_requests[0].ref_id == "ref-42"

            assert isinstance(result, DashActionResult)
            assert result.ok is True
            assert result.found is True
            assert result.ref_id == "ref-42"
            assert result.detail == "invoked"
        finally:
            server.close()
            await server.wait_closed()

    async def test_highlight_forwards_ref_id_and_decodes_result(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        socket_path = tmp_path / "rio-dash.sock"
        fake = _FakeDash()
        server = Server([fake])
        await server.start(path=str(socket_path))
        try:
            monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
            async with DashClient() as client:
                result = await client.highlight("ref-7")

            assert len(fake.highlight_requests) == 1
            assert fake.highlight_requests[0].ref_id == "ref-7"
            # highlight only previews: it must not fire invoke.
            assert fake.invoke_requests == []

            assert isinstance(result, DashActionResult)
            assert result.ok is True
            assert result.found is True
            assert result.ref_id == "ref-7"
            assert result.detail == "highlighted"
        finally:
            server.close()
            await server.wait_closed()

    async def test_scroll_forwards_ref_id_and_deltas_and_decodes_result(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        socket_path = tmp_path / "rio-dash.sock"
        fake = _FakeDash()
        server = Server([fake])
        await server.start(path=str(socket_path))
        try:
            monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
            async with DashClient() as client:
                result = await client.scroll("ref-9", delta_x=12.5, delta_y=-34.25)

            assert len(fake.scroll_requests) == 1
            wire = fake.scroll_requests[0]
            assert wire.ref_id == "ref-9"
            assert wire.delta_x == pytest.approx(12.5)
            assert wire.delta_y == pytest.approx(-34.25)

            assert isinstance(result, DashActionResult)
            assert result.ok is True
            assert result.found is True
            assert result.ref_id == "ref-9"
            assert result.detail == "scrolled"
        finally:
            server.close()
            await server.wait_closed()

    async def test_scroll_defaults_send_zero_deltas(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        socket_path = tmp_path / "rio-dash.sock"
        fake = _FakeDash()
        server = Server([fake])
        await server.start(path=str(socket_path))
        try:
            monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
            async with DashClient() as client:
                await client.scroll("ref-9")

            assert len(fake.scroll_requests) == 1
            wire = fake.scroll_requests[0]
            assert wire.ref_id == "ref-9"
            assert wire.delta_x == pytest.approx(0.0)
            assert wire.delta_y == pytest.approx(0.0)
        finally:
            server.close()
            await server.wait_closed()

    async def test_list_screens_round_trips_all_screen_fields_in_order(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        socket_path = tmp_path / "rio-dash.sock"
        fake = _FakeDash()
        server = Server([fake])
        await server.start(path=str(socket_path))
        try:
            monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
            async with DashClient() as client:
                screens = await client.list_screens()

            assert len(fake.list_screens_requests) == 1
            # list_screens is read-only: no mutating/other RPC fired.
            assert fake.set_screen_requests == []
            assert fake.open_requests == []
            assert fake.close_requests == []

            # The result is a list (not a tuple), preserves element order, and
            # every screen field survives the round-trip.
            assert isinstance(screens, list)
            assert screens == _EXPECTED_SCREENS
            assert all(isinstance(s, DashScreen) for s in screens)
        finally:
            server.close()
            await server.wait_closed()

    async def test_list_screens_returns_empty_list_when_no_screens(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        socket_path = tmp_path / "rio-dash.sock"

        class _EmptyScreensDash(_FakeDash):
            async def list_screens(
                self, message: DashListScreensRequest
            ) -> PbDashScreenList:
                self.list_screens_requests.append(message)
                return PbDashScreenList(screens=[])

        fake = _EmptyScreensDash()
        server = Server([fake])
        await server.start(path=str(socket_path))
        try:
            monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
            async with DashClient() as client:
                screens = await client.list_screens()

            assert screens == []
        finally:
            server.close()
            await server.wait_closed()

    async def test_set_screen_by_key_forwards_key_and_decodes_result(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        socket_path = tmp_path / "rio-dash.sock"
        fake = _FakeDash()
        server = Server([fake])
        await server.start(path=str(socket_path))
        try:
            monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
            async with DashClient() as client:
                result = await client.set_screen(key="Dash.Screens.Worlds")

            assert len(fake.set_screen_requests) == 1
            wire = fake.set_screen_requests[0]
            # Only the key was supplied; ref_id stays empty on the wire.
            assert wire.key == "Dash.Screens.Worlds"
            assert wire.ref_id == ""

            assert isinstance(result, DashActionResult)
            assert result.ok is True
            assert result.found is True
            # The fake echoes the key as the post-navigation ref_id, proving the
            # selector crossed the wire.
            assert result.ref_id == "Dash.Screens.Worlds"
            assert result.detail == "navigated"
        finally:
            server.close()
            await server.wait_closed()

    async def test_set_screen_by_ref_id_forwards_ref_id_and_decodes_result(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        socket_path = tmp_path / "rio-dash.sock"
        fake = _FakeDash()
        server = Server([fake])
        await server.start(path=str(socket_path))
        try:
            monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
            async with DashClient() as client:
                result = await client.set_screen(ref_id="screen-ref-7")

            assert len(fake.set_screen_requests) == 1
            wire = fake.set_screen_requests[0]
            assert wire.ref_id == "screen-ref-7"
            assert wire.key == ""

            assert isinstance(result, DashActionResult)
            assert result.ok is True
            assert result.found is True
            assert result.ref_id == "screen-ref-7"
        finally:
            server.close()
            await server.wait_closed()

    async def test_set_screen_sends_both_selectors_when_both_given(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        # The client does not resolve precedence locally; it forwards both
        # selectors and lets the server apply ref_id-first precedence.
        socket_path = tmp_path / "rio-dash.sock"
        fake = _FakeDash()
        server = Server([fake])
        await server.start(path=str(socket_path))
        try:
            monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
            async with DashClient() as client:
                await client.set_screen(
                    ref_id="screen-ref-9", key="Dash.Screens.Settings"
                )

            wire = fake.set_screen_requests[0]
            assert wire.ref_id == "screen-ref-9"
            assert wire.key == "Dash.Screens.Settings"
        finally:
            server.close()
            await server.wait_closed()

    async def test_set_screen_with_both_empty_raises_value_error_before_any_rpc(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        # The both-empty guard is a local contract check: it must raise before
        # any network round trip, so a connected client never reaches the server.
        socket_path = tmp_path / "rio-dash.sock"
        fake = _FakeDash()
        server = Server([fake])
        await server.start(path=str(socket_path))
        try:
            monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
            async with DashClient() as client:
                with pytest.raises(ValueError, match="ref_id or key"):
                    await client.set_screen()

            assert fake.set_screen_requests == []
        finally:
            server.close()
            await server.wait_closed()

    async def test_open_raises_when_not_connected(self):
        client = DashClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.open()

    async def test_close_raises_when_not_connected(self):
        client = DashClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.close()

    async def test_get_state_raises_when_not_connected(self):
        client = DashClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.get_state()

    async def test_get_tree_raises_when_not_connected(self):
        client = DashClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.get_tree()

    async def test_invoke_raises_when_not_connected(self):
        client = DashClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.invoke("ref-1")

    async def test_highlight_raises_when_not_connected(self):
        client = DashClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.highlight("ref-1")

    async def test_scroll_raises_when_not_connected(self):
        client = DashClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.scroll("ref-1")

    async def test_list_screens_raises_when_not_connected(self):
        client = DashClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.list_screens()

    async def test_set_screen_raises_when_not_connected(self):
        # A valid selector is supplied so the not-connected guard (not the
        # both-empty ValueError) is what surfaces.
        client = DashClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.set_screen(key="Dash.Screens.Worlds")
