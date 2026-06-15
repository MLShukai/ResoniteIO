"""Minimal Auth status example: read the Resonite cloud auth state (read-only).

Calls ``Auth.Status`` once and prints whether the running Resonite client is
signed in, plus the user id / name and session expiry when it is. Performs no
mutation (no login / logout), so it is safe to run anytime regardless of the
sign-in state.

This example never handles a password — see ``resoio auth login`` (CLI) for the
sign-in flow, which reads the password from ``RESONITE_IO_PASSWORD`` / piped
stdin / a hidden prompt (never a flag).

Run from inside the dev container:

    uv run python python/examples/auth_status.py
"""

import asyncio
import time

import grpclib.exceptions
from grpclib.const import Status

from resoio import AuthClient
from resoio.auth import AuthStatus

SOCKET_PATH: str | None = None
READY_TIMEOUT_S = 120.0
READY_INTERVAL_S = 2.0


async def wait_for_ready() -> AuthStatus:
    """Block until Status returns cleanly, returning the first snapshot.

    ``Status`` is a read-only, null-safe call (it reports logged-out rather
    than erroring), but during cold boot the bridge can briefly be UNAVAILABLE
    (not yet registered) or FAILED_PRECONDITION (cloud manager still coming
    up). Retry only those transient statuses, then return the first snapshot.
    """
    deadline = time.monotonic() + READY_TIMEOUT_S
    transient = {Status.UNAVAILABLE, Status.FAILED_PRECONDITION}
    while True:
        try:
            async with AuthClient(SOCKET_PATH) as client:
                return await client.status()
        except grpclib.exceptions.GRPCError as e:
            if e.status not in transient or time.monotonic() > deadline:
                raise
            await asyncio.sleep(READY_INTERVAL_S)


async def main() -> None:
    status = await wait_for_ready()
    if status.logged_in:
        print(f"logged in as {status.user_name} ({status.user_id})")
        if status.session_expires_unix_nanos > 0:
            print(
                f"session expires at {status.session_expires_unix_nanos} (unix nanos)"
            )
    else:
        print("not logged in")


if __name__ == "__main__":
    asyncio.run(main())
