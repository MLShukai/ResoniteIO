"""Integration-real tests for :class:`resoio.dash.DashClient`.

A real ``grpclib.server.Server`` hosting an inline fake :class:`DashBase`
handler is bound to a real UDS under ``tmp_path`` (via the shared
``uds_server`` fixture) and driven by the real ``DashClient`` over the
wire (no mocking of grpclib / betterproto2 internals, per
testing-strategy). This exercises the tab/control contract end to end:
each of the nine unary RPCs reaches the server with the correct request
fields, and the returned ``DashState`` / ``DashTab`` / ``DashControl`` /
``DashActionResult`` dataclasses decode every wire field.

The fakes deliberately give every field a *distinct* value (and use both
``True`` and ``False`` for booleans, ``button`` and ``scroll`` for
``control_type``, ``locale_key`` set on one row and empty on another, and
non-trivial ``parent_ref_id`` / ``depth``) so that a swapped, dropped, or
mis-mapped field would change an assertion result. ``float`` fields are
compared with :func:`pytest.approx` because the proto ``float`` type is
float32, so an exact ``==`` would be brittle across the serialization
round trip.

The module-level resolver (``_resolve_one``) and the ``*_by_label``
helpers codify the client-side selection contract: exact ``ref_id`` wins,
then casefold-exact, then a unique casefold substring; zero matches raise
:class:`DashNoMatchError` and an ambiguous substring raises
:class:`DashAmbiguousMatchError`. The by-label helpers must always put the
*resolved full* ``ref_id`` on the wire.
"""

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

import pytest

from resoio._generated.resonite_io.v1 import (
    DashActionResult as PbDashActionResult,
    DashBase,
    DashCloseRequest,
    DashControl as PbDashControl,
    DashControlList as PbDashControlList,
    DashGetStateRequest,
    DashHighlightRequest,
    DashInvokeRequest,
    DashListControlsRequest,
    DashListTabsRequest,
    DashOpenRequest,
    DashScrollRequest,
    DashSetTabRequest,
    DashState as PbDashState,
    DashTab as PbDashTab,
    DashTabList as PbDashTabList,
)
from resoio.dash import (
    DashActionResult,
    DashAmbiguousMatchError,
    DashClient,
    DashControl,
    DashNoMatchError,
    DashState,
    DashTab,
    _resolve_one,
    _tab_keys,
)

if TYPE_CHECKING:
    from grpclib._typing import IServable

UdsServer = Callable[["IServable"], Awaitable[str]]


# --- Wire fixtures: a two-tab bar and a two-control listing -----------------
#
# Every scalar field on both tabs holds a different value, and the two tabs
# use opposite ``is_current`` / ``enabled`` flags, so any field swap/drop or a
# reordered list would surface as a mismatch.
_WORLDS_TAB = PbDashTab(
    ref_id="tab-ref-1",
    locale_key="Dash.Screens.Worlds",
    name="Worlds",
    label="Worlds",
    is_current=True,
    enabled=True,
)
_CONTACTS_TAB = PbDashTab(
    ref_id="tab-ref-2",
    locale_key="Dash.Screens.Contacts",
    name="Contacts",
    label="Contacts (logged out)",
    is_current=False,
    enabled=False,
)

_EXPECTED_TABS = [
    DashTab(
        ref_id="tab-ref-1",
        locale_key="Dash.Screens.Worlds",
        name="Worlds",
        label="Worlds",
        is_current=True,
        enabled=True,
    ),
    DashTab(
        ref_id="tab-ref-2",
        locale_key="Dash.Screens.Contacts",
        name="Contacts",
        label="Contacts (logged out)",
        is_current=False,
        enabled=False,
    ),
]

# A button row (top of the light hierarchy: no parent, depth 0, locale_key set)
# and a scroll row nested under it (non-empty parent_ref_id, depth 1, empty
# locale_key). The two ``control_type`` values and the opposite ``enabled``
# flags cover both control kinds and both boolean states in one listing.
_BUTTON_CONTROL = PbDashControl(
    ref_id="ctrl-ref-1",
    control_type="button",
    label="Open Settings",
    locale_key="Settings.Open",
    enabled=True,
    parent_ref_id="",
    depth=0,
)
_SCROLL_CONTROL = PbDashControl(
    ref_id="ctrl-ref-2",
    control_type="scroll",
    label="World List",
    locale_key="",
    enabled=False,
    parent_ref_id="ctrl-ref-1",
    depth=1,
)

