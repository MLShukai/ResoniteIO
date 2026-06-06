"""E2E: drive the Cursor modality against a live Resonite and screenshot.

The desktop cursor itself is not reliably visible in a screenshot, so we
verify cursor movement *indirectly* through the radial context menu: on
desktop the menu opens at the cursor's laser hit point, so opening the
menu after ``set_position`` shows the menu at the requested screen
location. Centering the cursor (0.5, 0.5) then a corner-ish position
(0.25, 0.25) and screenshotting the resulting menu position proves the
cursor actually moved in-engine. ``get_position`` is also round-tripped.

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

# Cursor positions are pixel-quantized, so the normalized read-back differs
# from the request by at most ~1px / window-dimension. 0.01 comfortably
# covers that rounding for any realistic resolution.
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
    def test_set_position_moves_cursor_and_menu_follows(
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
                # 1. center the cursor.
                centered = await cur.set_position(0.5, 0.5)
                assert centered.x == pytest.approx(0.5, abs=_POS_TOL)
                assert centered.y == pytest.approx(0.5, abs=_POS_TOL)
            # the menu opens at the (centered) cursor.
            await open_menu_shot("00_center.png")

            async with CursorClient() as cur:
                # 2. move the cursor to an off-center position.
                moved = await cur.set_position(0.25, 0.25)
                assert moved.x == pytest.approx(0.25, abs=_POS_TOL)
                assert moved.y == pytest.approx(0.25, abs=_POS_TOL)
                # read-back via get_position reflects the same position.
                read = await cur.get_position()
                assert read.x == pytest.approx(0.25, abs=_POS_TOL)
                assert read.y == pytest.approx(0.25, abs=_POS_TOL)
            # the menu now opens at the off-center cursor — the two screenshots
            # showing the menu at different positions prove the cursor moved.
            await open_menu_shot("01_off_center.png")

        try:
            asyncio.run(scenario())
        finally:
            print(f"E2E artifacts: {out_dir}")
