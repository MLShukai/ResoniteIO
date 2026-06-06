"""Minimal Dash open -> list_screens -> set_screen -> get_tree -> invoke.

Opens the userspace Esc dash, enumerates its screens (tabs), navigates to
the first enabled non-current screen by its language-independent key,
introspects the rendered UI tree, invokes the first interactable element
by ref_id, then closes the dash. Screen and element addressing use
language-independent ``key`` / ``ref_id`` rather than localised labels.

Run from inside the dev container:

    uv run python python/examples/dash_navigate.py
"""

import asyncio
import time

import grpclib.exceptions
from grpclib.const import Status

from resoio import DashClient

SOCKET_PATH: str | None = None
SCREEN_SETTLE_S = 0.6
READY_TIMEOUT_S = 120.0
READY_INTERVAL_S = 2.0


async def wait_for_ready() -> None:
    """Block until Dash.GetState stops returning FAILED_PRECONDITION.

    The bridge replies FAILED_PRECONDITION while the
    UserspaceRadiantDash is still booting. Retry until ready.
    """
    deadline = time.monotonic() + READY_TIMEOUT_S
    while True:
        try:
            async with DashClient(SOCKET_PATH) as client:
                await client.get_state()
            return
        except grpclib.exceptions.GRPCError as e:
            if e.status != Status.FAILED_PRECONDITION:
                raise
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"Dash did not become ready in {READY_TIMEOUT_S:.0f}s"
                ) from e
            await asyncio.sleep(READY_INTERVAL_S)


async def main() -> None:
    await wait_for_ready()
    async with DashClient(SOCKET_PATH) as client:
        opened = await client.open()
        print(f"opened: is_open={opened.is_open} open_lerp={opened.open_lerp}")

        screens = await client.list_screens()
        print(f"screens: {len(screens)}")
        for screen in screens:
            print(
                f"  key={screen.key!r} is_current={screen.is_current} "
                f"enabled={screen.enabled} label={screen.label!r}"
            )

        # Navigate to the first enabled, keyed screen that is not the current
        # one. set_screen addresses screens by language-independent key.
        target = next(
            (s for s in screens if s.enabled and s.key and not s.is_current), None
        )
        if target is not None:
            nav = await client.set_screen(key=target.key)
            print(f"set_screen({target.key!r}): ok={nav.ok} found={nav.found}")
            # The screen-switch animation needs a moment before get_tree
            # reflects the new screen's content.
            await asyncio.sleep(SCREEN_SETTLE_S)

        tree = await client.get_tree(interactable_only=True)
        print(
            f"tree: {len(tree.elements)} interactable elements "
            f"screen={tree.screen_width}x{tree.screen_height}"
        )

        # Invoke the first interactable element by its language-independent
        # ref_id. found/ok report whether it resolved and applied.
        if tree.elements:
            ref_id = tree.elements[0].ref_id
            result = await client.invoke(ref_id)
            print(
                f"invoke ref_id={ref_id}: ok={result.ok} found={result.found} "
                f"detail={result.detail!r}"
            )

        closed = await client.close()
        print(f"closed: is_open={closed.is_open}")


if __name__ == "__main__":
    asyncio.run(main())
