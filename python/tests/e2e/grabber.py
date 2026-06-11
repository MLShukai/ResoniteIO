"""E2E: drive the Grabber modality against a live Resonite.

This verifies the Grabber RPC path (``get_state`` / ``grab`` /
``release``) end-to-end against a live Resonite: the mod loads, the
bridge reaches the real per-hand ``Grabber`` without throwing, responses
are well-formed, and the requested hand resolves correctly
(``left`` → left, ``right`` → right, ``primary`` → the engine's primary
hand, which is the right hand per ``InputInterface.PrimaryHand``).

Grab is cursor-ray based: it picks a grabbable within ``radius`` metres of
the point where the desktop cursor ray hits the world (aim with
``CursorClient.set_position`` first; VR mode is rejected with
``FAILED_PRECONDITION``).

A *positive* grab is asserted here: ``InventoryClient.spawn`` with the
Resonite Essentials Mirror (``/Inventory/Resonite Essentials/Mirror``)
deterministically places a grabbable Mirror in front of the avatar, so the
test spawns it, holds the cursor over it, and requires ``grabbed=True``
with ``"Mirror"`` in ``object_names``. ``release`` then must report
``is_holding=False``. The spawned Mirror's exact screen position can drift
slightly run to run, so the grab retries a few nearby aim points before
failing. The only remaining human-only checks (the object visually
following the hand, and the VR ``FAILED_PRECONDITION`` rejection) live in
``mod/tests/manual/grabber-verification.md``.

There is no API to delete the spawned Mirror from the world, so the test
releases it and leaves it in place; the local home world resets on the
next Resonite start (the ``resonite_session`` fixture restarts Resonite
per test anyway).

Screenshots are taken purely for the record (the desktop view around the
spawn/grab/release calls); the hard assertions are the RPC contract and
the positive grab, not pixel content.

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
from resoio.grabber import GrabberClient, GrabResult, GrabState
from resoio.inventory import InventoryClient
from tests.helpers import mark_e2e

# parents[2] is python/; the repo root (where scripts/ lives) is parents[3].
REPO_ROOT: Path = Path(__file__).resolve().parents[3]
ARTIFACT_ROOT = Path(__file__).parent / "e2e_artifacts"

# UDS bind and Grabber/LocalUser readiness race: while the engine is still
# booting, the Grabber bridge raises FAILED_PRECONDITION until the focused
# world and its per-hand Grabbers exist. Mirror context_menu.py's readiness poll.
_READY_TIMEOUT_S = 120.0
_READY_RETRY_INTERVAL_S = 2.0

# The bridge becomes ready (FocusedWorld present) before the home world has
# finished loading + presenting. Give the home world ~20 s to settle after the
# first ready response so the desktop is fully rendered before spawning the
# Mirror and driving the grab/release calls. Spawning too early after boot has
# been observed (once) to place the item away from the expected spot in front
# of the avatar, so this settle is also a flakiness guard for the spawn.
_HOME_LOAD_SETTLE_S = 20.0

# After the spawn RPC returns, the Mirror still tweens/settles into its place
# in front of the avatar; wait before aiming at it (5 s verified on hardware).
_SPAWN_SETTLE_S = 5.0

# Give the renderer a frame to present before grabbing the desktop, so
# screenshots are not torn mid-update.
_SETTLE_S = 0.4

# Inventory path of a known grabbable: the Resonite Essentials Mirror spawns
# in front of the avatar as a slot named "Mirror".
_MIRROR_INVENTORY_PATH = "/Inventory/Resonite Essentials/Mirror"
_MIRROR_SLOT_NAME = "Mirror"

# Aim points (normalized window coordinates) for the cursor-aimed positive
# grab, tried in order until one grab succeeds. (0.5, 0.45) is where the
# spawned Mirror lands on a verified run; the alternates cover the small
# run-to-run drift of the spawn position.
_AIM_POINTS: tuple[tuple[float, float], ...] = (
    (0.5, 0.45),
    (0.45, 0.5),
    (0.55, 0.4),
)
_GRAB_RADIUS = 0.5


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


class TestGrabber:
    @mark_e2e
    def test_spawned_mirror_positive_grab_and_release(
        self, resonite_session: Path
    ) -> None:
        del resonite_session  # fixture only manages Resonite lifecycle

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = ARTIFACT_ROOT / f"grabber_{timestamp}"
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
                    async with GrabberClient() as client:
                        return await client.get_state()
                except grpclib.exceptions.GRPCError as e:
                    if e.status != Status.FAILED_PRECONDITION:
                        raise
                    if time.monotonic() >= deadline:
                        raise AssertionError(
                            "Grabber bridge never became ready "
                            f"within {_READY_TIMEOUT_S:.0f}s"
                        ) from e
                    await asyncio.sleep(_READY_RETRY_INTERVAL_S)

        async def settle_shot(name: str) -> None:
            await asyncio.sleep(_SETTLE_S)
            _screenshot(out_dir, f"{name}.png")

        async def grab_with_aim_retries(
            client: GrabberClient, cursor: CursorClient
        ) -> GrabResult:
            """Aim at each candidate point in turn and grab; return the first
            successful result (or the last attempt's result if all miss).

            The spawned Mirror's screen position drifts slightly run to
            run, so a single fixed aim point would be flaky; retrying
            nearby points keeps the positive-grab assertion
            deterministic.
            """
            result: GrabResult | None = None
            for index, (aim_x, aim_y) in enumerate(_AIM_POINTS):
                await cursor.set_position(aim_x, aim_y)
                result = await client.grab(radius=_GRAB_RADIUS)
                record_result(f"05_grab_attempt_{index}_at_{aim_x}_{aim_y}", result)
                if result.grabbed:
                    return result
            assert result is not None  # _AIM_POINTS is non-empty
            return result

        async def scenario() -> None:
            # 0. baseline: engine ready, hands empty. Wait for the home world to
            #    finish loading/presenting before spawning anything (a too-early
            #    spawn has been observed to land away from the expected spot).
            initial = await wait_for_ready()
            await asyncio.sleep(_HOME_LOAD_SETTLE_S)
            initial = await wait_for_ready()
            record("00_initial", initial)
            await settle_shot("00_initial")
            assert not initial.is_holding, "hands should start empty"
            assert initial.hand in ("primary", "left", "right")

            async with GrabberClient() as client:
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

                # 2. spawn a known grabbable: the Resonite Essentials Mirror
                #    lands in front of the avatar as a slot named "Mirror".
                async with InventoryClient() as inventory:
                    spawned = await inventory.spawn(_MIRROR_INVENTORY_PATH)
                log_lines.append(
                    f"=== 04_spawn ===\nsource_path={spawned.source_path} "
                    f"slot_id={spawned.spawned_slot_id} "
                    f"slot_name={spawned.spawned_slot_name}"
                )
                assert spawned.spawned_slot_name == _MIRROR_SLOT_NAME
                await asyncio.sleep(_SPAWN_SETTLE_S)
                await settle_shot("01_after_spawn")

                # 3. positive grab: hold the cursor over the spawned Mirror and
                #    grab with an explicit radius. This exercises the full ray
                #    path (cursor position → view ray → raycast → proximity
                #    grab) on the real engine AND asserts the object is
                #    actually picked up. (The grabbed object tweens into the
                #    hand; its world position is not asserted — there is no
                #    position API for it.)
                async with CursorClient() as cursor:
                    grab_result = await grab_with_aim_retries(client, cursor)
                    await settle_shot("02_after_grab")
                    assert grab_result.grabbed, (
                        "grab should pick up the spawned Mirror "
                        f"(tried aim points {_AIM_POINTS})"
                    )
                    assert _MIRROR_SLOT_NAME in grab_result.state.object_names
                    assert grab_result.state.is_holding
                    assert grab_result.state.unix_nanos > 0
                    await cursor.release()

                # 4. release: the Mirror is dropped and the hand reports empty.
                release_state = await client.release()
                record("06_release", release_state)
                assert isinstance(release_state, GrabState)
                assert not release_state.is_holding
                assert release_state.unix_nanos > 0
                await settle_shot("03_after_release")

                # 5. idempotence: releasing an already-empty hand is a no-op
                #    that still returns is_holding False without error.
                release_again = await client.release()
                record("07_release_again", release_again)
                assert isinstance(release_again, GrabState)
                assert not release_again.is_holding

        async def best_effort_cleanup() -> None:
            """Teardown: never leave a grab hold or a cursor hold behind.

            The spawned Mirror itself cannot be deleted (no world-delete API);
            it is left released in the home world, which resets on the next
            Resonite start.
            """
            try:
                async with GrabberClient() as client:
                    await client.release()
            except Exception as e:  # noqa: BLE001 - teardown must not mask the test
                print(f"best-effort grabber release failed (ignored): {e!r}")
            try:
                async with CursorClient() as cursor:
                    await cursor.release()
            except Exception as e:  # noqa: BLE001 - teardown must not mask the test
                print(f"best-effort cursor release failed (ignored): {e!r}")

        async def run() -> None:
            try:
                await scenario()
            finally:
                await best_effort_cleanup()

        try:
            asyncio.run(run())
        finally:
            log_path.write_text("\n\n".join(log_lines), encoding="utf-8")
            print(f"E2E artifacts: {out_dir}")
