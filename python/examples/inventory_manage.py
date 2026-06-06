"""Minimal Inventory list -> mkdir -> copy -> move -> remove example.

Exercises the bash-like inventory ops end to end, scoped to a dedicated
temp folder under ``/Inventory`` that is recursively removed in a finally
block so the real inventory is left untouched. Steps: list the root,
mkdir the temp dir + a nested child, cp -r the child, mv the copy, then
rm -r the whole temp dir as cleanup. Every mutation stays inside the
temp folder this script created.

Inventory ops hit the user's real cloud inventory, so a logged-in
Resonite client is required.

Run from inside the dev container:

    uv run python python/examples/inventory_manage.py
"""

import asyncio
import time

import grpclib.exceptions
from grpclib.const import Status

from resoio import InventoryClient

SOCKET_PATH: str | None = None
ROOT = "/Inventory"
TEMP_DIR = f"{ROOT}/__resoio_example__"
CHILD_DIR = f"{TEMP_DIR}/child"
COPY_DIR = f"{TEMP_DIR}/child_copy"
MOVED_DIR = f"{TEMP_DIR}/child_moved"
READY_TIMEOUT_S = 120.0
READY_INTERVAL_S = 2.0


async def wait_for_ready() -> None:
    """Block until Inventory.List stops returning FAILED_PRECONDITION.

    The bridge replies FAILED_PRECONDITION until the engine has booted
    and the user is signed in. Retry until ready.
    """
    deadline = time.monotonic() + READY_TIMEOUT_S
    while True:
        try:
            async with InventoryClient(SOCKET_PATH) as client:
                await client.list(ROOT)
            return
        except grpclib.exceptions.GRPCError as e:
            if e.status != Status.FAILED_PRECONDITION:
                raise
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"Inventory did not become ready in {READY_TIMEOUT_S:.0f}s"
                ) from e
            await asyncio.sleep(READY_INTERVAL_S)


async def main() -> None:
    await wait_for_ready()
    async with InventoryClient(SOCKET_PATH) as client:
        root = await client.list(ROOT)
        print(f"root: {len(root.entries)} entries")

        try:
            # mkdir the temp dir + a nested child. All mutations below stay
            # inside TEMP_DIR so the finally cleanup removes everything.
            await client.mkdir(TEMP_DIR)
            await client.mkdir(CHILD_DIR)
            listing = await client.list(TEMP_DIR)
            print(f"after mkdir: {[e.name for e in listing.entries]}")

            # cp -r the folder (recursive=True is required for directories).
            await client.copy(CHILD_DIR, COPY_DIR, recursive=True)
            print(f"copied {CHILD_DIR} -> {COPY_DIR}")

            # mv the copy (folders move recursively without a flag).
            await client.move(COPY_DIR, MOVED_DIR)
            after_move = await client.list(TEMP_DIR)
            print(f"after move: {[e.name for e in after_move.entries]}")
        finally:
            # rm -r the whole temp dir; recursive=True is required for folders.
            await client.remove(TEMP_DIR, recursive=True)
            final = await client.list(ROOT)
            still_present = any(e.name == "__resoio_example__" for e in final.entries)
            print(f"cleaned up temp dir (still_present={still_present})")


if __name__ == "__main__":
    asyncio.run(main())
