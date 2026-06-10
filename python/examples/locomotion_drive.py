"""Minimal Locomotion drive + reset example.

Runs a short scripted scenario (forward -> strafe -> yaw -> jump ->
neutral), then opens a SECOND LocomotionClient to call reset() and clear
the bridge state. Assumes a walk-capable world is loaded in Resonite.

The mod-side bridge is a stateful repeater: it holds the last command
and re-injects it every engine tick, so a phase only needs ONE send().
``send()`` is a partial update — unset (``None``) fields keep their prior
value on the bridge, so each phase sends just the axes it changes (and
explicitly zeroes the axis the previous phase set). ``velocity`` defaults
to 1.0 inside the bridge, so plain forward motion needs no velocity arg.

Run from inside the dev container:

    uv run python python/examples/locomotion_drive.py
"""

import asyncio
import time

import grpclib.exceptions
from grpclib.const import Status

from resoio import LocomotionClient

SOCKET_PATH: str | None = None
READY_TIMEOUT_S = 120.0
READY_INTERVAL_S = 2.0


async def wait_for_ready() -> None:
    """Block until Locomotion.Drive accepts a single neutral command.

    Retries FAILED_PRECONDITION until the bridge has a walk-capable
    active module and LocalUser / FocusedWorld are wired up.
    """
    deadline = time.monotonic() + READY_TIMEOUT_S
    while True:
        try:
            async with LocomotionClient(SOCKET_PATH) as client:
                await client.send()  # neutral probe
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
        await client.send(move_forward=1.0)
        await asyncio.sleep(2.0)
        await client.send(move_forward=0.0, move_right=1.0)
        await asyncio.sleep(1.0)
        await client.send(move_right=0.0, yaw_rate=0.5)
        await asyncio.sleep(1.0)
        await client.send(yaw_rate=0.0, jump=True)
        await asyncio.sleep(1.0)
        # Final neutral: the stateful repeater would otherwise keep the
        # last command alive after the stream closes gracefully.
        await client.send(move_forward=0.0, move_right=0.0, move_up=0.0, crouch=0.0)

    summary = client.drive_summary
    if summary is not None:
        print(
            f"received_count={summary.received_count} "
            f"dropped_count={summary.dropped_count} "
            f"unix_nanos={summary.unix_nanos}"
        )

    # reset() goes on a SECOND client: graceful CompleteAsync leaves the
    # bridge state in place, so we clear it explicitly. (An ungraceful
    # disconnect would auto-reset bridge-side instead.)
    async with LocomotionClient(SOCKET_PATH) as reset_client:
        reset = await reset_client.reset()
    print(
        f"move={reset.move} look={reset.look} "
        f"crouch={reset.crouch} jump={reset.jump} "
        f"unix_nanos={reset.unix_nanos}"
    )


if __name__ == "__main__":
    asyncio.run(main())
