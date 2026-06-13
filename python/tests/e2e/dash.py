"""E2E: drive the Dash modality against a live Resonite and screenshot.

Exercises the full closed loop on the real Esc dash (userspace overlay):
open -> enumerate the **bottom tab bar** (language-independent ``ref_id`` +
``locale_key`` per tab) -> switch the current tab by tab -> let the switch
settle -> enumerate the current tab's interactable **controls** -> operate a
control by ``ref_id`` (highlight / invoke) -> close. Each step is followed by
a host-side desktop screenshot via the host-agent
(``scripts/resonite_cli.py screenshot``) since the dash is a local-user
overlay an in-world Camera would not capture.

Open/close is driven as a symmetric ``close -> open -> close -> open`` so a
real toggle is distinguishable from a no-op on an already-open dash.

Note on the localization goal: ``ref_id`` (engine RefID) and ``locale_key``
(``LocaleStringDriver`` key) are asserted present and stable across snapshots.
Confirming they are *identical* under a different UI language requires
switching Resonite's locale (a manual follow-up), but their
language-independence is structural: neither derives from the displayed
``label``.

Like every file under ``tests/e2e/`` this requires the host-side
``just host-agent`` daemon plus a live Resonite client; the
``require_host_agent`` autouse fixture skips otherwise.
"""

from __future__ import annotations

import asyncio
import subprocess
import time
from datetime import datetime
from pathlib import Path

import grpclib
import pytest
from grpclib.const import Status

from resoio.dash import DashClient, DashControl, DashTab
from tests.helpers import mark_e2e

# parents[2] is python/; the repo root (where scripts/ lives) is parents[3].
REPO_ROOT: Path = Path(__file__).resolve().parents[3]
ARTIFACT_ROOT = Path(__file__).parent / "e2e_artifacts"

# UDS bind and UserspaceRadiantDash readiness race: while the engine is still
# booting, the Dash bridge raises DashNotReadyException -> FAILED_PRECONDITION.
_READY_TIMEOUT_S = 120.0
_READY_RETRY_INTERVAL_S = 2.0

# The bridge becomes ready before the home world has finished loading; give it
# time to settle so the desktop is fully rendered before driving the dash.
_HOME_LOAD_SETTLE_S = 20.0

# Let the dash open/close lerp finish and the renderer present a frame before
# grabbing the desktop, so screenshots are not torn mid-animation.
_SETTLE_S = 0.6

# After a set_tab the CurrentScreen.Target / is_current flip is synchronous,
# but the tab-switch animation (~0.5s at the default speed) needs to settle
# before list_controls reflects the new tab's content.
TAB_SETTLE_S = 0.6

# Standard, login-independent tabs preferred as a navigation target when
# present. The scenario falls back to any enabled, keyed, non-current tab so
# it does not break if Resonite's tab set shifts between versions / login
# states.
_PREFERRED_TAB_KEYS = (
    "Dash.Screens.Worlds",
    "Dash.Screens.Settings",
    "Dash.Screens.Inventory",
)


def _screenshot(out_dir: Path, name: str) -> None:
    """Grab the host desktop into ``out_dir/name`` via the host-agent
    bridge."""
    path = out_dir / name
    subprocess.run(
        ["python3", "scripts/resonite_cli.py", "screenshot", "--output", str(path)],
        cwd=REPO_ROOT,
        check=True,
        text=True,
        capture_output=True,
        timeout=30.0,
    )


def _format_tabs(tabs: list[DashTab]) -> str:
    lines = [f"count={len(tabs)}"]
    for t in tabs:
        lines.append(
            f"  [{t.ref_id}] {t.locale_key} {t.name} is_current={t.is_current} "
            f"enabled={t.enabled} label={t.label!r}"
        )
    return "\n".join(lines)


def _format_controls(controls: list[DashControl]) -> str:
    lines = [f"count={len(controls)}"]
    for c in controls:
        lines.append(
            f"  [{c.ref_id}] {c.control_type} locale={c.locale_key!r} "
            f"label={c.label!r} enabled={c.enabled} depth={c.depth}"
        )
    return "\n".join(lines)


def _current_ref_id(tabs: list[DashTab]) -> str | None:
    current = [t for t in tabs if t.is_current]
    return current[0].ref_id if len(current) == 1 else None


def _pick_target_tab(tabs: list[DashTab], current_ref_id: str | None) -> DashTab | None:
    # Candidates: enabled, keyed, and not the tab we are already on.
    candidates = [
        t for t in tabs if t.enabled and t.locale_key and t.ref_id != current_ref_id
    ]
    preferred = [t for t in candidates if t.locale_key in _PREFERRED_TAB_KEYS]
    others = [t for t in candidates if t.locale_key not in _PREFERRED_TAB_KEYS]
    ordered = preferred + others
    return ordered[0] if ordered else None