_EXPECTED_CONTROLS = [
    DashControl(
        ref_id="ctrl-ref-1",
        control_type="button",
        label="Open Settings",
        locale_key="Settings.Open",
        enabled=True,
        parent_ref_id="",
        depth=0,
    ),
    DashControl(
        ref_id="ctrl-ref-2",
        control_type="scroll",
        label="World List",
        locale_key="",
        enabled=False,
        parent_ref_id="ctrl-ref-1",
        depth=1,
    ),
]


class _FakeDash(DashBase):
    """In-process fake that records each request and returns fixed protos.

    Each RPC stores the request it received so a test can assert the fields
    that reached the server, then returns a deterministic proto so the
    client-side decoding can be checked end-to-end. The mutating actions
    (``set_tab`` / ``invoke`` / ``scroll`` / ``highlight``) echo the
    selector that arrived back as the result ``ref_id`` so a test can prove
    exactly which value crossed the wire.
    """

    def __init__(self) -> None:
        self.open_requests: list[DashOpenRequest] = []
        self.close_requests: list[DashCloseRequest] = []
        self.get_state_requests: list[DashGetStateRequest] = []
        self.list_tabs_requests: list[DashListTabsRequest] = []
        self.set_tab_requests: list[DashSetTabRequest] = []
        self.list_controls_requests: list[DashListControlsRequest] = []
        self.invoke_requests: list[DashInvokeRequest] = []
        self.scroll_requests: list[DashScrollRequest] = []
        self.highlight_requests: list[DashHighlightRequest] = []

    async def open(self, message: DashOpenRequest) -> PbDashState:
        self.open_requests.append(message)
        return PbDashState(is_open=True, open_lerp=1.0)

    async def close(self, message: DashCloseRequest) -> PbDashState:
        self.close_requests.append(message)
        return PbDashState(is_open=False, open_lerp=0.0)

    async def get_state(self, message: DashGetStateRequest) -> PbDashState:
        self.get_state_requests.append(message)
        return PbDashState(is_open=True, open_lerp=0.5)

    async def list_tabs(self, message: DashListTabsRequest) -> PbDashTabList:
        self.list_tabs_requests.append(message)
        return PbDashTabList(tabs=[_WORLDS_TAB, _CONTACTS_TAB])

    async def set_tab(self, message: DashSetTabRequest) -> PbDashActionResult:
        self.set_tab_requests.append(message)
        resolved = message.ref_id or message.locale_key
        return PbDashActionResult(
            ok=True, found=True, ref_id=resolved, detail="switched"
        )

    async def list_controls(
        self, message: DashListControlsRequest
    ) -> PbDashControlList:
        self.list_controls_requests.append(message)
        return PbDashControlList(controls=[_BUTTON_CONTROL, _SCROLL_CONTROL])

    async def invoke(self, message: DashInvokeRequest) -> PbDashActionResult:
        self.invoke_requests.append(message)
        return PbDashActionResult(
            ok=True, found=True, ref_id=message.ref_id, detail="invoked"
        )

    async def scroll(self, message: DashScrollRequest) -> PbDashActionResult:
        self.scroll_requests.append(message)
        return PbDashActionResult(
            ok=True, found=True, ref_id=message.ref_id, detail="scrolled"
        )

    async def highlight(self, message: DashHighlightRequest) -> PbDashActionResult:
        self.highlight_requests.append(message)
        return PbDashActionResult(
            ok=True, found=True, ref_id=message.ref_id, detail="highlighted"
        )


