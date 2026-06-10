"""E2E: drive the Manipulation modality against a live Resonite.

This verifies the Manipulation RPC path (``get_state`` / ``grab`` /
``release``) end-to-end against a live Resonite: the mod loads, the
bridge reaches the real per-hand ``Grabber`` without throwing, responses
are well-formed, and the requested hand resolves correctly
(``left`` → left, ``right`` → right, ``primary`` → the engine's primary
hand, which is the right hand per ``InputInterface.PrimaryHand``).

Grab is cursor-ray based: it picks a grabbable within ``radius`` metres of
the point where the desktop cursor ray hits the world (aim with
``CursorClient.set_position`` first; VR mode is rejected with
``FAILED_PRECONDITION``). A *positive* grab (an object actually picked up,
``grabbed`` / ``is_holding`` becoming ``True``, and the object visually
following the hand) is intentionally NOT asserted here: the default local
home world exposes no grabbable object, and there is no API to
deterministically spawn one. So a ``grab`` against the empty home reports
``grabbed=False`` without error — the *call path* (cursor aim → ray
computation → raycast → proximity grab) is what is under test. The
positive-grab visual confirmation is a human-only check documented in
``mod/tests/manual/manipulation-verification.md``.

Screenshots are taken purely for the record (the desktop view before and
after the grab/release calls); the hard assertions are the RPC contract,
not pixel content.

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

from resoio.cursor import CursorClient
from resoio.manipulation import GrabResult, GrabState, ManipulationClient
from tests.helpers import mark_e2e

# parents[2] is python/; the repo root (where scripts/ lives) is parents[3].
REPO_ROOT: Path = Path(__file__).resolve().parents[3]
ARTIFACT_ROOT = Path(__file__).parent / "e2e_artifacts"

# UDS bind and Grabber/LocalUser readiness race: while the engine is still
# booting, the Manipulation bridge raises FAILED_PRECONDITION until the focused
# world and its per-hand Grabbers exist. Mirror context_menu.py's readiness poll.
_READY_TIMEOUT_S = 120.0
_READY_RETRY_INTERVAL_S = 2.0

# The bridge becomes ready (FocusedWorld present) before the home world has
# finished loading + presenting. Give the home world ~20 s to settle after the
# first ready response so the desktop is fully rendered before driving the
# grab/release calls and grabbing screenshots.
_HOME_LOAD_SETTLE_S = 20.0

# Give the renderer a frame to present before grabbing the desktop, so
# screenshots are not torn mid-update.
_SETTLE_S = 0.4

# Aim point (normalized window coordinates) and grab radius for the
# cursor-aimed grab step. Screen centre is a deterministic aim; the home
# world has nothing grabbable there, so only the call path (cursor hold →
# ray → raycast → proximity grab) is asserted, not grabbed=True.
_AIM_X = 0.5
_AIM_Y = 0.5
_PROBE_RADIUS = 0.5


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


def _format_state(state: GrabState) -> str:
    names = ", ".join(state.object_names)
    return (
        f"hand={state.hand} is_holding={state.is_holding} "
        f"objects=[{names}] unix_nanos={state.unix_nanos}"
    )


class TestManipulation:
    @mark_e2e
    def test_get_state_grab_release_contract(self, resonite_session: Path) -> None:
        del resonite_session  # fixture only manages Resonite lifecycle

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = ARTIFACT_ROOT / f"manipulation_{timestamp}"
        out_dir.mkdir(parents=True, exist_ok=True)
        log_path = out_dir / "states.txt"
        log_lines: list[str] = []

        def record(step: str, state: GrabState) -> None:
            block = f"=== {step} ===\n{_format_state(state)}"
            log_lines.append(block)
            print(block)

        def record_result(step: str, result: GrabResult) -> None:
            block = (
                f"=== {step} ===\n"
                f"grabbed={result.grabbed}\n{_format_state(result.state)}"
            )
            log_lines.append(block)
            print(block)

        async def wait_for_ready() -> GrabState:
            deadline = time.monotonic() + _READY_TIMEOUT_S
            while True:
                try:
                    async with ManipulationClient() as client:
                        return await client.get_state()
                except grpclib.exceptions.GRPCError as e:
                    if e.status != Status.FAILED_PRECONDITION:
                        raise
                    if time.monotonic() >= deadline:
                        raise AssertionError(
                            "Manipulation bridge never became ready "
                            f"within {_READY_TIMEOUT_S:.0f}s"
                        ) from e
                    await asyncio.sleep(_READY_RETRY_INTERVAL_S)

        async def settle_shot(name: str) -> None:
            await asyncio.sleep(_SETTLE_S)
            _screenshot(out_dir, f"{name}.png")

        async def scenario() -> None:
            # 0. baseline: engine ready, hands empty. Wait for the home world to
            #    finish loading/presenting before the first capture.
            initial = await wait_for_ready()
            await asyncio.sleep(_HOME_LOAD_SETTLE_S)
            initial = await wait_for_ready()
            record("00_initial", initial)
            await settle_shot("00_initial")
            assert not initial.is_holding, "hands should start empty"
            # "primary" resolves to a concrete hand (never "primary" echoed back
            # is fine — the bridge maps PRIMARY/UNSPECIFIED to "primary", but the
            # engine's primary hand is right; what we require is a real hand for
            # the per-hand queries below).
            assert initial.hand in ("primary", "left", "right")

            async with ManipulationClient() as client:
                # 1. per-hand get_state: each hand resolves correctly and stamps
                #    a real unix_nanos. left → "left", right → "right", and
                #    primary resolves to the same concrete hand as right
                #    (InputInterface.PrimaryHand is the right hand).
                primary_state = await client.get_state(hand="primary")
                record("01_state_primary", primary_state)
                assert isinstance(primary_state, GrabState)
                assert primary_state.unix_nanos > 0

                left_state = await client.get_state(hand="left")
                record("02_state_left", left_state)
                assert isinstance(left_state, GrabState)
                assert left_state.hand == "left"
                assert left_state.unix_nanos > 0

                right_state = await client.get_state(hand="right")
                record("03_state_right", right_state)
                assert isinstance(right_state, GrabState)
                assert right_state.hand == "right"
                assert right_state.unix_nanos > 0

                # primary maps to the right hand on the engine side; the bridge
                # echoes "right" for the resolved primary hand.
                assert primary_state.hand == right_state.hand

                # 2. grab at the current cursor ray (default radius). This must
                #    return a well-formed GrabResult without raising. We do NOT
                #    assert grabbed is True: the home world has nothing grabbable
                #    where the ray lands, so grabbed is typically False — the
                #    call path is what is under test.
                grab_primary = await client.grab(hand="primary")
                record_result("04_grab_primary", grab_primary)
                assert isinstance(grab_primary, GrabResult)
                assert isinstance(grab_primary.state, GrabState)
                assert grab_primary.state.unix_nanos > 0
                await settle_shot("01_after_grab")

                # 3. cursor aim → grab: hold the in-engine cursor at screen
                #    centre (Part A hold) so the grab targets a deterministic
                #    ray, then grab with an explicit radius. This exercises the
                #    full ray path (cursor position → view ray → raycast →
                #    proximity grab) on the real engine. Only the call path is
                #    asserted (no grabbable at screen centre in the home world).
                async with CursorClient() as cursor:
                    try:
                        await cursor.set_position(_AIM_X, _AIM_Y)
                        grab_aimed = await client.grab(
                            hand="left", radius=_PROBE_RADIUS
                        )
                        record_result("05_grab_left_cursor_aimed", grab_aimed)
                        assert isinstance(grab_aimed, GrabResult)
                        assert isinstance(grab_aimed.state, GrabState)
                        assert grab_aimed.state.unix_nanos > 0
                    finally:
                        # Best-effort: never leave a cursor hold behind for
                        # later steps / other e2e scenarios.
                        try:
                            await cursor.release()
                        except grpclib.exceptions.GRPCError:
                            pass

                # 4. release both hands: returns a GrabState with is_holding
                #    False (nothing was held, but release is well-defined).
                release_primary = await client.release(hand="primary")
                record("06_release_primary", release_primary)
                assert isinstance(release_primary, GrabState)
                assert not release_primary.is_holding
                assert release_primary.unix_nanos > 0

                release_left = await client.release(hand="left")
                record("07_release_left", release_left)
                assert isinstance(release_left, GrabState)
                assert not release_left.is_holding
                await settle_shot("02_after_release")

                # 5. idempotence: releasing an already-empty hand is a no-op that
                #    still returns is_holding False without error.
                release_again = await client.release(hand="primary")
                record("08_release_again", release_again)
                assert isinstance(release_again, GrabState)
                assert not release_again.is_holding

        try:
            asyncio.run(scenario())
        finally:
            log_path.write_text("\n\n".join(log_lines), encoding="utf-8")
            print(f"E2E artifacts: {out_dir}")
