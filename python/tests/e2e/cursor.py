"""E2E: drive the Cursor modality against a live Resonite and screenshot.

``set_position`` is a *one-shot warp*: the bridge warps the cursor,
confirms via settle-poll that the engine observed the target, then
releases the short-lived cursor lock before returning. The returned
snapshot is the settle-confirmed measured position, so asserting it
against the target is the platform-independent contract this test pins.

The position is **not held** after the RPC returns. On Wine/Proton (the
standard environment for this project) OS pointer injection does not
work, so once the lock is released the engine cursor reverts to the real
OS pointer position on the next frame. Consequently no cross-RPC
observation is guaranteed to reflect the set value: a follow-up
``get_position`` is logged as reference output only (not asserted), and
the radial-menu screenshots — the menu opens at the cursor's laser hit
point, via a separate ContextMenu RPC — are best-effort visual evidence
(they demonstrate the move on native platforms; on Wine the menu may
open at the reverted OS cursor position instead).

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

from resoio.context_menu import ContextMenuClient
from resoio.cursor import CursorClient, CursorState
from tests.helpers import mark_e2e

# parents[2] is python/; the repo root (where scripts/ lives) is parents[3].
REPO_ROOT: Path = Path(__file__).resolve().parents[3]
ARTIFACT_ROOT = Path(__file__).parent / "e2e_artifacts"

_READY_TIMEOUT_S = 120.0
_READY_RETRY_INTERVAL_S = 2.0
_HOME_LOAD_SETTLE_S = 20.0
_SETTLE_S = 0.4

# Cursor positions are pixel-quantized, so the normalized position in the
# snapshot returned by set_position differs from the request by at most
# ~1px / window-dimension. 0.01 comfortably covers that rounding for any
# realistic resolution.
_POS_TOL = 0.01


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


class TestCursor:
    @mark_e2e
    def test_set_position_returns_settled_snapshot_at_target(
        self, resonite_session: Path
    ) -> None:
        del resonite_session  # fixture only manages Resonite lifecycle

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = ARTIFACT_ROOT / f"cursor_{timestamp}"
        out_dir.mkdir(parents=True, exist_ok=True)

        async def wait_for_ready() -> CursorState:
            deadline = time.monotonic() + _READY_TIMEOUT_S
            while True:
                try:
                    async with CursorClient() as cur:
                        return await cur.get_position()
                except grpclib.exceptions.GRPCError as e:
                    if (
                        e.status != Status.FAILED_PRECONDITION
                        or time.monotonic() >= deadline
                    ):
                        raise
                    await asyncio.sleep(_READY_RETRY_INTERVAL_S)

        async def open_menu_shot(name: str) -> None:
            async with ContextMenuClient() as cm:
                opened = await cm.open()
                await asyncio.sleep(_SETTLE_S)
                _screenshot(out_dir, name)
                assert opened.is_open, "context menu should open at the cursor"
                await cm.close()
                await asyncio.sleep(_SETTLE_S)

        async def scenario() -> None:
            initial = await wait_for_ready()
            await asyncio.sleep(_HOME_LOAD_SETTLE_S)
            initial = await wait_for_ready()
            assert initial.window_width > 0 and initial.window_height > 0, (
                "window resolution should be known once the engine is ready"
            )

            async with CursorClient() as cur:
                # 1. center the cursor. The returned snapshot is the
                # settle-confirmed measured position — the spec contract.
                centered = await cur.set_position(0.5, 0.5)
                assert centered.x == pytest.approx(0.5, abs=_POS_TOL)
                assert centered.y == pytest.approx(0.5, abs=_POS_TOL)
            # best-effort visual evidence: on native the menu opens at the
            # (centered) cursor; on Wine the one-shot warp has already been
            # released, so the menu may open at the reverted OS position.
            await open_menu_shot("00_center.png")

            async with CursorClient() as cur:
                # 2. move the cursor to an off-center position. Again only the
                # set_position return snapshot is asserted (one-shot warp).
                moved = await cur.set_position(0.25, 0.25)
                assert moved.x == pytest.approx(0.25, abs=_POS_TOL)
                assert moved.y == pytest.approx(0.25, abs=_POS_TOL)
                # Cross-RPC read-back is NOT asserted: set_position releases
                # the cursor lock before returning, so on Wine the engine
                # cursor reverts to the OS pointer on the next frame and
                # get_position may no longer return the set value. Reference
                # output only.
                read = await cur.get_position()
                print(
                    "get_position after one-shot warp (reference, not asserted): "
                    f"x={read.x} y={read.y}"
                )
            # best-effort visual evidence (see module docstring): on native
            # the two screenshots show the menu at different positions.
            await open_menu_shot("01_off_center.png")

        try:
            asyncio.run(scenario())
        finally:
            print(f"E2E artifacts: {out_dir}")