class TestDashRpcRoundTrips:
    """Each unary RPC reaches the server and decodes its response."""

    async def test_open_calls_open_rpc_and_decodes_state(self, uds_server: UdsServer):
        fake = _FakeDash()
        socket_path = await uds_server(fake)
        async with DashClient() as client:
            assert client.socket_path == socket_path
            state = await client.open()

        assert len(fake.open_requests) == 1
        # open is a mutating RPC: no other RPC should have fired.
        assert fake.close_requests == []
        assert fake.get_state_requests == []

        assert isinstance(state, DashState)
        assert state.is_open is True
        assert state.open_lerp == pytest.approx(1.0)

    async def test_close_calls_close_rpc_and_decodes_state(self, uds_server: UdsServer):
        fake = _FakeDash()
        await uds_server(fake)
        async with DashClient() as client:
            state = await client.close()

        assert len(fake.close_requests) == 1
        assert fake.open_requests == []

        assert isinstance(state, DashState)
        assert state.is_open is False
        assert state.open_lerp == pytest.approx(0.0)

    async def test_get_state_calls_get_state_rpc_and_is_read_only(
        self, uds_server: UdsServer
    ):
        fake = _FakeDash()
        await uds_server(fake)
        async with DashClient() as client:
            state = await client.get_state()

        assert len(fake.get_state_requests) == 1
        assert isinstance(state, DashState)
        assert state.is_open is True
        assert state.open_lerp == pytest.approx(0.5)

        # get_state must be read-only: no mutating/other RPC fired.
        assert fake.open_requests == []
        assert fake.close_requests == []
        assert fake.set_tab_requests == []
        assert fake.invoke_requests == []
        assert fake.scroll_requests == []
        assert fake.highlight_requests == []

    async def test_list_tabs_round_trips_all_tab_fields_in_order(
        self, uds_server: UdsServer
    ):
        fake = _FakeDash()
        await uds_server(fake)
        async with DashClient() as client:
            tabs = await client.list_tabs()

        assert len(fake.list_tabs_requests) == 1
        # list_tabs is read-only: no mutating RPC fired.
        assert fake.set_tab_requests == []

        # The result is a list (not a tuple), preserves element order, and
        # every tab field survives the round-trip.
        assert isinstance(tabs, list)
        assert tabs == _EXPECTED_TABS
        assert all(isinstance(t, DashTab) for t in tabs)

    async def test_list_tabs_returns_empty_list_when_no_tabs(
        self, uds_server: UdsServer
    ):
        class _EmptyTabsDash(_FakeDash):
            async def list_tabs(self, message: DashListTabsRequest) -> PbDashTabList:
                self.list_tabs_requests.append(message)
                return PbDashTabList(tabs=[])

        await uds_server(_EmptyTabsDash())
        async with DashClient() as client:
            tabs = await client.list_tabs()

        assert tabs == []

    async def test_set_tab_forwards_both_selectors_and_decodes_result(
        self, uds_server: UdsServer
    ):
        # The client forwards both selectors verbatim; ref_id-vs-locale_key
        # precedence is the server's job, not the client's.
        fake = _FakeDash()
        await uds_server(fake)
        async with DashClient() as client:
            result = await client.set_tab(
                ref_id="tab-ref-1", locale_key="Dash.Screens.Worlds"
            )

        assert len(fake.set_tab_requests) == 1
        wire = fake.set_tab_requests[0]
        assert wire.ref_id == "tab-ref-1"
        assert wire.locale_key == "Dash.Screens.Worlds"

        assert isinstance(result, DashActionResult)
        assert result.ok is True
        assert result.found is True
        # The fake echoes ref_id-first, proving the chosen selector crossed
        # the wire.
        assert result.ref_id == "tab-ref-1"
        assert result.detail == "switched"

    async def test_set_tab_by_locale_key_only_leaves_ref_id_empty_on_wire(
        self, uds_server: UdsServer
    ):
        fake = _FakeDash()
        await uds_server(fake)
        async with DashClient() as client:
            result = await client.set_tab(locale_key="Dash.Screens.Worlds")

        wire = fake.set_tab_requests[0]
        assert wire.locale_key == "Dash.Screens.Worlds"
        assert wire.ref_id == ""
        # The fake echoes the locale_key as the resolved ref_id.
        assert result.ref_id == "Dash.Screens.Worlds"

    async def test_list_controls_decodes_button_and_scroll_rows(
        self, uds_server: UdsServer
    ):
        fake = _FakeDash()
        await uds_server(fake)
        async with DashClient() as client:
            controls = await client.list_controls()

        assert len(fake.list_controls_requests) == 1
        # Default lists only enabled controls.
        assert fake.list_controls_requests[0].include_disabled is False

        # Both control kinds decode, order is preserved, and every field
        # (control_type, locale_key set/empty, parent_ref_id, depth) survives.
        assert isinstance(controls, list)
        assert controls == _EXPECTED_CONTROLS
        assert all(isinstance(c, DashControl) for c in controls)

    async def test_list_controls_forwards_include_disabled_when_true(
        self, uds_server: UdsServer
    ):
        fake = _FakeDash()
        await uds_server(fake)
        async with DashClient() as client:
            await client.list_controls(include_disabled=True)

        assert len(fake.list_controls_requests) == 1
        assert fake.list_controls_requests[0].include_disabled is True

    async def test_invoke_forwards_ref_id_and_decodes_result(
        self, uds_server: UdsServer
    ):
        fake = _FakeDash()
        await uds_server(fake)
        async with DashClient() as client:
            result = await client.invoke("ctrl-ref-42")

        assert len(fake.invoke_requests) == 1
        assert fake.invoke_requests[0].ref_id == "ctrl-ref-42"

        assert isinstance(result, DashActionResult)
        assert result.ok is True
        assert result.found is True
        assert result.ref_id == "ctrl-ref-42"
        assert result.detail == "invoked"

    async def test_scroll_forwards_ref_id_and_deltas_and_decodes_result(
        self, uds_server: UdsServer
    ):
        fake = _FakeDash()
        await uds_server(fake)
        async with DashClient() as client:
            result = await client.scroll("ctrl-ref-9", delta_x=0.25, delta_y=-0.5)

        assert len(fake.scroll_requests) == 1
        wire = fake.scroll_requests[0]
        assert wire.ref_id == "ctrl-ref-9"
        assert wire.delta_x == pytest.approx(0.25)
        assert wire.delta_y == pytest.approx(-0.5)

        assert isinstance(result, DashActionResult)
        assert result.ok is True
        assert result.found is True
        assert result.ref_id == "ctrl-ref-9"
        assert result.detail == "scrolled"

    async def test_scroll_defaults_send_zero_deltas(self, uds_server: UdsServer):
        fake = _FakeDash()
        await uds_server(fake)
        async with DashClient() as client:
            await client.scroll("ctrl-ref-9")

        wire = fake.scroll_requests[0]
        assert wire.ref_id == "ctrl-ref-9"
        assert wire.delta_x == pytest.approx(0.0)
        assert wire.delta_y == pytest.approx(0.0)

    async def test_highlight_forwards_ref_id_and_decodes_result(
        self, uds_server: UdsServer
    ):
        fake = _FakeDash()
        await uds_server(fake)
        async with DashClient() as client:
            result = await client.highlight("ctrl-ref-7")

        assert len(fake.highlight_requests) == 1
        assert fake.highlight_requests[0].ref_id == "ctrl-ref-7"
        # highlight only previews: it must not fire invoke.
        assert fake.invoke_requests == []

        assert isinstance(result, DashActionResult)
        assert result.ok is True
        assert result.found is True
        assert result.ref_id == "ctrl-ref-7"
        assert result.detail == "highlighted"


