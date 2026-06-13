"""CLI tests for ``resoio dash``.

The CLI register/_run path is driven against a real ``grpclib.server.Server``
hosting an inline fake :class:`DashBase` over a real UDS (no mocking of
grpclib/betterproto2). Each test asserts that the chosen command issues the
correct RPC(s) with the correct arguments, that read-only commands stay free
of mutations, that client-side selector resolution forwards the **full**
``ref_id`` on the wire, and that resolution / argparse failures exit ``2``.

The dash is a **bottom tab bar** plus, within the current tab, a set of
interactable **controls**. Commands (entrypoint ``resoio dash ...``):

* no subcommand -> SUMMARY: fires ``get_state`` + ``list_tabs`` +
  ``list_controls`` and renders state + current tab + a numbered current-tab
  control list;
* ``open`` / ``close`` / ``state`` -> open / close / get_state;
* ``tabs`` -> ``list_tabs`` (aligned table, ``*`` marks the current tab);
* ``tab <selector>`` -> resolve a tab, then ``set_tab`` with the resolved
  **full** ``ref_id``;
* ``ls [--all]`` -> ``list_controls(include_disabled = --all present)``,
  numbered table;
* ``invoke`` / ``scroll`` / ``highlight`` <selector> [...] -> resolve a
  control, then the matching RPC with the full ``ref_id`` (and scroll deltas).

A ``<selector>`` is resolved client-side against the just-fetched listing: an
all-digit query is a 0-based index into that listing (bounds-checked); else an
exact ``ref_id`` / casefold-exact / unique casefold substring over the
listing's keys. Ambiguous / no-match / index-out-of-range writes a candidate
list to stderr and exits ``2``. The mutating-action result line keeps the
documented ``ok=... found=... ref_id=... detail=...`` shape.
"""

from pathlib import Path

import pytest
from grpclib.server import Server

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
from resoio.cli import _amain, _build_parser


async def _run_cli(argv: list[str]) -> int:
    """Run the CLI and return its exit code.

    Normalizes the two contractual error loci: an argparse usage error
    (SystemExit raised by ``parse_args``) and a runtime return code from
    ``_amain``. The contract pins the exit code, not the locus.
    """
    try:
        args = _build_parser().parse_args(argv)
    except SystemExit as exc:
        assert isinstance(exc.code, int)
        return exc.code
    return await _amain(args)


def _parse_error_code(argv: list[str]) -> int:
    """Return the SystemExit code raised by ``parse_args`` for ``argv``."""
    with pytest.raises(SystemExit) as excinfo:
        _build_parser().parse_args(argv)
    assert isinstance(excinfo.value.code, int)
    return excinfo.value.code


# A small bottom tab bar: Worlds is current; Contacts is disabled (logged
# out). ref_ids are full engine ReferenceIDs so the "full ref_id on the wire"
# assertions are meaningful.
_TAB_WORLDS = PbDashTab(
    ref_id="ID5A2B@worlds-screen",
    locale_key="Dash.Screens.Worlds",
    name="Worlds",
    label="Worlds",
    is_current=True,
    enabled=True,
)
_TAB_CONTACTS = PbDashTab(
    ref_id="ID5A2C@contacts-screen",
    locale_key="Dash.Screens.Contacts",
    name="Contacts",
    label="Contacts",
    is_current=False,
    enabled=False,
)
_TABS = [_TAB_WORLDS, _TAB_CONTACTS]

# Controls of the current (Worlds) tab. Two buttons share the substring
# "World" in their labels so an ambiguous-substring selector can be exercised;
# "Refresh" is unique. The scroll control carries no label (icon-only) but a
# unique ref_id.
_CTL_NEW_WORLD = PbDashControl(
    ref_id="ID7001@new-world-btn",
    control_type="button",
    label="New World",
    locale_key="Worlds.New",
    enabled=True,
    parent_ref_id="",
    depth=0,
)
_CTL_MY_WORLDS = PbDashControl(
    ref_id="ID7002@my-worlds-btn",
    control_type="button",
    label="My Worlds",
    locale_key="Worlds.Mine",
    enabled=True,
    parent_ref_id="",
    depth=0,
)
_CTL_REFRESH = PbDashControl(
    ref_id="ID7003@refresh-btn",
    control_type="button",
    label="Refresh",
    locale_key="Worlds.Refresh",
    enabled=True,
    parent_ref_id="",
    depth=0,
)
_CTL_SCROLL = PbDashControl(
    ref_id="ID7004@world-list-scroll",
    control_type="scroll",
    label="",
    locale_key="",
    enabled=True,
    parent_ref_id="",
    depth=0,
)
# A disabled control only surfaces when include_disabled is requested.
_CTL_DISABLED = PbDashControl(
    ref_id="ID7005@archive-btn",
    control_type="button",
    label="Archive",
    locale_key="Worlds.Archive",
    enabled=False,
    parent_ref_id="",
    depth=0,
)

