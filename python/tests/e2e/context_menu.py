"""E2E: drive the ContextMenu modality against a live Resonite and screenshot.

Each action (open / list / highlight / close / invoke) is followed by a
host-side desktop screenshot so the radial menu's appearance, item
highlight, and disappearance can be confirmed visually. The radial menu
is a local-user screen-space overlay (renderQueue 4000 / ZTest.Always),
so an in-world Camera frame would not capture it — we grab the actual
desktop window via the host-agent (`scripts/resonite_cli.py screenshot`).

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
from grpclib.const import Status

from resoio.context_menu import ContextMenuClient, ContextMenuState
from resoio.cursor import CursorClient
from tests.helpers import mark_e2e

# parents[2] is python/; the repo root (where scripts/ lives) is parents[3].
REPO_ROOT: Path = Path(__file__).resolve().parents[3]
ARTIFACT_ROOT = Path(__file__).parent / "e2e_artifacts"

# UDS bind and LocalUser/InteractionHandler readiness race: while the engine
# is still booting, the ContextMenu bridge raises ContextMenuNotReadyException
# → FAILED_PRECONDITION. Mirror camera_stream.py's readiness poll.
_READY_TIMEOUT_S = 120.0
_READY_RETRY_INTERVAL_S = 2.0

# The bridge becomes ready (FocusedWorld present) before the home world has
# finished loading + presenting. Give the home world ~20 s to settle after the
# first ready response so the desktop is fully rendered (cursor placed, world
# loaded) before driving the menu and grabbing screenshots.
_HOME_LOAD_SETTLE_S = 20.0

# Give the radial menu a moment to finish its open/close lerp + the renderer a
# frame to present before grabbing the desktop, so screenshots are not torn
# mid-animation. Kept short because the desktop radial menu is transient and
# auto-closes after a few seconds of no sustained summoning input — every
# open-dependent step below re-asserts open() (idempotent) to stay robust.
_SETTLE_S = 0.4


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


def _format_state(state: ContextMenuState) -> str:
    lines = [f"is_open={state.is_open} highlighted_index={state.highlighted_index}"]
    for item in state.items:
        lines.append(
            f"  [{item.index}] {item.label!r} enabled={item.enabled} "
            f"icon={item.has_icon} color={item.color}"
        )
    return "\n".join(lines)


class TestContextMenu:
    @mark_e2e
    def test_open_highlight_close_invoke(self, resonite_session: Path) -> None:
        del resonite_session  # fixture only manages Resonite lifecycle

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = ARTIFACT_ROOT / f"context_menu_{timestamp}"
        out_dir.mkdir(parents=True, exist_ok=True)
        log_path = out_dir / "states.txt"
        log_lines: list[str] = []

        def record(step: str, state: ContextMenuState) -> None:
            block = f"=== {step} ===\n{_format_state(state)}"
            log_lines.append(block)
            print(block)

        async def wait_for_ready() -> ContextMenuState:
            deadline = time.monotonic() + _READY_TIMEOUT_S
            while True:
                try:
                    async with ContextMenuClient() as cm:
                        return await cm.get_state()
                except grpclib.exceptions.GRPCError as e:
                    if e.status != Status.FAILED_PRECONDITION:
                        raise
                    if time.monotonic() >= deadline:
                        raise AssertionError(
                            "ContextMenu bridge never became ready "
                            f"within {_READY_TIMEOUT_S:.0f}s"
                        ) from e
                    await asyncio.sleep(_READY_RETRY_INTERVAL_S)

        async def settle_shot(step: str) -> None:
            await asyncio.sleep(_SETTLE_S)
            _screenshot(out_dir, f"{step}.png")

        async def scenario() -> None:
            # 0. baseline: engine ready, menu closed. Wait for the home world to
            #    finish loading/presenting before the first capture.
            initial = await wait_for_ready()
            await asyncio.sleep(_HOME_LOAD_SETTLE_S)
            initial = await wait_for_ready()
            record("00_initial", initial)
            await settle_shot("00_initial")
            assert not initial.is_open, "menu should start closed"

            # Center the cursor so the menu opens at screen center. The engine
            # positions the radial menu at the cursor's laser hit point, so
            # without this it would open wherever the cursor sits (bottom-left
            # right after startup). Best-effort: set_position is a one-shot
            # warp (position is not held after the RPC returns), so on Wine
            # the cursor may revert to the OS pointer before the menu opens —
            # menu placement in the screenshots is reference-only, and none of
            # the asserts below depend on it.
            async with CursorClient() as cur:
                await cur.set_position(0.5, 0.5)

            async with ContextMenuClient() as cm:
                # 1. open the T-key radial menu (populated with standard items).
                opened = await cm.open()
                record("01_open", opened)
                await settle_shot("01_open")
                assert opened.is_open, "menu should be open after open()"
                assert len(opened.items) > 0, "opened menu should expose items"
                item_count = len(opened.items)
                # first enabled item — invoking a disabled one would be a no-op.
                enabled_index = next((i.index for i in opened.items if i.enabled), 0)

                # 2. list/get the items (read-only). open() is idempotent; re-assert
                #    it first since the radial may have auto-closed during the shot.
                await cm.open()
                listed = await cm.get_state()
                record("02_list", listed)
                await settle_shot("02_list")
                assert listed.is_open
                assert len(listed.items) == item_count

                # 3. highlight the first item (preview only, no action fired).
                await cm.open()
                hl0 = await cm.highlight(0)
                record("03_highlight_0", hl0)
                await settle_shot("03_highlight_0")
                assert hl0.highlighted_index == 0

                # 4. highlight a different item (distinguishes real highlight from
                #    a no-op / leftover state).
                if item_count >= 2:
                    await cm.open()
                    hl_last = await cm.highlight(item_count - 1)
                    record("04_highlight_last", hl_last)
                    await settle_shot("04_highlight_last")
                    assert hl_last.highlighted_index == item_count - 1

                # 5. close the menu explicitly.
                closed = await cm.close()
                record("05_closed", closed)
                await settle_shot("05_closed")
                assert not closed.is_open, "menu should be closed after close()"

                # 6. reopen and invoke an enabled item (fires its action; e.g. the
                #    Locomotion item opens a submenu — captured for inspection).
                reopened = await cm.open()
                record("06_reopened", reopened)
                await settle_shot("06_reopened")
                assert reopened.is_open

                invoked = await cm.invoke(enabled_index)
                record("07_invoked", invoked)
                await settle_shot("07_invoked")

                # leave a clean state for the next run.
                await cm.close()

        try:
            asyncio.run(scenario())
        finally:
            log_path.write_text("\n\n".join(log_lines), encoding="utf-8")
            print(f"E2E artifacts: {out_dir}")
