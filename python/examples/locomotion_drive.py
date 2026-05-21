"""Minimal Locomotion drive + reset example.

Runs a 6 s scripted scenario (forward -> strafe -> yaw -> jump ->
neutral) at 30 Hz, then opens a SECOND LocomotionClient to call
reset() and clear the bridge state. Assumes a walk-capable world is
loaded in Resonite.

Run from inside the dev container:

    uv run python python/examples/locomotion_drive.py
"""

import asyncio
import time
from collections.abc import AsyncIterator

import grpclib.exceptions
from grpclib.const import Status

from resoio import LocomotionClient, LocomotionCmd

SOCKET_PATH: str | None = None
TICK_HZ = 30
TICK_INTERVAL_S = 1.0 / TICK_HZ
SCENARIO_DURATION_S = 6.0
READY_TIMEOUT_S = 120.0
READY_INTERVAL_S = 2.0


def scenario_command(elapsed: float) -> LocomotionCmd:
    """Return the LocomotionCmd to send at ``elapsed`` seconds in.

    LocomotionCmd.velocity defaults to 1.0 - proto3 wire default 0 would
    stop the avatar; the dataclass wrapper exists to avoid that pitfall.
    """
    if elapsed < 2.0:
        return LocomotionCmd(move_y=1.0)
    if elapsed < 3.0:
        return LocomotionCmd(move_x=1.0)
    if elapsed < 4.0:
        return LocomotionCmd(yaw_rate=0.5)
    if elapsed < 5.0:
        return LocomotionCmd(jump=True)
    # Final neutral LocomotionCmd() required: bridge holds the last
    # command; sending nothing would let move_y=1.0 survive on the
    # stateful repeater.
    return LocomotionCmd()


async def commands() -> AsyncIterator[LocomotionCmd]:
    """Yield scenario commands at TICK_HZ until SCENARIO_DURATION_S."""
    t0 = time.monotonic()
    while True:
        elapsed = time.monotonic() - t0
        if elapsed >= SCENARIO_DURATION_S:
            return
        yield scenario_command(elapsed)
        await asyncio.sleep(TICK_INTERVAL_S)


async def wait_for_ready() -> None:
    """Block until Locomotion.Drive accepts a single neutral command.

    Retries FAILED_PRECONDITION until the bridge has a walk-capable
    active module and LocalUser / FocusedWorld are wired up.
    """
    deadline = time.monotonic() + READY_TIMEOUT_S
    while True:
        try:
            async with LocomotionClient(SOCKET_PATH) as client:

                async def one_neutral() -> AsyncIterator[LocomotionCmd]:
                    yield LocomotionCmd()

                await client.drive(one_neutral())
            return
        except grpclib.exceptions.GRPCError as e:
            if e.status != Status.FAILED_PRECONDITION:
                raise
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"Locomotion did not become ready in {READY_TIMEOUT_S:.0f}s"
                ) from e
            await asyncio.sleep(READY_INTERVAL_S)


async def main() -> None:
    await wait_for_ready()
    async with LocomotionClient(SOCKET_PATH) as client:
        summary = await client.drive(commands())
    print(
        f"received_count={summary.received_count} "
        f"dropped_count={summary.dropped_count} "
        f"unix_nanos={summary.unix_nanos}"
    )

    # reset() goes on a SECOND client because the primary client is
    # still inside drive() (client-streaming blocks until the request
    # iterator returns). Bridge auto-resets on ungraceful disconnect;
    # graceful CompleteAsync leaves state, so we call reset() explicitly.
    async with LocomotionClient(SOCKET_PATH) as reset_client:
        reset = await reset_client.reset()
    print(
        f"move={reset.move} look={reset.look} "
        f"crouch={reset.crouch} jump={reset.jump} "
        f"unix_nanos={reset.unix_nanos}"
    )


if __name__ == "__main__":
    asyncio.run(main())