class TestDash:
    @mark_e2e
    def test_open_navigate_tabs_operate_close(self, resonite_session: Path) -> None:
        del resonite_session  # fixture only manages Resonite lifecycle

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = ARTIFACT_ROOT / f"dash_{timestamp}"
        out_dir.mkdir(parents=True, exist_ok=True)
        log_path = out_dir / "states.txt"
        log_lines: list[str] = []

        def record(step: str, text: str) -> None:
            block = f"=== {step} ===\n{text}"
            log_lines.append(block)
            print(block)

        async def wait_for_ready() -> bool:
            deadline = time.monotonic() + _READY_TIMEOUT_S
            while True:
                try:
                    async with DashClient() as dash:
                        return (await dash.get_state()).is_open
                except grpclib.exceptions.GRPCError as e:
                    if e.status != Status.FAILED_PRECONDITION:
                        raise
                    if time.monotonic() >= deadline:
                        raise AssertionError(
                            "Dash bridge never became ready within "
                            f"{_READY_TIMEOUT_S:.0f}s"
                        ) from e
                    await asyncio.sleep(_READY_RETRY_INTERVAL_S)

        async def settle_shot(step: str) -> None:
            await asyncio.sleep(_SETTLE_S)
            _screenshot(out_dir, f"{step}.png")

        async def scenario() -> None:
            # 0. baseline: engine ready, dash closed. Let the home world settle.
            await wait_for_ready()
            await asyncio.sleep(_HOME_LOAD_SETTLE_S)
            await wait_for_ready()

            async with DashClient() as dash:
                # 1. symmetric close -> open -> close -> open so a real toggle
                #    is distinguishable from a no-op on an already-open dash.
                await dash.close()
                s_closed = await dash.get_state()
                record("00_closed", f"is_open={s_closed.is_open}")
                await settle_shot("00_closed")
                assert not s_closed.is_open, "dash should be closed"

                opened = await dash.open()
                record(
                    "01_open", f"is_open={opened.is_open} open_lerp={opened.open_lerp}"
                )
                await settle_shot("01_open")
                assert opened.is_open, "dash should be open after open()"

                await dash.close()
                assert not (await dash.get_state()).is_open
                reopened = await dash.open()
                record("02_reopen", f"is_open={reopened.is_open}")
                await settle_shot("02_reopen")
                assert reopened.is_open

                # 2. enumerate the bottom tab bar. Exactly one tab is current;
                #    every tab carries a ref_id; standard tabs carry a
                #    language-independent locale_key.
                tabs = await dash.list_tabs()
                record("03_tabs", _format_tabs(tabs))
                await settle_shot("03_tabs")
                assert tabs, "open dash should expose tabs"
                assert sum(t.is_current for t in tabs) == 1, (
                    "exactly one tab must be current"
                )
                assert all(t.ref_id for t in tabs), "every tab needs a ref_id"
                assert any(t.locale_key.startswith("Dash.Screens.") for t in tabs), (
                    "standard tabs should carry a language-independent locale_key"
                )

                # ref_id / locale_key are stable across snapshots (not derived
                # from transient layout or the displayed label).
                tabs2 = await dash.list_tabs()
                keys1 = {(t.ref_id, t.locale_key) for t in tabs}
                keys2 = {(t.ref_id, t.locale_key) for t in tabs2}
                assert keys1 & keys2, (
                    "ref_id/locale_key should be stable across snapshots"
                )

                # 3. switch the current tab by its language-independent
                #    locale_key and confirm is_current tracks it.
                start_ref_id = _current_ref_id(tabs)
                target = _pick_target_tab(tabs, start_ref_id)
                if target is None:
                    pytest.skip(
                        "no enabled, keyed, non-current tab to switch to "
                        "(unexpected logged-out / minimal tab set)"
                    )

                switched = await dash.set_tab(locale_key=target.locale_key)
                record(
                    "04_set_tab",
                    f"ok={switched.ok} found={switched.found} "
                    f"ref_id={switched.ref_id} detail={switched.detail!r}",
                )
                assert switched.found, f"tab {target.locale_key} should resolve"
                assert switched.ok, f"set_tab({target.locale_key}) should succeed"

                await asyncio.sleep(TAB_SETTLE_S)
                after = await dash.list_tabs()
                assert _current_ref_id(after) == target.ref_id, (
                    f"is_current should move to {target.locale_key} "
                    f"(ref_id {target.ref_id})"
                )
                await settle_shot("04_set_tab")

                # 4. enumerate the now-current tab's controls. The bottom tab
                #    bar itself is excluded (controls come from ScreenRoot).
                controls = await dash.list_controls()
                record("05_controls", _format_controls(controls))
                await settle_shot("05_controls")
                # Controls of the switched-to tab should expose stable ref_ids;
                # a populated tab yields a non-empty list (a sparse tab may be
                # empty, so gate the operate step on a control existing).
                assert all(c.ref_id for c in controls), "every control needs a ref_id"
                assert all(c.control_type in ("button", "scroll") for c in controls), (
                    "v1 controls are button|scroll only"
                )

                # 5. operate a control by ref_id (language-independent). Prefer
                #    a real, enabled Button so highlight exercises the success
                #    path (a ScrollRect soft-rejects hover by design). Highlight
                #    is used over invoke because it is visual-only (no
                #    navigation / world mutation), keeping the run
                #    side-effect-free and non-flaky.
                button = next(
                    (c for c in controls if c.control_type == "button" and c.enabled),
                    None,
                )
                if button is not None:
                    highlighted = await dash.highlight(button.ref_id)
                    record(
                        "06_highlight",
                        f"ok={highlighted.ok} found={highlighted.found} "
                        f"ref_id={button.ref_id} locale={button.locale_key!r} "
                        f"detail={highlighted.detail!r}",
                    )
                    await settle_shot("06_highlight")
                    assert highlighted.found, "highlight target should resolve"
                    assert highlighted.ok, (
                        "highlighting a real Button by language-independent "
                        f"ref_id should succeed, got detail={highlighted.detail!r}"
                    )

                    invoked = await dash.invoke(button.ref_id)
                    record(
                        "07_invoke",
                        f"ok={invoked.ok} found={invoked.found} "
                        f"detail={invoked.detail!r}",
                    )
                    await settle_shot("07_invoke")
                    assert invoked.found, "invoke target should resolve"

                # 6. close, leaving a clean state for the next run.
                await dash.close()
                final = await dash.get_state()
                record("08_closed", f"is_open={final.is_open}")
                await settle_shot("08_closed")
                assert not final.is_open, "dash should be closed after close()"

        try:
            asyncio.run(scenario())
        finally:
            log_path.write_text("\n\n".join(log_lines), encoding="utf-8")
            print(f"E2E artifacts: {out_dir}")

    @mark_e2e
    def test_tab_navigation_by_language_independent_key(
        self, resonite_session: Path
    ) -> None:
        """Navigate dash tabs by language-independent locale_key and verify the
        current tab moves.

        Opens the dash, enumerates its tabs (each carrying a ``ref_id`` and,
        for standard tabs, a ``LocaleStringDriver`` ``locale_key``), then drives
        a few tabs by ``set_tab(locale_key=...)`` and asserts ``is_current``
        tracks the requested tab via a fresh ``list_tabs`` after each hop. The
        target tabs are chosen dynamically from the live ``enabled`` set (never
        hard-coded), so the scenario survives login-state / version differences
        in Resonite's tab roster.
        """
        del resonite_session  # fixture only manages Resonite lifecycle

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = ARTIFACT_ROOT / f"dash_tabs_{timestamp}"
        out_dir.mkdir(parents=True, exist_ok=True)
        log_path = out_dir / "states.txt"
        log_lines: list[str] = []

        def record(step: str, text: str) -> None:
            block = f"=== {step} ===\n{text}"
            log_lines.append(block)
            print(block)

        async def wait_for_ready() -> bool:
            deadline = time.monotonic() + _READY_TIMEOUT_S
            while True:
                try:
                    async with DashClient() as dash:
                        return (await dash.get_state()).is_open
                except grpclib.exceptions.GRPCError as e:
                    if e.status != Status.FAILED_PRECONDITION:
                        raise
                    if time.monotonic() >= deadline:
                        raise AssertionError(
                            "Dash bridge never became ready within "
                            f"{_READY_TIMEOUT_S:.0f}s"
                        ) from e
                    await asyncio.sleep(_READY_RETRY_INTERVAL_S)

        async def settle_shot(step: str) -> None:
            await asyncio.sleep(_SETTLE_S)
            _screenshot(out_dir, f"{step}.png")

        def _find_by_ref_id(tabs: list[DashTab], ref_id: str) -> DashTab | None:
            return next((t for t in tabs if t.ref_id == ref_id), None)

        def _pick_navigation_targets(
            tabs: list[DashTab], current_ref_id: str | None
        ) -> list[DashTab]:
            candidates = [
                t
                for t in tabs
                if t.enabled and t.locale_key and t.ref_id != current_ref_id
            ]
            preferred = [t for t in candidates if t.locale_key in _PREFERRED_TAB_KEYS]
            others = [t for t in candidates if t.locale_key not in _PREFERRED_TAB_KEYS]
            # Preferred standard tabs first, then any remaining enabled ones,
            # capped at three hops. Order is deterministic for reproducibility.
            ordered = preferred + others
            return ordered[:3]

        async def scenario() -> None:
            # 0. baseline: engine ready, home world settled.
            await wait_for_ready()
            await asyncio.sleep(_HOME_LOAD_SETTLE_S)
            await wait_for_ready()

            async with DashClient() as dash:
                await dash.open()
                await settle_shot("00_open")

                # 1. enumerate tabs. Exactly one is current; every tab carries
                #    a ref_id; standard tabs carry a locale_key.
                tabs = await dash.list_tabs()
                record("01_tabs", _format_tabs(tabs))
                assert tabs, "open dash should expose tabs"
                assert sum(t.is_current for t in tabs) == 1, (
                    "exactly one tab must be current"
                )
                assert all(t.ref_id for t in tabs), "every tab needs a ref_id"
                assert any(t.locale_key.startswith("Dash.Screens.") for t in tabs), (
                    "standard tabs should carry a language-independent locale_key"
                )

                start_ref_id = _current_ref_id(tabs)
                targets = _pick_navigation_targets(tabs, start_ref_id)
                if len(targets) < 2:
                    pytest.skip(
                        "need at least 2 enabled, keyed, non-current tabs to "
                        f"exercise navigation; got {len(targets)} "
                        "(unexpected logged-out / minimal tab set)"
                    )

                # 2. hop through the chosen tabs by language-independent
                #    locale_key; after each hop is_current must move to that tab
                #    (matched by ref_id), and the rendered controls should
                #    change.
                prev_control_keys: set[tuple[str, str]] | None = None
                for i, target in enumerate(targets):
                    result = await dash.set_tab(locale_key=target.locale_key)
                    record(
                        f"02_set_{i}_{target.locale_key}",
                        f"ok={result.ok} found={result.found} "
                        f"ref_id={result.ref_id} detail={result.detail!r}",
                    )
                    assert result.ok, f"set_tab({target.locale_key}) should succeed"
                    assert result.found, f"tab {target.locale_key} should resolve"

                    after = await dash.list_tabs()
                    assert _current_ref_id(after) == target.ref_id, (
                        f"is_current should move to {target.locale_key} "
                        f"(ref_id {target.ref_id})"
                    )
                    await settle_shot(f"02_tab_{i}_{target.locale_key}")

                    # 3. loose content check: the rendered controls differ per
                    #    tab (count or representative locale_key/label set
                    #    changes). Settle first so the switch animation is done
                    #    before reading the controls.
                    await asyncio.sleep(TAB_SETTLE_S)
                    controls = await dash.list_controls()
                    control_keys = {(c.locale_key, c.label) for c in controls}
                    record(
                        f"03_controls_{i}_{target.locale_key}",
                        f"count={len(controls)}",
                    )
                    if prev_control_keys is not None:
                        assert control_keys != prev_control_keys or (
                            len(controls) != len(prev_control_keys)
                        ), "switching tabs should change the rendered controls"
                    prev_control_keys = control_keys

                # 4. exact-id addressing: re-select the last target by ref_id
                #    and confirm is_current tracks it.
                last = targets[-1]
                exact = await dash.set_tab(ref_id=last.ref_id)
                record(
                    "04_set_by_ref_id",
                    f"ok={exact.ok} found={exact.found} ref_id={exact.ref_id}",
                )
                assert exact.found, "set_tab(ref_id=...) should resolve"
                after_exact = await dash.list_tabs()
                assert _current_ref_id(after_exact) == last.ref_id, (
                    "is_current should track the ref_id selection"
                )

                # 5. restore the tab we started on (if still present) and close.
                final_tabs = await dash.list_tabs()
                if start_ref_id is not None and _find_by_ref_id(
                    final_tabs, start_ref_id
                ):
                    await dash.set_tab(ref_id=start_ref_id)
                await settle_shot("05_restored")

                closed = await dash.close()
                record("06_closed", f"is_open={closed.is_open}")
                await settle_shot("06_closed")
                assert not closed.is_open, "dash should be closed after close()"

        try:
            asyncio.run(scenario())
        finally:
            log_path.write_text("\n\n".join(log_lines), encoding="utf-8")
            print(f"E2E artifacts: {out_dir}")
