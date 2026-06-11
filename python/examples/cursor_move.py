"""Minimal Cursor example.

Reads the current desktop cursor position, centers it, moves it to an
off-center point, then releases the hold. ``set_position`` keeps the
in-engine cursor at the set position (``held=True``) until ``release()``
returns control to the OS pointer; the real OS mouse pointer is never
captured. Positions are normalized window coordinates in [0, 1] (center is
(0.5, 0.5)). Assumes a Resonite client with the ResoniteIO mod loaded is
running on the host in desktop mode.

Run from inside the dev container:

    uv run python python/examples/cursor_move.py
"""

import asyncio
import time

import grpclib.exceptions
from grpclib.const import Status

from resoio import CursorClient

SOCKET_PATH: str | None = None
READY_TIMEOUT_S = 60.0
READY_INTERVAL_S = 2.0


async def wait_for_ready() -> None:
    """Block until Cursor.GetPosition returns OK.

    During cold boot the engine may not have a focused desktop window yet,
    in which case the server replies with FAILED_PRECONDITION. Retry until
    ``READY_TIMEOUT_S`` elapses.
    """
    deadline = time.monotonic() + READY_TIMEOUT_S
    while True:
        try:
            async with CursorClient(SOCKET_PATH) as cursor:
                await cursor.get_position()
            return
        except grpclib.exceptions.GRPCError as e:
            if e.status != Status.FAILED_PRECONDITION:
                raise
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"Cursor did not become ready in {READY_TIMEOUT_S:.0f}s"
                ) from e
            await asyncio.sleep(READY_INTERVAL_S)


async def main() -> None:
    await wait_for_ready()
    async with CursorClient(SOCKET_PATH) as cursor:
        initial = await cursor.get_position()
        print(
            f"initial=({initial.x:.3f}, {initial.y:.3f}) "
            f"window={initial.window_width}x{initial.window_height}"
        )

        try:
            centered = await cursor.set_position(0.5, 0.5)
            print(f"centered=({centered.x:.3f}, {centered.y:.3f}) held={centered.held}")

            moved = await cursor.set_position(0.25, 0.25)
            print(f"moved=({moved.x:.3f}, {moved.y:.3f}) held={moved.held}")
        finally:
            # Release the hold so the engine cursor follows the OS pointer again.
            released = await cursor.release()
            print(f"released held={released.held}")


if __name__ == "__main__":
    asyncio.run(main())
