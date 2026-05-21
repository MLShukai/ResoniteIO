"""Minimal Session.Ping example.

Sends a single ping over the Resonite IO UDS and prints the server
timestamp plus the measured round-trip time. Assumes a Resonite client
with the ResoniteIO mod loaded is running on the host.

Run from inside the dev container:

    uv run python python/examples/session_ping.py
"""

import asyncio
import time

import grpclib.exceptions
from grpclib.const import Status

from resoio import SessionClient

SOCKET_PATH: str | None = None
MESSAGE = "hello"
READY_TIMEOUT_S = 60.0
READY_INTERVAL_S = 2.0


async def wait_for_ready() -> None:
    """Block until Session.Ping returns OK.

    During cold boot the UDS may be bound before the engine is fully
    ready, in which case the server replies with FAILED_PRECONDITION.
    Retry until ``READY_TIMEOUT_S`` elapses.
    """
    deadline = time.monotonic() + READY_TIMEOUT_S
    while True:
        try:
            async with SessionClient(SOCKET_PATH) as client:
                await client.ping("ready?")
            return
        except grpclib.exceptions.GRPCError as e:
            if e.status != Status.FAILED_PRECONDITION:
                raise
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"Session did not become ready in {READY_TIMEOUT_S:.0f}s"
                ) from e
            await asyncio.sleep(READY_INTERVAL_S)


async def main() -> None:
    await wait_for_ready()
    async with SessionClient(SOCKET_PATH) as client:
        # monotonic_ns is immune to wall-clock jumps (NTP step / DST)
        # that would otherwise produce negative or inflated RTTs.
        t0 = time.monotonic_ns()
        resp = await client.ping(MESSAGE)
        t1 = time.monotonic_ns()
    rtt_ms = (t1 - t0) / 1e6
    print(
        f"message={resp.message} "
        f"server_unix_nanos={resp.server_unix_nanos} "
        f"rtt_ms={rtt_ms:.3f}"
    )


if __name__ == "__main__":
    asyncio.run(main())