_ENABLED_CONTROLS = [_CTL_NEW_WORLD, _CTL_MY_WORLDS, _CTL_REFRESH, _CTL_SCROLL]


class _FakeDash(DashBase):
    """In-process fake recording each request and returning fixed values.

    ``list_controls`` honours ``include_disabled`` so the ``ls --all`` toggle
    can be observed end to end. ``set_tab`` / ``invoke`` / ``scroll`` /
    ``highlight`` echo the resolved ``ref_id`` so the CLI's client-side
    resolution can be asserted on the wire.
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
        return PbDashTabList(tabs=_TABS)

    async def set_tab(self, message: DashSetTabRequest) -> PbDashActionResult:
        self.set_tab_requests.append(message)
        return PbDashActionResult(
            ok=True, found=True, ref_id=message.ref_id, detail="switched"
        )

    async def list_controls(
        self, message: DashListControlsRequest
    ) -> PbDashControlList:
        self.list_controls_requests.append(message)
        controls = list(_ENABLED_CONTROLS)
        if message.include_disabled:
            controls.append(_CTL_DISABLED)
        return PbDashControlList(controls=controls)

    async def invoke(self, message: DashInvokeRequest) -> PbDashActionResult:
        self.invoke_requests.append(message)
        return PbDashActionResult(
            ok=True, found=True, ref_id=message.ref_id, detail="pressed"
        )

    async def scroll(self, message: DashScrollRequest) -> PbDashActionResult:
        self.scroll_requests.append(message)
        return PbDashActionResult(
            ok=True, found=True, ref_id=message.ref_id, detail="scrolled"
        )

    async def highlight(self, message: DashHighlightRequest) -> PbDashActionResult:
        self.highlight_requests.append(message)
        return PbDashActionResult(
            ok=True, found=True, ref_id=message.ref_id, detail="hovered"
        )


# --- harness ----------------------------------------------------------------


async def _serve(socket_path: Path, fake: _FakeDash) -> Server:
    server = Server([fake])
    await server.start(path=str(socket_path))
    return server


# --- summary (no subcommand) ------------------------------------------------


async def test_bare_dash_summary_fires_state_tabs_and_controls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """``resoio dash`` with no subcommand answers "what can I do now": it fires
    get_state + list_tabs + list_controls and renders state, the current tab,
    and a numbered current-tab control list."""
    socket_path = tmp_path / "rio-dash.sock"
    fake = _FakeDash()
    server = await _serve(socket_path, fake)
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        rc = await _run_cli(["dash"])
        assert rc == 0

        # All three reads were issued; no mutation crept into the summary.
        assert len(fake.get_state_requests) == 1
        assert len(fake.list_tabs_requests) == 1
        assert len(fake.list_controls_requests) == 1
        assert fake.set_tab_requests == []
        assert fake.invoke_requests == []
        assert fake.open_requests == []

        out = capsys.readouterr().out
        # State line is present.
        assert "is_open=True" in out
        # The current tab (Worlds) is named in the summary.
        assert "Worlds" in out
        # The current-tab controls are numbered (0-based) and named.
        assert "New World" in out
        assert "Refresh" in out
        # The summary numbers the control list; index 0 is shown.
        lines = out.splitlines()
        assert any(line.lstrip().startswith("0") for line in lines)
    finally:
        server.close()
        await server.wait_closed()


# --- open / close / state ---------------------------------------------------


async def test_open_issues_open_rpc_and_prints_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    socket_path = tmp_path / "rio-dash.sock"
    fake = _FakeDash()
    server = await _serve(socket_path, fake)
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        rc = await _run_cli(["dash", "open"])
        assert rc == 0

        assert len(fake.open_requests) == 1
        out = capsys.readouterr().out
        assert "is_open=True" in out
    finally:
        server.close()
        await server.wait_closed()


async def test_close_issues_close_rpc_and_prints_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    socket_path = tmp_path / "rio-dash.sock"
    fake = _FakeDash()
    server = await _serve(socket_path, fake)
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        rc = await _run_cli(["dash", "close"])
        assert rc == 0

        assert len(fake.close_requests) == 1
        out = capsys.readouterr().out
        assert "is_open=False" in out
    finally:
        server.close()
        await server.wait_closed()


async def test_state_is_read_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """``state`` reads get_state and issues no open/close/mutation."""
    socket_path = tmp_path / "rio-dash.sock"
    fake = _FakeDash()
    server = await _serve(socket_path, fake)
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        rc = await _run_cli(["dash", "state"])
        assert rc == 0

        assert len(fake.get_state_requests) == 1
        assert fake.open_requests == []
        assert fake.close_requests == []
        assert fake.set_tab_requests == []
        assert fake.invoke_requests == []

        out = capsys.readouterr().out
        assert "is_open=True" in out
    finally:
        server.close()
        await server.wait_closed()


# --- tabs (read-only listing) -----------------------------------------------


async def test_tabs_lists_tabs_and_marks_current(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """``tabs`` lists the bottom bar and marks the current tab with ``*``; it
    must not switch tabs."""
    socket_path = tmp_path / "rio-dash.sock"
    fake = _FakeDash()
    server = await _serve(socket_path, fake)
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        rc = await _run_cli(["dash", "tabs"])
        assert rc == 0

        assert len(fake.list_tabs_requests) == 1
        # `tabs` is browse-only: it must not navigate.
        assert fake.set_tab_requests == []

        out = capsys.readouterr().out
        assert "Worlds" in out
        assert "Contacts" in out
        # The current tab (Worlds) is marked with '*'; the line that carries
        # the marker is the one naming the current tab.
        worlds_line = next(line for line in out.splitlines() if "Worlds" in line)
        assert "*" in worlds_line
        contacts_line = next(line for line in out.splitlines() if "Contacts" in line)
        assert "*" not in contacts_line
    finally:
        server.close()
        await server.wait_closed()


# --- ls (controls listing, --all toggle) ------------------------------------


async def test_ls_lists_enabled_controls_without_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """``ls`` (no ``--all``) requests include_disabled=False and numbers the
    listing; the disabled control is absent."""
    socket_path = tmp_path / "rio-dash.sock"
    fake = _FakeDash()
    server = await _serve(socket_path, fake)
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        rc = await _run_cli(["dash", "ls"])
        assert rc == 0

        assert len(fake.list_controls_requests) == 1
        assert fake.list_controls_requests[0].include_disabled is False
        # `ls` is browse-only.
        assert fake.invoke_requests == []
        assert fake.scroll_requests == []

        out = capsys.readouterr().out
        # Enabled controls are listed; the disabled one is not.
        assert "New World" in out
        assert "Refresh" in out
        assert "Archive" not in out
        # The listing is numbered (0-based).
        lines = out.splitlines()
        assert any(line.lstrip().startswith("0") for line in lines)
    finally:
        server.close()
        await server.wait_closed()


async def test_ls_all_requests_include_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """``ls --all`` requests include_disabled=True and the disabled control
    appears in the listing."""
    socket_path = tmp_path / "rio-dash.sock"
    fake = _FakeDash()
    server = await _serve(socket_path, fake)
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        rc = await _run_cli(["dash", "ls", "--all"])
        assert rc == 0

        assert len(fake.list_controls_requests) == 1
        assert fake.list_controls_requests[0].include_disabled is True

        out = capsys.readouterr().out
        assert "Archive" in out
    finally:
        server.close()
        await server.wait_closed()


# --- tab <selector>: switch by resolved full ref_id -------------------------


async def test_tab_by_label_substring_switches_by_full_ref_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """``tab contacts`` resolves a tab client-side and switches by its FULL
    ``ref_id`` on the wire, printing the result line."""
    socket_path = tmp_path / "rio-dash.sock"
    fake = _FakeDash()
    server = await _serve(socket_path, fake)
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        rc = await _run_cli(["dash", "tab", "contacts"])
        assert rc == 0

        assert len(fake.set_tab_requests) == 1
        # The full ref_id (not the label / a short ref) is sent on the wire.
        assert fake.set_tab_requests[0].ref_id == _TAB_CONTACTS.ref_id

        out = capsys.readouterr().out.strip()
        # The mutating-action result line keeps the documented shape.
        assert out.startswith(f"ok=True found=True ref_id={_TAB_CONTACTS.ref_id}")
        assert "detail=" in out
    finally:
        server.close()
        await server.wait_closed()


async def test_tab_by_numeric_index_resolves_listing_position(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """A numeric selector is a 0-based index into the just-fetched tab listing;
    ``tab 1`` switches to the second tab by its full ref_id."""
    socket_path = tmp_path / "rio-dash.sock"
    fake = _FakeDash()
    server = await _serve(socket_path, fake)
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        rc = await _run_cli(["dash", "tab", "1"])
        assert rc == 0

        assert len(fake.set_tab_requests) == 1
        assert fake.set_tab_requests[0].ref_id == _TABS[1].ref_id
    finally:
        server.close()
        await server.wait_closed()


# --- invoke / scroll / highlight: resolve a control then act ----------------


async def test_invoke_by_exact_ref_id_forwards_full_ref_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """``invoke`` with an exact ``ref_id`` selector presses that control and
    forwards the full ref_id on the wire."""
    socket_path = tmp_path / "rio-dash.sock"
    fake = _FakeDash()
    server = await _serve(socket_path, fake)
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        rc = await _run_cli(["dash", "invoke", _CTL_REFRESH.ref_id])
        assert rc == 0

        assert len(fake.invoke_requests) == 1
        assert fake.invoke_requests[0].ref_id == _CTL_REFRESH.ref_id

        out = capsys.readouterr().out.strip()
        assert out.startswith(f"ok=True found=True ref_id={_CTL_REFRESH.ref_id}")
    finally:
        server.close()
        await server.wait_closed()


async def test_invoke_by_unique_label_substring_resolves_control(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """A unique label substring resolves a single control; ``invoke refresh``
    presses Refresh by its full ref_id."""
    socket_path = tmp_path / "rio-dash.sock"
    fake = _FakeDash()
    server = await _serve(socket_path, fake)
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        rc = await _run_cli(["dash", "invoke", "refresh"])
        assert rc == 0

        assert len(fake.invoke_requests) == 1
        assert fake.invoke_requests[0].ref_id == _CTL_REFRESH.ref_id
    finally:
        server.close()
        await server.wait_closed()


async def test_invoke_by_numeric_index_resolves_listing_position(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """A numeric control selector indexes the just-fetched control listing
    (0-based); ``invoke 0`` presses the first control."""
    socket_path = tmp_path / "rio-dash.sock"
    fake = _FakeDash()
    server = await _serve(socket_path, fake)
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        rc = await _run_cli(["dash", "invoke", "0"])
        assert rc == 0

        assert len(fake.invoke_requests) == 1
        assert fake.invoke_requests[0].ref_id == _ENABLED_CONTROLS[0].ref_id
    finally:
        server.close()
        await server.wait_closed()


async def test_scroll_forwards_ref_id_and_deltas(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """``scroll <selector> <dx> <dy>`` resolves the control and forwards the
    full ref_id plus the parsed float deltas."""
    socket_path = tmp_path / "rio-dash.sock"
    fake = _FakeDash()
    server = await _serve(socket_path, fake)
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        rc = await _run_cli(["dash", "scroll", _CTL_SCROLL.ref_id, "0.0", "0.3"])
        assert rc == 0

        assert len(fake.scroll_requests) == 1
        wire = fake.scroll_requests[0]
        assert wire.ref_id == _CTL_SCROLL.ref_id
        assert wire.delta_x == pytest.approx(0.0)
        assert wire.delta_y == pytest.approx(0.3)

        out = capsys.readouterr().out.strip()
        assert out.startswith(f"ok=True found=True ref_id={_CTL_SCROLL.ref_id}")
    finally:
        server.close()
        await server.wait_closed()


async def test_highlight_forwards_full_ref_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """``highlight <selector>`` resolves a control and hover-highlights it by
    its full ref_id."""
    socket_path = tmp_path / "rio-dash.sock"
    fake = _FakeDash()
    server = await _serve(socket_path, fake)
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        rc = await _run_cli(["dash", "highlight", "refresh"])
        assert rc == 0

        assert len(fake.highlight_requests) == 1
        assert fake.highlight_requests[0].ref_id == _CTL_REFRESH.ref_id

        out = capsys.readouterr().out.strip()
        assert out.startswith(f"ok=True found=True ref_id={_CTL_REFRESH.ref_id}")
    finally:
        server.close()
        await server.wait_closed()


# --- selector resolution failures: exit 2 + candidate list ------------------


async def test_ambiguous_label_selector_exits_2_with_candidates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """An ambiguous control label substring (matches >1 control) writes a
    candidate list to stderr and exits 2 without invoking anything."""
    socket_path = tmp_path / "rio-dash.sock"
    fake = _FakeDash()
    server = await _serve(socket_path, fake)
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        # "world" appears in both "New World" and "My Worlds".
        rc = await _run_cli(["dash", "invoke", "world"])
        assert rc == 2

        assert fake.invoke_requests == []

        err = capsys.readouterr().err
        # The friendly error names both ambiguous candidates.
        assert "New World" in err
        assert "My Worlds" in err
    finally:
        server.close()
        await server.wait_closed()


async def test_no_match_label_selector_exits_2_with_candidates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """A selector matching no control exits 2 and lists the available
    candidates on stderr."""
    socket_path = tmp_path / "rio-dash.sock"
    fake = _FakeDash()
    server = await _serve(socket_path, fake)
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        rc = await _run_cli(["dash", "invoke", "nonexistent-control"])
        assert rc == 2

        assert fake.invoke_requests == []

        err = capsys.readouterr().err
        # The candidate list points the caller at real controls.
        assert "Refresh" in err
    finally:
        server.close()
        await server.wait_closed()


async def test_index_out_of_range_selector_exits_2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """A numeric selector past the end of the listing is rejected with exit 2
    and a candidate list (the index is bounds-checked client-side)."""
    socket_path = tmp_path / "rio-dash.sock"
    fake = _FakeDash()
    server = await _serve(socket_path, fake)
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        # Only 4 enabled controls -> valid indices are 0..3.
        rc = await _run_cli(["dash", "invoke", "99"])
        assert rc == 2

        assert fake.invoke_requests == []

        err = capsys.readouterr().err
        assert err.strip() != ""
    finally:
        server.close()
        await server.wait_closed()


async def test_tab_ambiguous_selector_does_not_switch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """An unresolvable ``tab`` selector exits 2 without issuing set_tab."""
    socket_path = tmp_path / "rio-dash.sock"
    fake = _FakeDash()
    server = await _serve(socket_path, fake)
    try:
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        rc = await _run_cli(["dash", "tab", "no-such-tab"])
        assert rc == 2
        assert fake.set_tab_requests == []
    finally:
        server.close()
        await server.wait_closed()


# --- socket routing ---------------------------------------------------------


async def test_socket_flag_routes_to_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """``-s SOCK`` is the explicit socket route (env var would mask intent)."""
    socket_path = tmp_path / "rio-dash.sock"
    fake = _FakeDash()
    server = await _serve(socket_path, fake)
    try:
        monkeypatch.delenv("RESONITE_IO_SOCKET", raising=False)
        rc = await _run_cli(["dash", "state", "-s", str(socket_path)])
        assert rc == 0
        assert len(fake.get_state_requests) == 1
    finally:
        server.close()
        await server.wait_closed()


# --- argparse usage errors (exit 2 at parse) --------------------------------


def test_tab_without_selector_is_a_parse_error():
    """``tab`` requires a selector positional; omitting it exits 2 at parse."""
    assert _parse_error_code(["dash", "tab"]) == 2


def test_invoke_without_selector_is_a_parse_error():
    """``invoke`` requires a selector positional; omitting it exits 2."""
    assert _parse_error_code(["dash", "invoke"]) == 2


def test_scroll_without_selector_is_a_parse_error():
    """``scroll`` requires a selector positional; omitting it exits 2."""
    assert _parse_error_code(["dash", "scroll"]) == 2


def test_highlight_without_selector_is_a_parse_error():
    """``highlight`` requires a selector positional; omitting it exits 2."""
    assert _parse_error_code(["dash", "highlight"]) == 2


def test_scroll_with_non_float_delta_is_a_parse_error():
    """``scroll`` deltas are argparse floats; a non-numeric dx exits 2."""
    assert _parse_error_code(["dash", "scroll", "0", "abc", "0.3"]) == 2


def test_scroll_missing_deltas_is_a_parse_error():
    """``scroll`` requires both dx and dy positionals; omitting them exits
    2."""
    assert _parse_error_code(["dash", "scroll", "0"]) == 2


def test_unknown_subcommand_is_a_parse_error():
    """An unknown ``dash`` subcommand is a usage error (exit 2)."""
    assert _parse_error_code(["dash", "toggle"]) == 2
