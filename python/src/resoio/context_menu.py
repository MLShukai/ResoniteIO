"""Client for the Resonite IO ``ContextMenu`` unary RPCs (radial menu).

The ContextMenu service mirrors the desktop ``T`` key radial menu. Each
RPC is a one-shot unary request/response that operates on a chosen hand
(``primary`` / ``left`` / ``right``) and returns the resulting
:class:`ContextMenuState` snapshot.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal, override

from grpclib.client import Channel

from resoio._client import _BaseClient
from resoio._generated.resonite_io.v1 import (
    ContextMenuCloseRequest,
    ContextMenuGetStateRequest,
    ContextMenuHand,
    ContextMenuHighlightRequest,
    ContextMenuInvokeRequest,
    ContextMenuItem as _PbContextMenuItem,
    ContextMenuOpenRequest,
    ContextMenuState as _PbContextMenuState,
    ContextMenuStub,
)

__all__ = [
    "ContextMenuClient",
    "ContextMenuItem",
    "ContextMenuState",
]

_logger = logging.getLogger("resoio.context_menu")

ContextMenuHandArg = Literal["primary", "left", "right"]


@dataclass(frozen=True, slots=True)
class ContextMenuItem:
    """A single entry in the radial context menu.

    ``index`` is the enumeration order (ArcLayout child order) and is
    what :meth:`ContextMenuClient.highlight` / :meth:`ContextMenuClient.invoke`
    address. ``color`` is the RGBA tuple ``(r, g, b, a)``.
    """

    index: int
    label: str
    enabled: bool
    has_icon: bool
    color: tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class ContextMenuState:
    """Snapshot of the current context menu state.

    ``items`` is empty when the menu is closed. ``highlighted_index`` is
    ``-1`` when no item is highlighted.
    """

    is_open: bool
    items: tuple[ContextMenuItem, ...]
    highlighted_index: int


def _hand_to_proto(hand: ContextMenuHandArg) -> ContextMenuHand:
    if hand == "primary":
        return ContextMenuHand.PRIMARY
    if hand == "left":
        return ContextMenuHand.LEFT
    return ContextMenuHand.RIGHT


def _item_from_proto(pb: _PbContextMenuItem) -> ContextMenuItem:
    return ContextMenuItem(
        index=pb.index,
        label=pb.label,
        enabled=pb.enabled,
        has_icon=pb.has_icon,
        color=(pb.color_r, pb.color_g, pb.color_b, pb.color_a),
    )


def _state_from_proto(pb: _PbContextMenuState) -> ContextMenuState:
    return ContextMenuState(
        is_open=pb.is_open,
        items=tuple(_item_from_proto(item) for item in pb.items),
        highlighted_index=pb.highlighted_index,
    )


class ContextMenuClient(_BaseClient[ContextMenuStub]):
    """Async client for the Resonite IO ``ContextMenu`` service over a UDS.

    Use as an async context manager so the gRPC channel is closed
    deterministically. Socket resolution mirrors
    :class:`resoio.SessionClient`.
    """

    _logger = _logger
    _log_label = "ContextMenu"

    @override
    def _make_stub(self, channel: Channel) -> ContextMenuStub:
        return ContextMenuStub(channel)

    async def _dispatch(
        self,
        rpc: Callable[[ContextMenuStub], Awaitable[_PbContextMenuState]],
    ) -> ContextMenuState:
        """Run a unary RPC against the connected stub and decode the result.

        Centralises the not-connected guard and proto -> dataclass decode
        shared by every RPC. ``rpc`` selects the stub method and supplies
        its request. gRPC failures surface as
        :class:`grpclib.exceptions.GRPCError`.
        """
        return _state_from_proto(await rpc(self._require_stub()))

    async def open(self, *, hand: ContextMenuHandArg = "primary") -> ContextMenuState:
        """Open the radial context menu and return the resulting state.

        Waits server-side until the menu has finished opening. Calling
        when already open is a no-op that returns the current state.
        gRPC failures surface as :class:`grpclib.exceptions.GRPCError`.
        """
        request = ContextMenuOpenRequest(hand=_hand_to_proto(hand))
        return await self._dispatch(lambda stub: stub.open(request))

    async def close(self, *, hand: ContextMenuHandArg = "primary") -> ContextMenuState:
        """Close the radial context menu and return the resulting state."""
        request = ContextMenuCloseRequest(hand=_hand_to_proto(hand))
        return await self._dispatch(lambda stub: stub.close(request))

    async def get_state(
        self, *, hand: ContextMenuHandArg = "primary"
    ) -> ContextMenuState:
        """Return the current menu state without modifying it."""
        request = ContextMenuGetStateRequest(hand=_hand_to_proto(hand))
        return await self._dispatch(lambda stub: stub.get_state(request))

    async def highlight(
        self, index: int, *, hand: ContextMenuHandArg = "primary"
    ) -> ContextMenuState:
        """Select (preview) the item at ``index`` without triggering it.

        Highlight only moves the visual selection; it never presses the
        item, so it has no side effect on the world or active tool. Use
        :meth:`invoke` to actually act on an item.

        gRPC failures (e.g. out-of-range index, menu not open) surface as
        :class:`grpclib.exceptions.GRPCError`.
        """
        request = ContextMenuHighlightRequest(hand=_hand_to_proto(hand), index=index)
        return await self._dispatch(lambda stub: stub.highlight(request))

    async def invoke(
        self, index: int, *, hand: ContextMenuHandArg = "primary"
    ) -> ContextMenuState:
        """Press the item at ``index`` and return the resulting state.

        Unlike :meth:`highlight`, this fires the item's button action, so
        it may open a submenu, switch the active tool, or otherwise mutate
        world state. The returned state reflects the menu *after* the press
        (e.g. a submenu's items, or an empty menu if the action closed it).

        gRPC failures (e.g. out-of-range index, menu not open) surface as
        :class:`grpclib.exceptions.GRPCError`.
        """
        request = ContextMenuInvokeRequest(hand=_hand_to_proto(hand), index=index)
        return await self._dispatch(lambda stub: stub.invoke(request))