class TestDashSetTabGuard:
    """``set_tab`` rejects an empty selector before touching the network."""

    async def test_set_tab_with_both_empty_raises_value_error_before_any_rpc(
        self, uds_server: UdsServer
    ):
        # The both-empty guard is a local contract check: it must raise before
        # any network round trip, so a connected client never reaches the
        # server.
        fake = _FakeDash()
        await uds_server(fake)
        async with DashClient() as client:
            with pytest.raises(ValueError, match="ref_id or locale_key"):
                await client.set_tab()

        assert fake.set_tab_requests == []


class TestDashNotConnectedGuard:
    """Every public RPC method refuses to run without an active connection."""

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

    async def test_list_tabs_raises_when_not_connected(self):
        client = DashClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.list_tabs()

    async def test_set_tab_raises_when_not_connected(self):
        # A valid selector is supplied so the not-connected guard (not the
        # both-empty ValueError) is what surfaces.
        client = DashClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.set_tab(locale_key="Dash.Screens.Worlds")

    async def test_list_controls_raises_when_not_connected(self):
        client = DashClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.list_controls()

    async def test_invoke_raises_when_not_connected(self):
        client = DashClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.invoke("ctrl-ref-1")

    async def test_scroll_raises_when_not_connected(self):
        client = DashClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.scroll("ctrl-ref-1")

    async def test_highlight_raises_when_not_connected(self):
        client = DashClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.highlight("ctrl-ref-1")


