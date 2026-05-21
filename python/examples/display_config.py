"""Minimal Display apply + restore example.

Reads the current display state, applies 1024x768, polls until the
engine snapshot reflects the new size, then restores the original
resolution. apply() returns None so a post-apply snapshot must be
fetched via get().

Run from inside the dev container:

    uv run python python/examples/display_config.py
"""

import asyncio
import time

import grpclib.exceptions
from grpclib.const import Status

from resoio import DisplayClient, DisplayInfo

SOCKET_PATH: str | None = None
TARGET_WIDTH = 1024
TARGET_HEIGHT = 768
SETTLE_TIMEOUT_S = 15.0
SETTLE_POLL_S = 0.2
READY_TIMEOUT_S = 60.0
READY_INTERVAL_S = 1.0


async def wait_for_ready() -> None:
    """Block until Display.Get stops returning FAILED_PRECONDITION."""
    deadline = time.monotonic() + READY_TIMEOUT_S
    while True:
        try:
            async with DisplayClient(SOCKET_PATH) as client:
                await client.get()
            return
        except grpclib.exceptions.GRPCError as e:
            if e.status != Status.FAILED_PRECONDITION:
                raise
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"Display did not become ready in {READY_TIMEOUT_S:.0f}s"
                ) from e
            await asyncio.sleep(READY_INTERVAL_S)


async def apply_and_settle(width: int, height: int) -> DisplayInfo:
    """Apply ``width x height`` and poll get() until the snapshot matches.

    apply() returns None by contract - engine settings dispatch hops
    threads, so a post-apply snapshot from the same RPC would be
    unreliable. 0 in any apply() field means "leave unchanged"; we
    always supply both width+height here. Poll-settle because
    RenderSystem.UpdateResolution reconciles for a few ticks after Apply.
    """
    async with DisplayClient(SOCKET_PATH) as client:
        await client.apply(width=width, height=height)
    deadline = time.monotonic() + SETTLE_TIMEOUT_S
    while True:
        async with DisplayClient(SOCKET_PATH) as client:
            info = await client.get()
        if (info.width, info.height) == (width, height):
            return info
        if time.monotonic() > deadline:
            raise TimeoutError(
                f"apply({width}x{height}) did not settle within "
                f"{SETTLE_TIMEOUT_S:.1f}s (last seen: {info.width}x{info.height})"
            )
        await asyncio.sleep(SETTLE_POLL_S)


async def main() -> None:
    await wait_for_ready()
    async with DisplayClient(SOCKET_PATH) as client:
        initial = await client.get()
    print(
        f"initial: width={initial.width} height={initial.height} "
        f"max_fps={initial.max_fps}"
    )

    applied = await apply_and_settle(TARGET_WIDTH, TARGET_HEIGHT)
    print(
        f"applied: width={applied.width} height={applied.height} "
        f"max_fps={applied.max_fps}"
    )

    restored = await apply_and_settle(initial.width, initial.height)
    print(
        f"restored: width={restored.width} height={restored.height} "
        f"max_fps={restored.max_fps}"
    )


if __name__ == "__main__":
    asyncio.run(main())
