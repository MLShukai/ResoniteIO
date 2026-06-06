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
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import grpclib
import pytest
from grpclib.const import Status

from resoio.world import (
    OpenWorld,
    RecordSort,
    RecordSource,
    WorldClient,
    WorldSession,
)
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


# Cap how many candidates we attempt so a hostile cloud can't stall the run.
_MAX_JOIN_CANDIDATES = 6
_MAX_START_CANDIDATES = 5


async def _acquire_world(
    world: WorldClient,
    sessions: list[WorldSession],
    record: Callable[[str, str], None],
) -> OpenWorld:
    """Move into a world and return its ``OpenWorld``.

    Public sessions vary in compatibility / access, so any single join can
    be legitimately rejected (the bridge surfaces that as
    ``FAILED_PRECONDITION``). Try several joinable candidates (``Anyone``
    access, proven-loadable ones — those with active users — first), then
    fall back to starting one of our OWN world records. ``pytest.skip`` only
    if neither path yields a running world.
    """
    candidates = [s for s in sessions if s.session_id and s.access_level == "Anyone"]
    candidates.sort(key=lambda s: s.active_users, reverse=True)
    tried: list[str] = []

    for cand in candidates[:_MAX_JOIN_CANDIDATES]:
        try:
            joined = await world.join(session_id=cand.session_id)
            record(
                "02b_acquire",
                f"joined live session {cand.session_id!r} ({cand.name!r}) "
                f"after {len(tried)} rejected candidate(s)",
            )
            return joined
        except grpclib.exceptions.GRPCError as exc:
            tried.append(f"join {cand.session_id!r}: {exc.status.name} {exc.message!r}")

    # Fallback: start one of our own world records (deterministic, always
    # version-compatible, fast to reach Running).
    own = await world.list_records(source=RecordSource.OWN, count=10)
    for own_rec in own.records[:_MAX_START_CANDIDATES]:
        try:
            started = await world.start_world(
                record_id=own_rec.record_id, owner_id=own_rec.owner_id
            )
            record(
                "02b_acquire",
                f"started OWN record {own_rec.record_id!r} ({own_rec.name!r}) "
                f"after {len(tried)} live-join rejection(s)",
            )
            return started
        except grpclib.exceptions.GRPCError as exc:
            tried.append(
                f"start {own_rec.record_id!r}: {exc.status.name} {exc.message!r}"
            )

    pytest.skip(
        "No joinable live session and no startable OWN world; cannot drive the "
        "movement scenario. Attempts:\n" + "\n".join(tried)
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
                # 2. move into a world: try joinable live sessions, falling
                #    back to starting an OWN world. Nest keeps the home world
                #    open alongside the new one.
                await settle_shot("02_before_join", 0.5)
                joined = await _acquire_world(world, page.sessions, record)
                record("03_joined", _format_world(joined))
                await settle_shot("03_after_join", _WORLD_TRANSITION_SETTLE_S)
                assert joined.session_id, (
                    "the joined/started world must carry a session_id"
                )
                # join/start default focus=True must report the world as
                # actually focused (the bridge waits for the engine to apply
                # the focus, not just queue it).
                assert joined.focused, (
                    "a focus-on-join world must be reported as focused"
                )

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
                # Require a session_id so we focus a real loaded world (e.g.
                # the home world Nest kept open), never a half-dead leftover.
                others = [
                    w
                    for w in open_worlds
                    if w.session_id and w.session_id != joined.session_id
                ]
                if others:
                    other = others[0]
                    await settle_shot("06_before_focus", 0.5)
                    focused = await world.focus(other.handle)
                    record("07_focused_other", _format_world(focused))
                    await settle_shot("07_after_focus", _WORLD_TRANSITION_SETTLE_S)
                    assert focused.handle == other.handle
                    # focus() must wait for the engine to apply the focus, so
                    # the returned snapshot must already report focused=True
                    # (previously it raced and returned focused=False).
                    assert focused.focused, (
                        "focus() must report the target world as focused"
                    )
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

                # 7. fetch a real thumbnail image and write it out as this
                #    step's visual artifact. Prefer resdb:/// record thumbnails
                #    (content-addressed, stable on assets.resonite.com) over
                #    https:// session thumbnails (which legitimately 404 on the
                #    CDN). Try candidates in that order until one yields bytes.
                record_uris = [r.thumbnail_url for r in own.records] + [
                    r.thumbnail_url for r in random_page.records
                ]
                session_uris = [s.thumbnail_url for s in page.sessions]
                all_uris = record_uris + session_uris
                resdb_uris = [u for u in all_uris if u.startswith("resdb:///")]
                http_uris = [u for u in all_uris if u.startswith("http")]
                candidates = resdb_uris + http_uris

                fetched = False
                failures: list[str] = []
                for uri in candidates[:8]:
                    try:
                        thumb = await world.fetch_thumbnail(uri)
                    except grpclib.exceptions.GRPCError as exc:
                        failures.append(f"{uri!r}: {exc.status.name} {exc.message!r}")
                        continue
                    assert len(thumb.data) > 0, (
                        "FetchThumbnail must return non-empty image bytes"
                    )
                    thumb_path = out_dir / "thumbnail.webp"
                    thumb_path.write_bytes(thumb.data)
                    record(
                        "12_thumbnail",
                        f"uri={uri!r} content_type={thumb.content_type!r} "
                        f"bytes={len(thumb.data)} -> {thumb_path.name} "
                        f"(after {len(failures)} failed candidate(s))",
                    )
                    fetched = True
                    break

                if not fetched:
                    detail = (
                        "\n".join(failures) if failures else "no thumbnail_url exposed"
                    )
                    # resdb thumbnails are content-addressed and must be
                    # fetchable; only a pure-https set that all 404 is an
                    # environment quirk we tolerate as a skip.
                    assert not resdb_uris, (
                        "every resdb:/// thumbnail failed to fetch; FetchThumbnail "
                        "is broken for the primary (content-addressed) case:\n" + detail
                    )
                    record(
                        "12_thumbnail",
                        "no fetchable thumbnail (https candidates all failed):\n"
                        + detail,
                    )

        try:
            asyncio.run(scenario())
        finally:
            log_path.write_text("\n\n".join(log_lines), encoding="utf-8")
            print(f"E2E artifacts: {out_dir}")
