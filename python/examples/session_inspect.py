"""Minimal Session inspect example: read settings, users, and roles.

Read-only walk of the connected session's control panel — the same data
the in-game dash "Session" dialog shows across its Settings / Users /
Permissions tabs. Prints the current world settings, the connected
users, and the permission roles. Performs no mutation, so it is safe to
run against any live session regardless of host permissions.

A running, signed-in Resonite client focused on a world (not just
userspace) is required.

Run from inside the dev container:

    uv run python python/examples/session_inspect.py
"""

import asyncio
import time

import grpclib.exceptions
from grpclib.const import Status

from resoio import SessionClient
from resoio.session import SessionSettings

SOCKET_PATH: str | None = None
READY_TIMEOUT_S = 120.0
READY_INTERVAL_S = 2.0


async def wait_for_ready() -> SessionSettings:
    """Block until GetSettings stops returning FAILED_PRECONDITION.

    The bridge replies FAILED_PRECONDITION until the engine has booted
    and a non-userspace world is focused. Retry until ready, then return
    the first successful settings snapshot.
    """
    deadline = time.monotonic() + READY_TIMEOUT_S
    while True:
        try:
            async with SessionClient(SOCKET_PATH) as client:
                return await client.get_settings()
        except grpclib.exceptions.GRPCError as e:
            if e.status != Status.FAILED_PRECONDITION:
                raise
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"Session did not become ready in {READY_TIMEOUT_S:.0f}s"
                ) from e
            await asyncio.sleep(READY_INTERVAL_S)


async def main() -> None:
    settings = await wait_for_ready()
    print(
        f"settings: name={settings.world_name!r} "
        f"access={settings.access_level.name} "
        f"users={settings.max_users} host={settings.is_host}"
    )

    async with SessionClient(SOCKET_PATH) as client:
        users = await client.list_users()
        print(f"users: {len(users)} connected")
        for u in users:
            tags = "".join(
                flag for flag, on in (("H", u.is_host), ("*", u.is_local_user)) if on
            )
            print(f"  {u.user_name} [{tags or '-'}] role={u.role_name or '-'}")

        roles = await client.list_roles()
        print(f"roles: {', '.join(r.role_name for r in roles.roles)}")


if __name__ == "__main__":
    asyncio.run(main())