# --- Resolver fixtures -------------------------------------------------------
#
# Two tabs whose ``ref_id`` of the second is a substring of the first's
# ``label`` lets us prove the exact-ref_id stage wins over a would-be
# substring match (Hyrum's law trap: a stray substring must not steal an exact
# id). ``CASE_TAB`` exercises a casefold-exact hit, ``LOCALE_TAB`` a locale_key
# hit.
_RESOLVER_TABS = [
    DashTab(
        ref_id="aaa",
        locale_key="Dash.Screens.Worlds",
        name="Worlds",
        label="contains xyz inside",
        is_current=True,
        enabled=True,
    ),
    DashTab(
        ref_id="xyz",
        locale_key="Dash.Screens.Contacts",
        name="Contacts",
        label="Contacts",
        is_current=False,
        enabled=True,
    ),
    DashTab(
        ref_id="set-ref",
        locale_key="Dash.Screens.Settings",
        name="Settings",
        label="Settings",
        is_current=False,
        enabled=True,
    ),
]


class TestResolveOne:
    """``_resolve_one`` ranks exact > casefold-exact > unique substring."""

    def test_exact_ref_id_wins_over_substring_of_another_label(self):
        # "xyz" is an exact ref_id of the second tab AND a substring of the
        # first tab's label; the exact-id stage must short-circuit so the
        # second tab is chosen unambiguously.
        result = _resolve_one(_RESOLVER_TABS, "xyz", _tab_keys)
        assert result.ref_id == "xyz"

    def test_casefold_exact_match_on_name(self):
        result = _resolve_one(_RESOLVER_TABS, "settings", _tab_keys)
        assert result.ref_id == "set-ref"

    def test_unique_casefold_substring_match(self):
        # The query is a substring of exactly one tab's name ("Settings").
        result = _resolve_one(_RESOLVER_TABS, "settin", _tab_keys)  # codespell:ignore
        assert result.ref_id == "set-ref"

    def test_locale_key_hit_resolves_the_tab(self):
        result = _resolve_one(_RESOLVER_TABS, "Dash.Screens.Contacts", _tab_keys)
        assert result.ref_id == "xyz"

    def test_zero_matches_raises_no_match_error(self):
        with pytest.raises(DashNoMatchError, match="no match"):
            _resolve_one(_RESOLVER_TABS, "no-such-thing", _tab_keys)

    def test_ambiguous_substring_raises_ambiguous_match_error(self):
        # "Dash.Screens." is a substring of all three locale_keys, so the
        # substring stage matches more than one item.
        with pytest.raises(DashAmbiguousMatchError, match="matched 3"):
            _resolve_one(_RESOLVER_TABS, "Dash.Screens.", _tab_keys)


# --- by-label helper fixtures ------------------------------------------------
#
# The by-label helpers fetch a list, resolve a query to one item, then call the
# corresponding ref_id-based RPC. These fakes return a known tab/control list
# and record what the *follow-up* mutating RPC received on the wire.
_BYLABEL_TABS = [
    PbDashTab(
        ref_id="tab-worlds-ref",
        locale_key="Dash.Screens.Worlds",
        name="Worlds",
        label="Worlds",
        is_current=True,
        enabled=True,
    ),
    PbDashTab(
        ref_id="tab-settings-ref",
        locale_key="Dash.Screens.Settings",
        name="Settings",
        label="Settings",
        is_current=False,
        enabled=True,
    ),
]

# Two enabled controls (find_control reads the default include_disabled=False
# listing, so disabled controls would not be visible to the resolver).
_BYLABEL_CONTROLS = [
    PbDashControl(
        ref_id="ctrl-open-ref",
        control_type="button",
        label="Open Settings",
        locale_key="Settings.Open",
        enabled=True,
        parent_ref_id="",
        depth=0,
    ),
    PbDashControl(
        ref_id="ctrl-list-ref",
        control_type="scroll",
        label="World List",
        locale_key="",
        enabled=True,
        parent_ref_id="",
        depth=0,
    ),
]


