"""Minimal Connection.Ping example.

Sends a single ping over the Resonite IO UDS and prints the server
timestamp plus the measured round-trip time. Assumes a Resonite client
with the ResoniteIO mod loaded is running on the host.

Run from inside the dev container:

    uv run python python/examples/connection_ping.py
"""

import asyncio
import time

from resoio import ConnectionClient, wait_for_ready

SOCKET_PATH: str | None = None
MESSAGE = "hello"
READY_TIMEOUT_S = 60.0


async def main() -> None:
    # Block until the engine answers Connection.Ping. During cold boot the
    # socket may be absent, have no listener yet, or be bound by an engine
    # still initialising (FAILED_PRECONDITION); wait_for_ready retries those
    # until READY_TIMEOUT_S elapses, then returns the resolved socket path.
    await wait_for_ready(SOCKET_PATH, timeout=READY_TIMEOUT_S)
    async with ConnectionClient(SOCKET_PATH) as client:
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
