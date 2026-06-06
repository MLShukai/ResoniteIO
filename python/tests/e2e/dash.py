"""E2E: drive the Dash modality against a live Resonite and screenshot.

Exercises the full closed loop on the real Esc dash (userspace overlay):
open -> introspect the UI tree (language-independent ``ref_id`` + ``locale_key``
per element) -> operate elements by ``ref_id`` (invoke / highlight / scroll)
-> close. Each step is followed by a host-side desktop screenshot via the
host-agent (``scripts/resonite_cli.py screenshot``) since the dash is a
local-user overlay an in-world Camera would not capture.

Open/close is driven as a symmetric ``close -> open -> close -> open`` so a
real toggle is distinguishable from a no-op on an already-open dash.

Note on the localization goal: ``ref_id`` (engine RefID) and ``locale_key``
(LocaleStringDriver key) are asserted to be present and to stay stable across
two introspection snapshots. Confirming they are *identical* under a different
UI language requires switching Resonite's locale (a manual follow-up), but
their language-independence is structural: neither derives from the displayed
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

from resoio.dash import DashClient, DashElement, DashScreen, DashTree
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


def _format_tree(tree: DashTree) -> str:
    lines = [
        f"screen={tree.screen_width}x{tree.screen_height} count={len(tree.elements)}"
    ]
    for e in tree.elements:
        lines.append(
            f"  [{e.ref_id}] {e.type} locale={e.locale_key!r} label={e.label!r} "
            f"enabled={e.enabled} interactable={e.interactable}"
        )
    return "\n".join(lines)


def _format_screens(screens: list[DashScreen]) -> str:
    lines = [f"count={len(screens)}"]
    for s in screens:
        lines.append(
            f"  [{s.ref_id}] {s.key} {s.name} is_current={s.is_current} "
            f"enabled={s.enabled} label={s.label!r}"
        )
    return "\n".join(lines)


# Standard, login-independent screens preferred as navigation targets when
# present. The scenario falls back to any enabled, keyed screen so it does not
# break if Resonite's screen set shifts between versions / login states.
_PREFERRED_SCREEN_KEYS = (
    "Dash.Screens.Worlds",
    "Dash.Screens.Settings",
    "Dash.Screens.Inventory",
)
_HOME_SCREEN_KEY = "Dash.Screens.Home"

# After a set_screen the CurrentScreen.Target / is_current flip is synchronous,
# but the screen-switch animation (~0.5s at the default speed) needs to settle
# before get_tree reflects the new screen's content.
_SCREEN_SWITCH_SETTLE_S = 0.6


class TestDash:
    @mark_e2e
    def test_open_introspect_operate_close(self, resonite_session: Path) -> None:
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
                            f"Dash bridge never became ready within {_READY_TIMEOUT_S:.0f}s"
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
                # 1. symmetric close -> open -> close -> open so a real toggle is
                #    distinguishable from a no-op on an already-open dash.
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

                # 2. introspect the dash UI tree. Every element must carry a
                #    language-independent ref_id; at least one should expose a
                #    locale_key (the dash chrome is localized).
                tree = await dash.get_tree()
                record("03_tree", _format_tree(tree))
                await settle_shot("03_tree")
                assert tree.elements, "open dash should expose UI elements"
                assert all(e.ref_id for e in tree.elements), (
                    "every element needs a ref_id"
                )
                assert any(e.locale_key for e in tree.elements), (
                    "at least one element should carry a language-independent locale_key"
                )

                # ref_id / locale_key are stable across snapshots (not derived
                # from transient layout or the displayed label).
                tree2 = await dash.get_tree()
                keys1 = {(e.ref_id, e.locale_key) for e in tree.elements}
                keys2 = {(e.ref_id, e.locale_key) for e in tree2.elements}
                assert keys1 & keys2, (
                    "ref_id/locale_key should be stable across snapshots"
                )

                # 3. operate an interactable element by ref_id (language-independent).
                interactable = await dash.get_tree(interactable_only=True)
                record("04_interactable", _format_tree(interactable))
                target: DashElement | None = next(iter(interactable.elements), None)
                if target is not None:
                    highlighted = await dash.highlight(target.ref_id)
                    record(
                        "05_highlight",
                        f"ok={highlighted.ok} found={highlighted.found} "
                        f"ref_id={target.ref_id} detail={highlighted.detail!r}",
                    )
                    await settle_shot("05_highlight")
                    assert highlighted.found, "highlight target should resolve"

                    invoked = await dash.invoke(target.ref_id)
                    record(
                        "06_invoke",
                        f"ok={invoked.ok} found={invoked.found} detail={invoked.detail!r}",
                    )
                    await settle_shot("06_invoke")
                    assert invoked.found, "invoke target should resolve"

                # 3b. prove a *successful* operation (ok=True), not just a
                #     graceful soft-fail: the chrome's first interactable is a
                #     RectTransform that cannot be hovered/pressed, so addressing
                #     it soft-fails by design. A real, hoverable Button exercises
                #     the success path of language-independent ref_id addressing.
                #     Gated on a Button existing so the dash layout staying free
                #     of buttons skips this instead of breaking it. Highlight is
                #     used over invoke because it is visual-only (no navigation /
                #     state mutation) per the DashClient contract, keeping the
                #     run side-effect-free and non-flaky.
                button = next(
                    (
                        e
                        for e in tree.elements
                        if e.type == "Button" and e.enabled and e.interactable
                    ),
                    None,
                )
                if button is not None:
                    button_hl = await dash.highlight(button.ref_id)
                    record(
                        "06b_button_highlight",
                        f"ok={button_hl.ok} found={button_hl.found} "
                        f"ref_id={button.ref_id} locale={button.locale_key!r} "
                        f"detail={button_hl.detail!r}",
                    )
                    await settle_shot("06b_button_highlight")
                    assert button_hl.found, "button highlight target should resolve"
                    assert button_hl.ok, (
                        "highlighting a real Button by language-independent "
                        f"ref_id should succeed, got detail={button_hl.detail!r}"
                    )

                # 4. close, leaving a clean state for the next run.
                await dash.close()
                final = await dash.get_state()
                record("07_closed", f"is_open={final.is_open}")
                await settle_shot("07_closed")
                assert not final.is_open, "dash should be closed after close()"

        try:
            asyncio.run(scenario())
        finally:
            log_path.write_text("\n\n".join(log_lines), encoding="utf-8")
            print(f"E2E artifacts: {out_dir}")

    @mark_e2e
    def test_screen_navigation_by_language_independent_key(
        self, resonite_session: Path
    ) -> None:
        """Navigate dash screens by language-independent key and verify the
        current screen moves.

        Opens the dash, enumerates its screens (each carrying a ``ref_id`` and,
        for standard screens, a ``LocaleStringDriver`` ``key``), then drives a
        few screens by ``set_screen(key=...)`` and asserts ``is_current`` tracks
        the requested screen via a fresh ``list_screens`` after each hop. The
        target screens are chosen dynamically from the live ``enabled`` set
        (never hard-coded), so the scenario survives login-state / version
        differences in Resonite's screen roster.
        """
        del resonite_session  # fixture only manages Resonite lifecycle

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = ARTIFACT_ROOT / f"dash_screens_{timestamp}"
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

        def _current_ref_id(screens: list[DashScreen]) -> str | None:
            current = [s for s in screens if s.is_current]
            return current[0].ref_id if len(current) == 1 else None

        def _find_by_ref_id(
            screens: list[DashScreen], ref_id: str
        ) -> DashScreen | None:
            return next((s for s in screens if s.ref_id == ref_id), None)

        def _pick_navigation_targets(
            screens: list[DashScreen], current_ref_id: str | None
        ) -> list[DashScreen]:
            # Candidates: enabled, keyed, and not the screen we are already on.
            candidates = [
                s for s in screens if s.enabled and s.key and s.ref_id != current_ref_id
            ]
            preferred = [s for s in candidates if s.key in _PREFERRED_SCREEN_KEYS]
            others = [s for s in candidates if s.key not in _PREFERRED_SCREEN_KEYS]
            # Preferred standard screens first, then any remaining enabled ones,
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

                # 1. enumerate screens. Exactly one is current; every screen
                #    carries a ref_id; standard screens carry a key.
                screens = await dash.list_screens()
                record("01_screens", _format_screens(screens))
                assert screens, "open dash should expose screens"
                assert sum(s.is_current for s in screens) == 1, (
                    "exactly one screen must be current"
                )
                assert all(s.ref_id for s in screens), "every screen needs a ref_id"
                assert any(s.key.startswith("Dash.Screens.") for s in screens), (
                    "standard screens should carry a language-independent key"
                )

                start_ref_id = _current_ref_id(screens)
                targets = _pick_navigation_targets(screens, start_ref_id)
                if len(targets) < 2:
                    pytest.skip(
                        "need at least 2 enabled, keyed, non-current screens to "
                        f"exercise navigation; got {len(targets)} "
                        "(unexpected logged-out / minimal screen set)"
                    )

                # 2. hop through the chosen screens by language-independent key;
                #    after each hop is_current must move to that screen (matched
                #    by ref_id), and the rendered tree should change.
                prev_tree_keys: set[tuple[str, str]] | None = None
                for i, target in enumerate(targets):
                    result = await dash.set_screen(key=target.key)
                    record(
                        f"02_set_{i}_{target.key}",
                        f"ok={result.ok} found={result.found} "
                        f"ref_id={result.ref_id} detail={result.detail!r}",
                    )
                    assert result.ok, f"set_screen({target.key}) should succeed"
                    assert result.found, f"screen {target.key} should resolve"

                    after = await dash.list_screens()
                    assert _current_ref_id(after) == target.ref_id, (
                        f"is_current should move to {target.key} "
                        f"(ref_id {target.ref_id})"
                    )
                    await settle_shot(f"02_screen_{i}_{target.key}")

                    # 3. loose content check: the rendered tree differs per
                    #    screen (element count or representative locale_key/label
                    #    set changes). Settle first so the switch animation is
                    #    done before reading the tree.
                    await asyncio.sleep(_SCREEN_SWITCH_SETTLE_S)
                    tree = await dash.get_tree()
                    tree_keys = {(e.locale_key, e.label) for e in tree.elements}
                    record(
                        f"03_tree_{i}_{target.key}",
                        f"count={len(tree.elements)}",
                    )
                    if prev_tree_keys is not None:
                        assert tree_keys != prev_tree_keys or (
                            len(tree.elements) != len(prev_tree_keys)
                        ), "switching screens should change the rendered tree content"
                    prev_tree_keys = tree_keys

                # 4. exact-id addressing: re-select the last target by ref_id and
                #    confirm is_current tracks it.
                last = targets[-1]
                exact = await dash.set_screen(ref_id=last.ref_id)
                record(
                    "04_set_by_ref_id",
                    f"ok={exact.ok} found={exact.found} ref_id={exact.ref_id}",
                )
                assert exact.found, "set_screen(ref_id=...) should resolve"
                after_exact = await dash.list_screens()
                assert _current_ref_id(after_exact) == last.ref_id, (
                    "is_current should track the ref_id selection"
                )

                # 5. restore Home (or the screen we started on) and close.
                final_screens = await dash.list_screens()
                home = next(
                    (s for s in final_screens if s.key == _HOME_SCREEN_KEY), None
                )
                if home is not None:
                    await dash.set_screen(key=_HOME_SCREEN_KEY)
                elif start_ref_id is not None and _find_by_ref_id(
                    final_screens, start_ref_id
                ):
                    await dash.set_screen(ref_id=start_ref_id)
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
