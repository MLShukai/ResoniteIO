"""Minimal ContextMenu open -> get_state -> highlight -> invoke -> close.

Opens the desktop T-key radial menu on the primary hand, reads its items,
highlights the first one (preview only), invokes the first enabled item
(fires its action - e.g. opening a submenu or switching the active tool),
then closes the menu. open() is re-asserted before each step because the
desktop radial auto-closes after a few seconds of no summoning input.

Run from inside the dev container:

    uv run python python/examples/context_menu_interact.py
"""

import asyncio
import time

import grpclib.exceptions
from grpclib.const import Status

from resoio import ContextMenuClient, ContextMenuState

SOCKET_PATH: str | None = None
HAND = "primary"
READY_TIMEOUT_S = 120.0
READY_INTERVAL_S = 2.0


async def wait_for_ready() -> None:
    """Block until ContextMenu.GetState stops returning FAILED_PRECONDITION.

    The bridge replies FAILED_PRECONDITION while the LocalUser /
    InteractionHandler are still booting. Retry until ready.
    """
    deadline = time.monotonic() + READY_TIMEOUT_S
    while True:
        try:
            async with ContextMenuClient(SOCKET_PATH) as client:
                await client.get_state(hand=HAND)
            return
        except grpclib.exceptions.GRPCError as e:
            if e.status != Status.FAILED_PRECONDITION:
                raise
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"ContextMenu did not become ready in {READY_TIMEOUT_S:.0f}s"
                ) from e
            await asyncio.sleep(READY_INTERVAL_S)


def format_state(state: ContextMenuState) -> str:
    labels = ", ".join(f"[{item.index}] {item.label!r}" for item in state.items)
    return (
        f"is_open={state.is_open} "
        f"highlighted_index={state.highlighted_index} items={{{labels}}}"
    )


async def main() -> None:
    await wait_for_ready()
    async with ContextMenuClient(SOCKET_PATH) as client:
        opened = await client.open(hand=HAND)
        print(f"opened: {format_state(opened)}")
        if not opened.items:
            print("menu opened with no items; done")
            return

        # open() is idempotent; re-assert before each step because the
        # radial auto-closes after a few seconds.
        await client.open(hand=HAND)
        listed = await client.get_state(hand=HAND)
        print(f"state: {format_state(listed)}")

        await client.open(hand=HAND)
        highlighted = await client.highlight(0, hand=HAND)
        print(f"highlighted: {format_state(highlighted)}")

        # First enabled item; invoking a disabled one is a no-op.
        enabled_index = next((i.index for i in opened.items if i.enabled), 0)
        await client.open(hand=HAND)
        invoked = await client.invoke(enabled_index, hand=HAND)
        print(f"invoked index={enabled_index}: {format_state(invoked)}")

        closed = await client.close(hand=HAND)
        print(f"closed: {format_state(closed)}")


if __name__ == "__main__":
    asyncio.run(main())
