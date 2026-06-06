"""Integration-real tests for :class:`resoio.context_menu.ContextMenuClient`.

A real ``grpclib.server.Server`` hosting an inline fake
:class:`ContextMenuBase` handler is bound to a real UDS under ``tmp_path``
and driven by the real ``ContextMenuClient`` over the wire (no mocking of
grpclib/betterproto2 internals). This verifies that each of the five unary
RPCs reaches the server with the correct ``hand`` enum (and ``index`` for
highlight/invoke) and that the returned ``ContextMenuState`` / ``ContextMenuItem``
dataclasses round-trip every field — including color-tuple ordering, item
order, and ``highlighted_index``.
"""

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

import pytest

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
from resoio.context_menu import (
    ContextMenuClient,
    ContextMenuItem,
    ContextMenuState,
)

if TYPE_CHECKING:
    from grpclib._typing import IServable

UdsServer = Callable[["IServable"], Awaitable[str]]

# A two-item menu used by the round-trip tests. The two items differ in
# every field (enabled / has_icon / color components) so a swapped or
# dropped field would change the assertion result.
_FIRST_ITEM = PbContextMenuItem(
    index=0,
    label="Move",
    enabled=True,
    has_icon=True,
    color_r=0.1,
    color_g=0.2,
    color_b=0.3,
    color_a=0.4,
)
_SECOND_ITEM = PbContextMenuItem(
    index=1,
    label="Tools",
    enabled=False,
    has_icon=False,
    color_r=0.9,
    color_g=0.8,
    color_b=0.7,
    color_a=0.6,
)


def _two_item_state(*, is_open: bool, highlighted_index: int) -> PbContextMenuState:
    return PbContextMenuState(
        is_open=is_open,
        items=[_FIRST_ITEM, _SECOND_ITEM],
        highlighted_index=highlighted_index,
    )


class _FakeContextMenu(ContextMenuBase):
    """In-process fake that records each request and returns a fixed state.

    Each RPC stores the request it received so a test can assert the
    ``hand`` enum (and ``index`` for highlight/invoke) that reached the
    server, then returns a deterministic ``ContextMenuState`` so the
    client-side decoding can be checked end-to-end.
    """

    def __init__(self) -> None:
        self.open_requests: list[ContextMenuOpenRequest] = []
        self.close_requests: list[ContextMenuCloseRequest] = []
        self.get_state_requests: list[ContextMenuGetStateRequest] = []
        self.highlight_requests: list[ContextMenuHighlightRequest] = []
        self.invoke_requests: list[ContextMenuInvokeRequest] = []

    async def open(self, message: ContextMenuOpenRequest) -> PbContextMenuState:
        self.open_requests.append(message)
        return _two_item_state(is_open=True, highlighted_index=-1)

    async def close(self, message: ContextMenuCloseRequest) -> PbContextMenuState:
        self.close_requests.append(message)
        return PbContextMenuState(is_open=False, items=[], highlighted_index=-1)

    async def get_state(
        self, message: ContextMenuGetStateRequest
    ) -> PbContextMenuState:
        self.get_state_requests.append(message)
        return _two_item_state(is_open=True, highlighted_index=1)

    async def highlight(
        self, message: ContextMenuHighlightRequest
    ) -> PbContextMenuState:
        self.highlight_requests.append(message)
        return _two_item_state(is_open=True, highlighted_index=message.index)

    async def invoke(self, message: ContextMenuInvokeRequest) -> PbContextMenuState:
        self.invoke_requests.append(message)
        return _two_item_state(is_open=True, highlighted_index=message.index)


_EXPECTED_OPEN_ITEMS = (
    ContextMenuItem(
        index=0,
        label="Move",
        enabled=True,
        has_icon=True,
        color=(
            pytest.approx(0.1),
            pytest.approx(0.2),
            pytest.approx(0.3),
            pytest.approx(0.4),
        ),
    ),
    ContextMenuItem(
        index=1,
        label="Tools",
        enabled=False,
        has_icon=False,
        color=(
            pytest.approx(0.9),
            pytest.approx(0.8),
            pytest.approx(0.7),
            pytest.approx(0.6),
        ),
    ),
)


