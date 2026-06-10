"""Manipulation positive-grab example: spawn a Mirror, aim, grab, release.

Demonstrates a real pick-up against the primary hand: spawn a grabbable
Mirror from the cloud inventory (Resonite Essentials), hold the desktop
cursor on it with CursorClient.set_position, grab at the cursor ray hit
point, then release everything. The grabbed object is tweened into the
hand and follows it (held in front of the chest in desktop mode). VR mode
fails with FAILED_PRECONDITION. The spawned Mirror stays in the world
after release (there is no despawn API); the local home resets on the
next Resonite restart.

Run from inside the dev container:

    uv run python python/examples/manipulation_grab.py
"""

import asyncio
import time

import grpclib.exceptions
from grpclib.const import Status

from resoio import CursorClient, GrabState, InventoryClient, ManipulationClient

SOCKET_PATH: str | None = None
HAND = "primary"
MIRROR_PATH = "/Inventory/Resonite Essentials/Mirror"
# The Mirror spawns in front of the view; these normalized cursor targets
# cover small spawn-position jitter (retry until one of them hits it).
AIM_POINTS = ((0.5, 0.45), (0.45, 0.5), (0.55, 0.4))
GRAB_RADIUS = 0.5
SPAWN_SETTLE_S = 5.0
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
    async with (
        InventoryClient(SOCKET_PATH) as inventory,
        CursorClient(SOCKET_PATH) as cursor,
        ManipulationClient(SOCKET_PATH) as client,
    ):
        spawned = await inventory.spawn(MIRROR_PATH)
        print(f"spawned: {spawned.spawned_slot_name} ({spawned.spawned_slot_id})")
        await asyncio.sleep(SPAWN_SETTLE_S)

        try:
            # Hold the cursor on the Mirror and grab at the ray hit point.
            # Retry a few aim points to absorb spawn-position jitter.
            grabbed = False
            for x, y in AIM_POINTS:
                await cursor.set_position(x, y)
                result = await client.grab(hand=HAND, radius=GRAB_RADIUS)
                print(
                    f"aim=({x}, {y}) grabbed={result.grabbed} "
                    f"state: {format_state(result.state)}"
                )
                if result.grabbed:
                    grabbed = True
                    break
            if not grabbed:
                print("Mirror was not hit by the cursor ray; nothing grabbed.")
        finally:
            released = await client.release(hand=HAND)
            print(f"released: {format_state(released)}")
            await cursor.release()


if __name__ == "__main__":
    asyncio.run(main())
