"""E2E: drive the World modality against a live Resonite and screenshot.

Exercises the real ``WorldClient`` over the live UDS: browse live
sessions / records, join a session (Nest), inspect open worlds, focus a
different one, and leave. Each state-changing step asserts the API return
value AND grabs a host-side desktop screenshot so the world transition
(loading screen, the joined world's environment, the focus switch) can be
confirmed visually — an in-world Camera frame would only show one world's
render, whereas the desktop window shows whichever world is focused.

Like every file under ``tests/e2e/`` this requires the host-side
``just host-agent`` daemon plus a live, **logged-in** Resonite client; the
``require_host_agent`` autouse fixture skips when the agent is absent. The
cloud-dependent steps (sessions / records) degrade to a clear skip when
the account sees an empty cloud, but the join/focus/leave asserts are the
core of the scenario.
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

from resoio.world import OpenWorld, RecordSort, RecordSource, WorldClient
from tests.helpers import mark_e2e

# parents[2] is python/; the repo root (where scripts/ lives) is parents[3].
REPO_ROOT: Path = Path(__file__).resolve().parents[3]
ARTIFACT_ROOT = Path(__file__).parent / "e2e_artifacts"

# UDS bind + cloud/engine readiness race: while the engine is still booting
# (or the cloud session has not finished authenticating) the World bridge
# raises WorldNotReadyException -> FAILED_PRECONDITION. Poll like
# context_menu.py.
_READY_TIMEOUT_S = 120.0
_READY_RETRY_INTERVAL_S = 2.0

# The bridge becomes ready before the home world has finished loading +
# presenting. Give the home world time to settle so the first screenshots
# show a fully rendered desktop.
_HOME_LOAD_SETTLE_S = 20.0

# Joining / focusing / leaving a world triggers async world load + present.
# Give the renderer a generous window to finish the transition before the
# screenshot so the captured frame is the target world, not a loading
# screen.
_WORLD_TRANSITION_SETTLE_S = 15.0


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


def _format_world(world: OpenWorld | None) -> str:
    if world is None:
        return "<userspace / no focused world>"
    return (
        f"handle={world.handle} session_id={world.session_id!r} "
        f"name={world.name!r} focused={world.focused} "
        f"users={world.user_count} access={world.access_level!r}"
    )


class TestWorld:
    @mark_e2e
    def test_browse_join_focus_leave(self, resonite_session: Path) -> None:
        del resonite_session  # fixture only manages Resonite lifecycle

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = ARTIFACT_ROOT / f"world_{timestamp}"
        out_dir.mkdir(parents=True, exist_ok=True)
        log_path = out_dir / "states.txt"
        log_lines: list[str] = []

        def record(step: str, body: str) -> None:
            block = f"=== {step} ===\n{body}"
            log_lines.append(block)
            print(block)

        async def wait_for_ready() -> None:
            """Block until World RPCs stop returning FAILED_PRECONDITION."""
            deadline = time.monotonic() + _READY_TIMEOUT_S
            while True:
                try:
                    async with WorldClient() as world:
                        await world.list_open_worlds()
                    return
                except grpclib.exceptions.GRPCError as e:
                    if e.status != Status.FAILED_PRECONDITION:
                        raise
                    if time.monotonic() >= deadline:
                        raise AssertionError(
                            "World bridge never became ready within "
                            f"{_READY_TIMEOUT_S:.0f}s"
                        ) from e
                    await asyncio.sleep(_READY_RETRY_INTERVAL_S)

        async def settle_shot(step: str, settle_s: float) -> None:
            await asyncio.sleep(settle_s)
            _screenshot(out_dir, f"{step}.png")

        async def scenario() -> None:
            # 0. baseline: engine ready, home world loaded + presented.
            await wait_for_ready()
            await asyncio.sleep(_HOME_LOAD_SETTLE_S)
            await wait_for_ready()

            async with WorldClient() as world:
                # 1. list live sessions. Need >=1 joinable session to drive
                #    the rest; degrade to a clear skip on an empty cloud.
                page = await world.list_sessions()
                record(
                    "01_sessions",
                    f"total_count={page.total_count} returned={len(page.sessions)}\n"
                    + "\n".join(
                        f"  {s.session_id!r} {s.name!r} host={s.host_username!r} "
                        f"active={s.active_users} access={s.access_level!r}"
                        for s in page.sessions
                    ),
                )
                if not page.sessions:
                    pytest.skip(
                        "No live sessions visible to this account; cannot drive "
                        "the join/focus/leave scenario (needs a non-empty cloud)."
                    )
                target = page.sessions[0]
                assert target.session_id, "first session must carry a session_id"

                # 2. join the first session (Nest keeps the home world).
                await settle_shot("02_before_join", 0.5)
                joined = await world.join(session_id=target.session_id)
                record("03_joined", _format_world(joined))
                await settle_shot("03_after_join", _WORLD_TRANSITION_SETTLE_S)
                assert joined.session_id == target.session_id

                # get_current must reflect the world we just joined.
                current = await world.get_current()
                record("04_current_after_join", _format_world(current))
                assert current is not None, "a focused world is expected after join"
                assert current.session_id == joined.session_id, (
                    "get_current must report the just-joined world"
                )

                # 3. the joined world must appear in the open-world list (Nest
                #    keeps prior worlds open alongside it).
                open_worlds = await world.list_open_worlds()
                record(
                    "05_open_worlds",
                    "\n".join(_format_world(w) for w in open_worlds),
                )
                assert any(w.session_id == joined.session_id for w in open_worlds), (
                    "joined world must be present among the open worlds"
                )
                joined_count = len(open_worlds)
                assert joined_count >= 1

                # 4. focus a *different* open world if one exists (e.g. the
                #    home/userspace world Nest kept open), then assert the
                #    switch took effect.
                others = [w for w in open_worlds if w.session_id != joined.session_id]
                if others:
                    other = others[0]
                    await settle_shot("06_before_focus", 0.5)
                    focused = await world.focus(other.handle)
                    record("07_focused_other", _format_world(focused))
                    await settle_shot("07_after_focus", _WORLD_TRANSITION_SETTLE_S)
                    assert focused.handle == other.handle
                    now_current = await world.get_current()
                    record("08_current_after_focus", _format_world(now_current))
                    assert now_current is not None
                    assert now_current.handle == other.handle, (
                        "get_current must reflect the focus switch"
                    )

                # 5. leave the joined world; the open-world count must drop.
                await world.leave(joined.handle)
                after_leave = await world.list_open_worlds()
                record(
                    "09_open_worlds_after_leave",
                    "\n".join(_format_world(w) for w in after_leave),
                )
                await settle_shot("09_after_leave", _WORLD_TRANSITION_SETTLE_S)
                assert len(after_leave) < joined_count, (
                    "leaving a world must reduce the open-world count"
                )
                assert not any(
                    w.session_id == joined.session_id for w in after_leave
                ), "the left world must no longer be open"

                # 6. record browsing: a plain OWN list and a RANDOM sort must
                #    both return without error (content varies per account, so
                #    only the call's success is asserted).
                own = await world.list_records(source=RecordSource.OWN)
                record(
                    "10_records_own",
                    f"returned={len(own.records)} has_more={own.has_more} "
                    f"offset={own.offset}",
                )
                random_page = await world.list_records(
                    source=RecordSource.PUBLIC, sort=RecordSort.RANDOM, count=5
                )
                record(
                    "11_records_random",
                    f"returned={len(random_page.records)} "
                    f"has_more={random_page.has_more}",
                )

        try:
            asyncio.run(scenario())
        finally:
            log_path.write_text("\n\n".join(log_lines), encoding="utf-8")
            print(f"E2E artifacts: {out_dir}")
