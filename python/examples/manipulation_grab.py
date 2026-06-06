"""Minimal Manipulation grab -> get_state -> release example.

Runs the smallest grab/release cycle against the primary hand: probe the
current hold state, attempt a grab at the hand's position, re-read the
state, then release. The default home world has nothing grabbable near an
empty hand, so grab() typically reports grabbed=False without error - the
RPC path is what this exercises, not a positive pick-up. See
mod/tests/manual/manipulation-verification.md for the visual confirmation.

Run from inside the dev container:

    uv run python python/examples/manipulation_grab.py
"""

import asyncio
import time

import grpclib.exceptions
from grpclib.const import Status

from resoio import GrabState, ManipulationClient

SOCKET_PATH: str | None = None
HAND = "primary"
READY_TIMEOUT_S = 120.0
READY_INTERVAL_S = 2.0


async def wait_for_ready() -> None:
    """Block until Manipulation.GetState stops returning FAILED_PRECONDITION.

    During cold boot the per-hand Grabber / LocalUser are not yet wired
    up and the bridge replies FAILED_PRECONDITION. Retry until ready.
    """
    deadline = time.monotonic() + READY_TIMEOUT_S
    while True:
        try:
            async with ManipulationClient(SOCKET_PATH) as client:
                await client.get_state(hand=HAND)
            return
        except grpclib.exceptions.GRPCError as e:
            if e.status != Status.FAILED_PRECONDITION:
                raise
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"Manipulation did not become ready in {READY_TIMEOUT_S:.0f}s"
                ) from e
            await asyncio.sleep(READY_INTERVAL_S)


def format_state(state: GrabState) -> str:
    objects = ", ".join(state.object_names)
    return (
        f"hand={state.hand} is_holding={state.is_holding} "
        f"objects=[{objects}] unix_nanos={state.unix_nanos}"
    )


async def main() -> None:
    await wait_for_ready()
    async with ManipulationClient(SOCKET_PATH) as client:
        initial = await client.get_state(hand=HAND)
        print(f"initial: {format_state(initial)}")

        # grab at the hand's current position (point=None). grabbed=False on
        # an empty home world is expected, not an error.
        result = await client.grab(hand=HAND)
        print(f"grabbed={result.grabbed} state: {format_state(result.state)}")

        released = await client.release(hand=HAND)
        print(f"released: {format_state(released)}")


if __name__ == "__main__":
    asyncio.run(main())
