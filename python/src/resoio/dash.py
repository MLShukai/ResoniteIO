"""Client for the Resonite IO ``Dash`` unary RPCs (userspace radiant dash).

The Dash service mirrors the userspace overlay opened by the dash button.
Open / close / get-state RPCs return a :class:`DashState` snapshot of the
overlay's open/animation state, while :meth:`DashClient.get_tree` enumerates
the dash UI as a :class:`DashTree` of :class:`DashElement` nodes keyed by
``ref_id``. Mutating actions (:meth:`DashClient.invoke`,
:meth:`DashClient.highlight`, :meth:`DashClient.scroll`) address an element
by ``ref_id`` and return a :class:`DashActionResult`.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from types import TracebackType
from typing import Self

from grpclib.client import Channel

from resoio._generated.resonite_io.v1 import (
    DashActionResult as _PbDashActionResult,
    DashCloseRequest,
    DashElement as _PbDashElement,
    DashGetStateRequest,
    DashGetTreeRequest,
    DashHighlightRequest,
    DashInvokeRequest,
    DashOpenRequest,
    DashRect as _PbDashRect,
    DashScrollRequest,
    DashState as _PbDashState,
    DashStub,
    DashTree as _PbDashTree,
)
from resoio._socket import resolve_socket_path

__all__ = [
    "DashActionResult",
    "DashClient",
    "DashElement",
    "DashRect",
    "DashState",
    "DashTree",
]

_logger = logging.getLogger("resoio.dash")


@dataclass(frozen=True, slots=True)
class DashRect:
    """Rectangle of a dash UI element.

    Origin is the top-left corner ``(0, 0)`` with ``x`` increasing right and
    ``y`` increasing down. When ``is_screen_space`` is ``True`` the values are
    screen pixels (the same space as :attr:`DashTree.screen_width` /
    :attr:`DashTree.screen_height`); when ``False`` they are canvas-space
    coordinates used as a fallback.
    """

    x: float
    y: float
    width: float
    height: float
    is_screen_space: bool


@dataclass(frozen=True, slots=True)
class DashState:
    """Snapshot of the dash (userspace overlay) open/close state.

    ``open_lerp`` is the open/close animation lerp in ``[0.0, 1.0]``.
    """

    is_open: bool
    open_lerp: float


@dataclass(frozen=True, slots=True)
class DashElement:
    """A single node in the dash UI tree.

    ``ref_id`` (the slot's ``ReferenceID``) is the language-independent key
    that :meth:`DashClient.invoke` / :meth:`DashClient.highlight` /
    :meth:`DashClient.scroll` address. ``locale_key`` is the locale string key
    when present (empty for already-localised labels); ``label`` is the
    human-readable, localised text. ``parent_ref_id`` links the node to its
    parent (empty at the root) and ``depth`` is the tree depth (root = ``0``).
    """

    ref_id: str
    type: str
    slot_name: str
    locale_key: str
    label: str
    enabled: bool
    interactable: bool
    rect: DashRect
    parent_ref_id: str
    depth: int


@dataclass(frozen=True, slots=True)
class DashTree:
    """Snapshot of the dash UI tree.

    ``elements`` are enumerated in depth-first order and is empty when the
    dash is closed. ``screen_width`` / ``screen_height`` are the current
    window resolution (pixels) that screen-space rects are expressed in.
    """

    elements: tuple[DashElement, ...]
    screen_width: int
    screen_height: int


@dataclass(frozen=True, slots=True)
class DashActionResult:
    """Result of a mutating dash action.

    ``found`` indicates whether the requested ``ref_id`` resolved to an
    element (``ok`` is always ``False`` when ``found`` is ``False``).
    ``ref_id`` echoes the resolved target and ``detail`` carries the reason
    when the action could not be applied (e.g. locked / non-interactable).
    """

    ok: bool
    found: bool
    ref_id: str
    detail: str


def _rect_from_proto(pb: _PbDashRect | None) -> DashRect:
    if pb is None:
        return DashRect(
            x=0.0,
            y=0.0,
            width=0.0,
            height=0.0,
            is_screen_space=False,
        )
    return DashRect(
        x=pb.x,
        y=pb.y,
        width=pb.width,
        height=pb.height,
        is_screen_space=pb.is_screen_space,
    )


def _state_from_proto(pb: _PbDashState) -> DashState:
    return DashState(
        is_open=pb.is_open,
        open_lerp=pb.open_lerp,
    )


def _element_from_proto(pb: _PbDashElement) -> DashElement:
    return DashElement(
        ref_id=pb.ref_id,
        type=pb.type,
        slot_name=pb.slot_name,
        locale_key=pb.locale_key,
        label=pb.label,
        enabled=pb.enabled,
        interactable=pb.interactable,
        rect=_rect_from_proto(pb.rect),
        parent_ref_id=pb.parent_ref_id,
        depth=pb.depth,
    )


def _tree_from_proto(pb: _PbDashTree) -> DashTree:
    return DashTree(
        elements=tuple(_element_from_proto(element) for element in pb.elements),
        screen_width=pb.screen_width,
        screen_height=pb.screen_height,
    )


def _result_from_proto(pb: _PbDashActionResult) -> DashActionResult:
    return DashActionResult(
        ok=pb.ok,
        found=pb.found,
        ref_id=pb.ref_id,
        detail=pb.detail,
    )


class DashClient:
    """Async client for the Resonite IO ``Dash`` service over a UDS.

    Use as an async context manager so the gRPC channel is closed
    deterministically. Socket resolution mirrors
    :class:`resoio.SessionClient`.
    """

    def __init__(self, socket_path: str | None = None) -> None:
        self._explicit_path: str | None = socket_path
        self._channel: Channel | None = None
        self._stub: DashStub | None = None
        self._resolved_path: str | None = None

    @property
    def socket_path(self) -> str | None:
        """Resolved UDS path, or ``None`` before ``__aenter__``."""
        return self._resolved_path

    async def __aenter__(self) -> Self:
        path = self._explicit_path or resolve_socket_path()
        _logger.debug("Opening Dash channel on UDS path: %s", path)
        channel = Channel(path=path)
        self._channel = channel
        self._stub = DashStub(channel)
        self._resolved_path = path
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        channel = self._channel
        self._channel = None
        self._stub = None
        self._resolved_path = None
        if channel is not None:
            channel.close()

    async def _dispatch[T](
        self,
        rpc: Callable[[DashStub], Awaitable[T]],
    ) -> T:
        """Run a unary RPC against the connected stub and return the result.

        Centralises the not-connected guard shared by every RPC. ``rpc``
        selects the stub method and supplies its request; each public method
        decodes the returned proto into its dataclass. gRPC failures surface
        as :class:`grpclib.exceptions.GRPCError`.
        """
        stub = self._stub
        if stub is None:
            raise RuntimeError(
                "DashClient is not connected. Use `async with DashClient(): ...`."
            )
        return await rpc(stub)

    async def open(self) -> DashState:
        """Open the dash overlay and return the resulting state.

        Calling when already open is a no-op that returns the current state.
        gRPC failures surface as :class:`grpclib.exceptions.GRPCError`.
        """
        request = DashOpenRequest()
        return _state_from_proto(await self._dispatch(lambda stub: stub.open(request)))

    async def close(self) -> DashState:
        """Close the dash overlay and return the resulting state."""
        request = DashCloseRequest()
        return _state_from_proto(await self._dispatch(lambda stub: stub.close(request)))

    async def get_state(self) -> DashState:
        """Return the current dash state without modifying it."""
        request = DashGetStateRequest()
        return _state_from_proto(
            await self._dispatch(lambda stub: stub.get_state(request))
        )

    async def get_tree(
        self, *, interactable_only: bool = False, root_ref_id: str = ""
    ) -> DashTree:
        """Enumerate the dash UI tree as a :class:`DashTree`.

        When ``interactable_only`` is ``True`` only interactable elements are
        returned. ``root_ref_id`` restricts the result to the subtree rooted
        at that ``ref_id``; an empty string enumerates the whole dash. The
        tree is empty when the dash is closed.

        gRPC failures surface as :class:`grpclib.exceptions.GRPCError`.
        """
        request = DashGetTreeRequest(
            interactable_only=interactable_only,
            root_ref_id=root_ref_id,
        )
        return _tree_from_proto(
            await self._dispatch(lambda stub: stub.get_tree(request))
        )

    async def invoke(self, ref_id: str) -> DashActionResult:
        """Press the element identified by ``ref_id``.

        Fires the element's interaction (e.g. a button press), which may
        mutate world or dash state. The returned result reports whether the
        ``ref_id`` resolved and whether the action was applied.

        gRPC failures surface as :class:`grpclib.exceptions.GRPCError`.
        """
        request = DashInvokeRequest(ref_id=ref_id)
        return _result_from_proto(
            await self._dispatch(lambda stub: stub.invoke(request))
        )

    async def highlight(self, ref_id: str) -> DashActionResult:
        """Highlight (preview) the element identified by ``ref_id``.

        Highlight only moves the visual selection; it does not trigger the
        element. Use :meth:`invoke` to act on it.

        gRPC failures surface as :class:`grpclib.exceptions.GRPCError`.
        """
        request = DashHighlightRequest(ref_id=ref_id)
        return _result_from_proto(
            await self._dispatch(lambda stub: stub.highlight(request))
        )

    async def scroll(
        self, ref_id: str, *, delta_x: float = 0.0, delta_y: float = 0.0
    ) -> DashActionResult:
        """Scroll the element identified by ``ref_id`` by ``(delta_x,
        delta_y)``.

        The result reports whether the ``ref_id`` resolved and whether the
        scroll was applied.

        gRPC failures surface as :class:`grpclib.exceptions.GRPCError`.
        """
        request = DashScrollRequest(ref_id=ref_id, delta_x=delta_x, delta_y=delta_y)
        return _result_from_proto(
            await self._dispatch(lambda stub: stub.scroll(request))
        )
