"""E2E: drive the Cursor modality against a live Resonite and screenshot.

``set_position`` establishes a *persistent hold*: the bridge registers a
cursor lock that pins the engine cursor at the target position until
``release`` is called. The returned snapshot is the settle-confirmed
measured position with ``held=True``. Because the hold survives the RPC,
a follow-up ``get_position`` — even over a **separate connection** — must
keep returning the set value with ``held=True``. That cross-RPC
observation is the core contract this test pins (it was impossible under
the old one-shot warp semantics, where the engine cursor reverted to the
OS pointer on the next frame on Wine/Proton).

The hold acts on the engine cursor only and never captures the OS mouse
pointer (no warp, no confine, no center pin); that half of the contract
is verified by the human/orchestrator on the host, not here.

Visual evidence: the desktop radial context menu opens at the cursor's
laser hit point, so opening it while holding at (0.25, 0.25) shows the
menu in the upper-left region of the window in the screenshot.

After ``release`` the hold is dropped: the release response and a
subsequent ``get_position`` both report ``held=False``. The teardown
always best-effort releases so a failed run does not leave the engine
cursor pinned for later tests or for a human at the machine.

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

# Cursor positions are pixel-quantized, so the normalized position in a
# snapshot differs from the request by at most ~1px / window-dimension.
# 0.01 comfortably covers that rounding for any realistic resolution.
_POS_TOL = 0.01

_HOLD_X = 0.25
_HOLD_Y = 0.25


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
    def test_hold_persists_across_rpcs_until_release(
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

        async def best_effort_release() -> None:
            """Teardown: never leave the engine cursor held."""
            try:
                async with CursorClient() as cur:
                    await cur.release()
            except Exception as e:  # noqa: BLE001 - teardown must not mask the test
                print(f"best-effort release failed (ignored): {e!r}")

        async def scenario() -> None:
            initial = await wait_for_ready()
            await asyncio.sleep(_HOME_LOAD_SETTLE_S)
            initial = await wait_for_ready()
            assert initial.window_width > 0 and initial.window_height > 0, (
                "window resolution should be known once the engine is ready"
            )
            assert initial.held is False, (
                "no hold should be active before the test sets one"
            )

            # 1. set: establishes the hold. The returned snapshot is the
            # settle-confirmed measured position with held=True.
            async with CursorClient() as cur:
                held = await cur.set_position(_HOLD_X, _HOLD_Y)
                assert held.x == pytest.approx(_HOLD_X, abs=_POS_TOL)
                assert held.y == pytest.approx(_HOLD_Y, abs=_POS_TOL)
                assert held.held is True

            # 2. cross-RPC observation over a *separate connection*: the
            # hold must survive the RPC that created it. This is the core
            # contract of the persistent-hold semantics.
            async with CursorClient() as cur:
                read = await cur.get_position()
                assert read.x == pytest.approx(_HOLD_X, abs=_POS_TOL)
                assert read.y == pytest.approx(_HOLD_Y, abs=_POS_TOL)
                assert read.held is True

            # 3. visual evidence: the radial menu opens at the (held)
            # cursor position, i.e. upper-left region of the window.
            async with ContextMenuClient() as cm:
                opened = await cm.open()
                await asyncio.sleep(_SETTLE_S)
                _screenshot(out_dir, "00_menu_at_held_position.png")
                assert opened.is_open, "context menu should open at the held cursor"
                await cm.close()
                await asyncio.sleep(_SETTLE_S)

            # 4. release: drops the hold. Both the release response and a
            # subsequent read must report held=False.
            async with CursorClient() as cur:
                released = await cur.release()
                assert released.held is False
                after = await cur.get_position()
                assert after.held is False

        async def run() -> None:
            try:
                await scenario()
            finally:
                await best_effort_release()

        try:
            asyncio.run(run())
        finally:
            print(f"E2E artifacts: {out_dir}")