class TestContextMenuClient:
    async def test_open_sends_primary_hand_and_decodes_state(
        self, uds_server: UdsServer
    ):
        fake = _FakeContextMenu()
        socket_path = await uds_server(fake)
        async with ContextMenuClient() as client:
            assert client.socket_path == socket_path
            state = await client.open()

        # Default hand is "primary" -> PRIMARY enum on the wire.
        assert len(fake.open_requests) == 1
        assert fake.open_requests[0].hand == ContextMenuHand.PRIMARY

        assert isinstance(state, ContextMenuState)
        assert state.is_open is True
        assert state.highlighted_index == -1
        # Item order and every field (incl. color tuple ordering) survive
        # the round-trip.
        assert state.items == _EXPECTED_OPEN_ITEMS
        assert all(isinstance(item, ContextMenuItem) for item in state.items)

    async def test_close_sends_hand_and_returns_closed_state(
        self, uds_server: UdsServer
    ):
        fake = _FakeContextMenu()
        await uds_server(fake)
        async with ContextMenuClient() as client:
            state = await client.close(hand="left")

        assert len(fake.close_requests) == 1
        assert fake.close_requests[0].hand == ContextMenuHand.LEFT

        assert state == ContextMenuState(is_open=False, items=(), highlighted_index=-1)

    async def test_get_state_sends_hand_and_decodes_highlighted_index(
        self, uds_server: UdsServer
    ):
        fake = _FakeContextMenu()
        await uds_server(fake)
        async with ContextMenuClient() as client:
            state = await client.get_state(hand="right")

        assert len(fake.get_state_requests) == 1
        assert fake.get_state_requests[0].hand == ContextMenuHand.RIGHT

        assert state.is_open is True
        assert state.highlighted_index == 1
        assert state.items == _EXPECTED_OPEN_ITEMS
        # `get_state` must be read-only: no mutating RPC was issued.
        assert fake.open_requests == []
        assert fake.highlight_requests == []
        assert fake.invoke_requests == []

    async def test_highlight_forwards_index_and_hand(self, uds_server: UdsServer):
        fake = _FakeContextMenu()
        await uds_server(fake)
        async with ContextMenuClient() as client:
            state = await client.highlight(1, hand="left")

        assert len(fake.highlight_requests) == 1
        wire = fake.highlight_requests[0]
        assert wire.index == 1
        assert wire.hand == ContextMenuHand.LEFT

        # Fake echoes the requested index into highlighted_index, so a
        # mismatch would prove the index never reached the server.
        assert state.highlighted_index == 1
        assert state.items == _EXPECTED_OPEN_ITEMS

    async def test_invoke_forwards_index_and_default_hand(self, uds_server: UdsServer):
        fake = _FakeContextMenu()
        await uds_server(fake)
        async with ContextMenuClient() as client:
            state = await client.invoke(0)

        assert len(fake.invoke_requests) == 1
        wire = fake.invoke_requests[0]
        assert wire.index == 0
        # No explicit hand -> default "primary" -> PRIMARY on the wire.
        assert wire.hand == ContextMenuHand.PRIMARY

        assert state.highlighted_index == 0
        assert state.items == _EXPECTED_OPEN_ITEMS

    async def test_open_raises_when_not_connected(self):
        client = ContextMenuClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.open()

    async def test_close_raises_when_not_connected(self):
        client = ContextMenuClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.close()

    async def test_get_state_raises_when_not_connected(self):
        client = ContextMenuClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.get_state()

    async def test_highlight_raises_when_not_connected(self):
        client = ContextMenuClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.highlight(0)

    async def test_invoke_raises_when_not_connected(self):
        client = ContextMenuClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.invoke(0)
