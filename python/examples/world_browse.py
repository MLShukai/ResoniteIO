"""Minimal World browse -> join -> focus -> leave example.

Browses the live cloud session list, joins the first joinable session
(Nest keeps the home world open alongside it), lists the locally-open
worlds, focuses a different open world if Nest kept one, then leaves the
joined world. The cloud session list is environment-dependent: when no
joinable session is visible the script prints a notice and exits cleanly
instead of failing.

Requires a logged-in Resonite client (the session list is empty when
signed out).

Run from inside the dev container:

    uv run python python/examples/world_browse.py
"""

import asyncio
import time

import grpclib.exceptions
from grpclib.const import Status

from resoio import OpenWorld, WorldClient

SOCKET_PATH: str | None = None
READY_TIMEOUT_S = 120.0
READY_INTERVAL_S = 2.0


async def wait_for_ready() -> None:
    """Block until World.ListOpenWorlds stops returning FAILED_PRECONDITION.

    The bridge replies FAILED_PRECONDITION while the engine is booting
    or the cloud session has not finished authenticating. Retry until
    ready.
    """
    deadline = time.monotonic() + READY_TIMEOUT_S
    while True:
        try:
            async with WorldClient(SOCKET_PATH) as client:
                await client.list_open_worlds()
            return
        except grpclib.exceptions.GRPCError as e:
            if e.status != Status.FAILED_PRECONDITION:
                raise
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"World did not become ready in {READY_TIMEOUT_S:.0f}s"
                ) from e
            await asyncio.sleep(READY_INTERVAL_S)


def format_world(world: OpenWorld) -> str:
    return (
        f"handle={world.handle} session_id={world.session_id!r} "
        f"name={world.name!r} focused={world.focused} "
        f"users={world.user_count} access={world.access_level!r}"
    )


async def main() -> None:
    await wait_for_ready()
    async with WorldClient(SOCKET_PATH) as client:
        page = await client.list_sessions()
        print(f"sessions: total_count={page.total_count} returned={len(page.sessions)}")

        # Cloud-dependent step: with no joinable session there is nothing to
        # drive, so exit cleanly rather than fail.
        joinable = [s for s in page.sessions if s.session_id]
        if not joinable:
            print("no joinable session visible (empty cloud / signed out); done")
            return

        target = joinable[0]
        print(f"joining: {target.session_id!r} ({target.name!r})")
        joined = await client.join(session_id=target.session_id)
        print(f"joined: {format_world(joined)}")

        open_worlds = await client.list_open_worlds()
        print(f"open worlds: {len(open_worlds)}")
        for world in open_worlds:
            print(f"  {format_world(world)}")

        # Focus a different open world if Nest kept one (e.g. the home
        # world). Skipped when the joined world is the only one open.
        others = [
            w for w in open_worlds if w.session_id and w.session_id != joined.session_id
        ]
        if others:
            focused = await client.focus(others[0].handle)
            print(f"focused other: {format_world(focused)}")

        await client.leave(joined.handle)
        print(f"left handle={joined.handle}")


if __name__ == "__main__":
    asyncio.run(main())
