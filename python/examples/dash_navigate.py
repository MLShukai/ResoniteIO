"""Minimal Dash open -> list_tabs -> set_tab -> list_controls -> invoke.

Opens the userspace Esc dash, enumerates its bottom-bar tabs, navigates to
the first enabled non-current tab by its language-independent ``locale_key``,
enumerates the interactable controls (buttons / scroll areas) of that tab,
invokes the first control by ``ref_id``, then closes the dash. Tab and
control addressing use language-independent ``locale_key`` / ``ref_id``
rather than localised labels.

Run from inside the dev container:

    uv run python python/examples/dash_navigate.py
"""

import asyncio
import time

import grpclib.exceptions
from grpclib.const import Status

from resoio import DashClient

SOCKET_PATH: str | None = None
TAB_SETTLE_S = 0.6
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

        tabs = await client.list_tabs()
        print(f"tabs: {len(tabs)}")
        for tab in tabs:
            print(
                f"  locale_key={tab.locale_key!r} is_current={tab.is_current} "
                f"enabled={tab.enabled} label={tab.label!r}"
            )

        # Navigate to the first enabled, keyed tab that is not the current one.
        # set_tab addresses tabs by language-independent locale_key.
        target = next(
            (t for t in tabs if t.enabled and t.locale_key and not t.is_current), None
        )
        if target is not None:
            nav = await client.set_tab(locale_key=target.locale_key)
            print(f"set_tab({target.locale_key!r}): ok={nav.ok} found={nav.found}")
            # The tab-switch animation needs a moment before list_controls
            # reflects the new tab's content.
            await asyncio.sleep(TAB_SETTLE_S)

        controls = await client.list_controls()
        print(f"controls: {len(controls)} interactable")
        for control in controls:
            indent = "  " * control.depth
            print(
                f"  {indent}[{control.control_type}] {control.label!r} "
                f"enabled={control.enabled} ref_id={control.ref_id}"
            )

        # Invoke the first control by its language-independent ref_id.
        # found/ok report whether it resolved and applied.
        if controls:
            ref_id = controls[0].ref_id
            result = await client.invoke(ref_id)
            print(
                f"invoke ref_id={ref_id}: ok={result.ok} found={result.found} "
                f"detail={result.detail!r}"
            )

        closed = await client.close()
        print(f"closed: is_open={closed.is_open}")


if __name__ == "__main__":
    asyncio.run(main())