class _ByLabelDash(_FakeDash):
    """Fake returning known tab/control lists for the by-label helpers."""

    async def list_tabs(self, message: DashListTabsRequest) -> PbDashTabList:
        self.list_tabs_requests.append(message)
        return PbDashTabList(tabs=list(_BYLABEL_TABS))

    async def list_controls(
        self, message: DashListControlsRequest
    ) -> PbDashControlList:
        self.list_controls_requests.append(message)
        return PbDashControlList(controls=list(_BYLABEL_CONTROLS))


class TestDashByLabelHelpers:
    """``*_by_label`` helpers resolve a query then act on the full ref_id."""

    async def test_find_tab_returns_the_matching_tab(self, uds_server: UdsServer):
        await uds_server(_ByLabelDash())
        async with DashClient() as client:
            tab = await client.find_tab("Settings")

        assert isinstance(tab, DashTab)
        assert tab.ref_id == "tab-settings-ref"

    async def test_set_tab_by_label_sends_resolved_full_ref_id(
        self, uds_server: UdsServer
    ):
        fake = _ByLabelDash()
        await uds_server(fake)
        async with DashClient() as client:
            result = await client.set_tab_by_label("Settings")

        # The set_tab RPC must carry the resolved full ref_id (not the label),
        # and locale_key must be empty since selection happened client-side.
        assert len(fake.set_tab_requests) == 1
        wire = fake.set_tab_requests[0]
        assert wire.ref_id == "tab-settings-ref"
        assert wire.locale_key == ""
        assert result.ref_id == "tab-settings-ref"

    async def test_find_control_returns_the_matching_control(
        self, uds_server: UdsServer
    ):
        await uds_server(_ByLabelDash())
        async with DashClient() as client:
            control = await client.find_control("World List")

        assert isinstance(control, DashControl)
        assert control.ref_id == "ctrl-list-ref"

    async def test_invoke_by_label_sends_resolved_full_ref_id(
        self, uds_server: UdsServer
    ):
        fake = _ByLabelDash()
        await uds_server(fake)
        async with DashClient() as client:
            result = await client.invoke_by_label("Open Settings")

        assert len(fake.invoke_requests) == 1
        assert fake.invoke_requests[0].ref_id == "ctrl-open-ref"
        assert result.ref_id == "ctrl-open-ref"

    async def test_scroll_by_label_forwards_resolved_ref_id_and_deltas(
        self, uds_server: UdsServer
    ):
        fake = _ByLabelDash()
        await uds_server(fake)
        async with DashClient() as client:
            await client.scroll_by_label("World List", delta_x=0.1, delta_y=0.2)

        assert len(fake.scroll_requests) == 1
        wire = fake.scroll_requests[0]
        assert wire.ref_id == "ctrl-list-ref"
        assert wire.delta_x == pytest.approx(0.1)
        assert wire.delta_y == pytest.approx(0.2)

    async def test_highlight_by_label_sends_resolved_full_ref_id(
        self, uds_server: UdsServer
    ):
        fake = _ByLabelDash()
        await uds_server(fake)
        async with DashClient() as client:
            await client.highlight_by_label("Open Settings")

        assert len(fake.highlight_requests) == 1
        assert fake.highlight_requests[0].ref_id == "ctrl-open-ref"

    async def test_set_tab_by_label_propagates_no_match(self, uds_server: UdsServer):
        fake = _ByLabelDash()
        await uds_server(fake)
        async with DashClient() as client:
            with pytest.raises(DashNoMatchError):
                await client.set_tab_by_label("nonexistent-tab")

        # Resolution failed client-side, so the set_tab RPC never fired.
        assert fake.set_tab_requests == []

    async def test_invoke_by_label_propagates_ambiguous_match(
        self, uds_server: UdsServer
    ):
        fake = _ByLabelDash()
        await uds_server(fake)
        async with DashClient() as client:
            # "-ref" is a substring of BOTH controls' ref_ids
            # ("ctrl-open-ref" and "ctrl-list-ref"), so the substring stage
            # matches more than one control and the query is ambiguous.
            with pytest.raises(DashAmbiguousMatchError):
                await client.invoke_by_label("-ref")

        assert fake.invoke_requests == []
