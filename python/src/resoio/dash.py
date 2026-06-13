"""Client for the Resonite IO ``Dash`` modality (Python -> Resonite).

Unary RPCs driving the userspace radiant dash overlay (the ``Esc`` menu).

The Dash is structured as a **bottom tab bar** (Home / Worlds / Contacts /
Inventory / ...), and within the current tab a set of **interactable
controls** (pressable ``Button`` s and scrollable ``ScrollRect`` s). The
client mirrors that: :meth:`DashClient.list_tabs` enumerates the tab bar and
:meth:`DashClient.set_tab` switches the current tab, while
:meth:`DashClient.list_controls` enumerates the current tab's controls and
:meth:`DashClient.invoke` / :meth:`DashClient.scroll` /
:meth:`DashClient.highlight` act on one by ``ref_id``.

On the wire selection is always by ``ref_id`` (the engine ``ReferenceID``),
which is the stable, language-independent handle. The ``*_by_label`` helpers
add client-side ergonomics: they fetch the relevant list and resolve a
human-friendly query (label / ``locale_key`` / ``name`` / ``ref_id``) to a
single ``ref_id`` via :func:`_resolve_one`, raising :class:`DashNoMatchError`
or :class:`DashAmbiguousMatchError` when the query is unresolvable.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import override

from grpclib.client import Channel

from resoio._client import _BaseClient
from resoio._generated.resonite_io.v1 import (
    DashActionResult as _PbDashActionResult,
    DashCloseRequest,
    DashControl as _PbDashControl,
    DashGetStateRequest,
    DashHighlightRequest,
    DashInvokeRequest,
    DashListControlsRequest,
    DashListTabsRequest,
    DashOpenRequest,
    DashScrollRequest,
    DashSetTabRequest,
    DashState as _PbDashState,
    DashStub,
    DashTab as _PbDashTab,
)

__all__ = [
    "DashActionResult",
    "DashAmbiguousMatchError",
    "DashClient",
    "DashControl",
    "DashNoMatchError",
    "DashState",
    "DashTab",
]

_logger = logging.getLogger("resoio.dash")


@dataclass(frozen=True, slots=True)
class DashState:
    """Snapshot of the dash (userspace overlay) open/close state.

    ``open_lerp`` is the open/close animation lerp in ``[0.0, 1.0]``.
    """

    is_open: bool
    open_lerp: float


@dataclass(frozen=True, slots=True)
class DashTab:
    """A single tab in the dash's bottom tab bar.

    ``ref_id`` (the tab slot's engine ``ReferenceID``) and ``locale_key``
    (the tab label's ``LocaleStringDriver`` key, e.g. ``Dash.Screens.Worlds``)
    are the language-independent keys that :meth:`DashClient.set_tab`
    addresses; ``name`` is the slot name (e.g. ``Worlds``) and ``label`` is
    the localized display text. ``is_current`` is ``True`` for the tab
    currently shown; ``enabled`` reports whether the tab is navigable (e.g.
    ``Contacts`` is ``False`` while logged out).
    """

    ref_id: str
    locale_key: str
    name: str
    label: str
    is_current: bool
    enabled: bool


@dataclass(frozen=True, slots=True)
class DashControl:
    """A single interactable control within the current tab.

    ``control_type`` is ``"button"`` (pressable) or ``"scroll"`` (scrollable).
    ``ref_id`` (the slot's engine ``ReferenceID``) is the stable key that
    :meth:`DashClient.invoke` / :meth:`DashClient.scroll` /
    :meth:`DashClient.highlight` address. ``label`` is the human-readable
    text (may be empty for icon-only buttons) and ``locale_key`` is the
    language-independent key when present. ``parent_ref_id`` links the
    control to its nearest enumerated control ancestor (empty at the top) and
    ``depth`` is that light hierarchy's depth (top = ``0``).
    """

    ref_id: str
    control_type: str
    label: str
    locale_key: str
    enabled: bool
    parent_ref_id: str
    depth: int


@dataclass(frozen=True, slots=True)
class DashActionResult:
    """Result of a mutating dash action.

    ``found`` indicates whether the requested ``ref_id`` resolved to a tab or
    control (``ok`` is always ``False`` when ``found`` is ``False``).
    ``ref_id`` echoes the resolved target and ``detail`` carries the reason
    when the action could not be applied (e.g. type mismatch, disabled).
    """

    ok: bool
    found: bool
    ref_id: str
    detail: str


class DashNoMatchError(ValueError):
    """A label / index query did not match any tab or control."""


class DashAmbiguousMatchError(ValueError):
    """A label query matched more than one tab or control.

    The message lists the matching candidates so the caller can narrow the
    query (or use an exact ``ref_id``).
    """


def _resolve_one[T](
    items: Sequence[T],
    query: str,
    keys: Callable[[T], Iterable[str]],
) -> T:
    """Resolve ``query`` to exactly one item in ``items`` by its keys.

    ``keys`` extracts the comparable strings for an item (e.g. its
    ``ref_id``, ``locale_key``, ``name``, ``label``). Matching is tried in
    order of decreasing strictness, returning as soon as a stage is decisive:

    1. **Exact** (case-sensitive) match on any key equal to ``query`` -- this
       is what makes a full ``ref_id`` an unambiguous handle.
    2. **Case-insensitive exact** match (``casefold``) on any key; returned
       only when exactly one item matches.
    3. **Case-insensitive substring** match on any key; returned only when
       exactly one item matches.

    Raises :class:`DashNoMatchError` when nothing matches anywhere, or
    :class:`DashAmbiguousMatchError` (listing candidates) when the substring
    stage matches more than one item.
    """
    for item in items:
        if any(key == query for key in keys(item)):
            return item

    folded = query.casefold()

    exact_ci = [
        item for item in items if any(k.casefold() == folded for k in keys(item))
    ]
    if len(exact_ci) == 1:
        return exact_ci[0]

    substring = [
        item for item in items if any(folded in k.casefold() for k in keys(item))
    ]
    if len(substring) == 1:
        return substring[0]
    if not substring:
        raise DashNoMatchError(
            f"no match for {query!r}; candidates: {_candidate_hint(items, keys)}"
        )
    raise DashAmbiguousMatchError(
        f"{query!r} matched {len(substring)} items: {_candidate_hint(substring, keys)}"
    )


def _candidate_hint[T](
    items: Sequence[T],
    keys: Callable[[T], Iterable[str]],
) -> str:
    """Render a short ``key | key`` hint listing each item's first key."""
    return ", ".join(repr(next((k for k in keys(item) if k), "")) for item in items)


def _tab_keys(tab: DashTab) -> tuple[str, str, str, str]:
    return (tab.ref_id, tab.locale_key, tab.name, tab.label)


def _control_keys(control: DashControl) -> tuple[str, str, str]:
    return (control.ref_id, control.locale_key, control.label)


def _state_from_proto(pb: _PbDashState) -> DashState:
    return DashState(
        is_open=pb.is_open,
        open_lerp=pb.open_lerp,
    )


def _tab_from_proto(pb: _PbDashTab) -> DashTab:
    return DashTab(
        ref_id=pb.ref_id,
        locale_key=pb.locale_key,
        name=pb.name,
        label=pb.label,
        is_current=pb.is_current,
        enabled=pb.enabled,
    )


def _control_from_proto(pb: _PbDashControl) -> DashControl:
    return DashControl(
        ref_id=pb.ref_id,
        control_type=pb.control_type,
        label=pb.label,
        locale_key=pb.locale_key,
        enabled=pb.enabled,
        parent_ref_id=pb.parent_ref_id,
        depth=pb.depth,
    )


def _result_from_proto(pb: _PbDashActionResult) -> DashActionResult:
    return DashActionResult(
        ok=pb.ok,
        found=pb.found,
        ref_id=pb.ref_id,
        detail=pb.detail,
    )


class DashClient(_BaseClient[DashStub]):
    """Async client for the Resonite IO ``Dash`` service over a UDS.

    Use as an async context manager so the gRPC channel is closed
    deterministically. Socket resolution mirrors
    :class:`resoio.ConnectionClient`.
    """

    _logger = _logger
    _log_label = "Dash"

    @override
    def _make_stub(self, channel: Channel) -> DashStub:
        return DashStub(channel)

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
        return await rpc(self._require_stub())

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

    async def list_tabs(self) -> list[DashTab]:
        """Enumerate the dash's bottom tab bar as a list of :class:`DashTab`.

        Tabs can be enumerated even while the dash is closed. Each tab
        carries the language-independent ``ref_id`` / ``locale_key`` /
        ``name`` that :meth:`set_tab` and :meth:`find_tab` address.

        gRPC failures surface as :class:`grpclib.exceptions.GRPCError`.
        """
        request = DashListTabsRequest()
        tab_list = await self._dispatch(lambda stub: stub.list_tabs(request))
        return [_tab_from_proto(tab) for tab in tab_list.tabs]

    async def set_tab(
        self, *, ref_id: str = "", locale_key: str = ""
    ) -> DashActionResult:
        """Switch the current tab, selecting by ``ref_id`` or ``locale_key``.

        ``ref_id`` takes precedence: when non-empty it selects the tab by its
        exact engine ``ReferenceID``; otherwise the tab is matched by its
        language-independent ``locale_key`` (e.g. ``Dash.Screens.Worlds``).
        Passing neither raises :class:`ValueError` before any network round
        trip.

        An unresolved ``ref_id`` / ``locale_key`` is a soft failure
        (``found == ok == False``), not an exception. After switching, the
        new tab's controls are read with :meth:`list_controls`.

        gRPC failures surface as :class:`grpclib.exceptions.GRPCError`.
        """
        if not ref_id and not locale_key:
            raise ValueError("set_tab requires ref_id or locale_key")
        request = DashSetTabRequest(ref_id=ref_id, locale_key=locale_key)
        return _result_from_proto(
            await self._dispatch(lambda stub: stub.set_tab(request))
        )

    async def list_controls(
        self, *, include_disabled: bool = False
    ) -> list[DashControl]:
        """Enumerate the **current** tab's controls in reading order.

        Returns the pressable / scrollable controls of whichever tab is
        current; switch tabs with :meth:`set_tab` first to read another tab.
        When ``include_disabled`` is ``True`` disabled controls are included
        too (the default lists only enabled ones). The list is empty when the
        dash is closed.

        gRPC failures surface as :class:`grpclib.exceptions.GRPCError`.
        """
        request = DashListControlsRequest(include_disabled=include_disabled)
        control_list = await self._dispatch(lambda stub: stub.list_controls(request))
        return [_control_from_proto(control) for control in control_list.controls]

    async def invoke(self, ref_id: str) -> DashActionResult:
        """Press the control identified by ``ref_id``.

        Fires the control's interaction (a button press), which may mutate
        world or dash state. The returned result reports whether the
        ``ref_id`` resolved and whether the action was applied.

        gRPC failures surface as :class:`grpclib.exceptions.GRPCError`.
        """
        request = DashInvokeRequest(ref_id=ref_id)
        return _result_from_proto(
            await self._dispatch(lambda stub: stub.invoke(request))
        )

    async def scroll(
        self, ref_id: str, *, delta_x: float = 0.0, delta_y: float = 0.0
    ) -> DashActionResult:
        """Scroll the control identified by ``ref_id`` by ``(delta_x,
        delta_y)``.

        ``delta_x`` / ``delta_y`` are added to the ``ScrollRect`` 's
        normalized position (``[0, 1]`` space). The result reports whether the
        ``ref_id`` resolved and whether the scroll was applied.

        gRPC failures surface as :class:`grpclib.exceptions.GRPCError`.
        """
        request = DashScrollRequest(ref_id=ref_id, delta_x=delta_x, delta_y=delta_y)
        return _result_from_proto(
            await self._dispatch(lambda stub: stub.scroll(request))
        )

    async def highlight(self, ref_id: str) -> DashActionResult:
        """Hover-highlight the control identified by ``ref_id``.

        Highlight only moves the visual hover; it does not press the control.
        A control that does not support hover (e.g. a ``ScrollRect``) is a
        soft rejection (``found == True``, ``ok == False``). Use
        :meth:`invoke` to act on a control.

        gRPC failures surface as :class:`grpclib.exceptions.GRPCError`.
        """
        request = DashHighlightRequest(ref_id=ref_id)
        return _result_from_proto(
            await self._dispatch(lambda stub: stub.highlight(request))
        )

    async def find_tab(self, query: str) -> DashTab:
        """Resolve ``query`` to a single :class:`DashTab` (client-side).

        ``query`` matches a tab's ``ref_id`` / ``locale_key`` / ``name`` /
        ``label`` via :func:`_resolve_one` (exact, then case-insensitive
        exact, then unique substring). Raises :class:`DashNoMatchError` or
        :class:`DashAmbiguousMatchError` when the query is unresolvable.
        """
        return _resolve_one(await self.list_tabs(), query, _tab_keys)

    async def set_tab_by_label(self, query: str) -> DashActionResult:
        """Resolve ``query`` to a tab and switch to it by its ``ref_id``.

        Convenience over :meth:`find_tab` + :meth:`set_tab`; the wire request
        always carries the resolved ``ref_id``. Resolution errors surface as
        :class:`DashNoMatchError` / :class:`DashAmbiguousMatchError`.
        """
        tab = await self.find_tab(query)
        return await self.set_tab(ref_id=tab.ref_id)

    async def find_control(self, query: str) -> DashControl:
        """Resolve ``query`` to a single control in the current tab.

        ``query`` matches a control's ``ref_id`` / ``locale_key`` / ``label``
        via :func:`_resolve_one`. Raises :class:`DashNoMatchError` or
        :class:`DashAmbiguousMatchError` when the query is unresolvable.
        """
        return _resolve_one(await self.list_controls(), query, _control_keys)

    async def invoke_by_label(self, query: str) -> DashActionResult:
        """Resolve ``query`` to a control and :meth:`invoke` it by
        ``ref_id``."""
        control = await self.find_control(query)
        return await self.invoke(control.ref_id)

    async def scroll_by_label(
        self, query: str, *, delta_x: float = 0.0, delta_y: float = 0.0
    ) -> DashActionResult:
        """Resolve ``query`` to a control and :meth:`scroll` it by
        ``ref_id``."""
        control = await self.find_control(query)
        return await self.scroll(control.ref_id, delta_x=delta_x, delta_y=delta_y)

    async def highlight_by_label(self, query: str) -> DashActionResult:
        """Resolve ``query`` to a control and :meth:`highlight` it by
        ``ref_id``."""
        control = await self.find_control(query)
        return await self.highlight(control.ref_id)
