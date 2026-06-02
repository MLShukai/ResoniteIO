"""``resoio context-menu`` subcommand: drive the radial context menu.

Flat dispatch via a positional ``action`` (no nested subparsers per
project convention):

* ``open`` / ``close`` / ``list`` — operate on the menu and print state
* ``highlight <index>`` — preview-select an item (no side effect)
* ``invoke <index>`` — press an item's action (may open a submenu / switch tool)

``--hand {primary,left,right}`` selects the target hand (default
``primary``). The shared ``-s/--socket`` flag comes from the common
parent parser. After every action the resulting state is printed.
"""

from __future__ import annotations

import argparse
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

    from resoio.context_menu import ContextMenuItem


def register(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
    common: argparse.ArgumentParser,
) -> None:
    """Register the flat ``context-menu`` subparser.

    Dispatch rules (no nested subcommands) live in the module docstring.
    """
    parser = subparsers.add_parser(
        "context-menu",
        parents=[common],
        help="Drive the radial context menu (open/close/list/highlight/invoke).",
        description=(
            "Drive the Resonite IO ContextMenu service from the shell. "
            "Pick an action (open / close / list / highlight / invoke); "
            "highlight and invoke require an item index. The resulting "
            "menu state is printed after every action."
        ),
    )
    parser.add_argument(
        "action",
        choices=["open", "close", "list", "highlight", "invoke"],
        help="The context-menu action to perform.",
    )
    parser.add_argument(
        "index",
        type=int,
        nargs="?",
        default=None,
        help="Item index for 'highlight' / 'invoke' (must be >= 0).",
    )
    parser.add_argument(
        "--hand",
        choices=["primary", "left", "right"],
        default="primary",
        help="Target hand / interaction handler (default: primary).",
    )
    parser.set_defaults(func=_run)


def _format_state(
    is_open: bool,
    items: Iterable[ContextMenuItem],
    highlighted_index: int,
) -> str:
    lines: list[str] = [f"is_open={is_open}"]
    for item in items:
        r, g, b, a = item.color
        lines.append(
            f"[{item.index}] {item.label!r} enabled={item.enabled} "
            f"icon={item.has_icon} color=({r}, {g}, {b}, {a})"
        )
    lines.append(f"highlighted_index={highlighted_index}")
    return "\n".join(lines)


async def _run(args: argparse.Namespace) -> int:
    """Dispatch on ``args.action`` and print the resulting menu state."""
    # Deferred to keep `resoio --help` and shell completion fast.
    from resoio.context_menu import ContextMenuClient

    action: str = args.action
    if action in ("highlight", "invoke"):
        if args.index is None:
            print(f"error: '{action}' requires an item index", file=sys.stderr)
            return 2
        if args.index < 0:
            print(f"error: index must be >= 0, got {args.index}", file=sys.stderr)
            return 2

    async with ContextMenuClient(args.socket) as client:
        if action == "open":
            state = await client.open(hand=args.hand)
        elif action == "close":
            state = await client.close(hand=args.hand)
        elif action == "list":
            state = await client.get_state(hand=args.hand)
        elif action == "highlight":
            state = await client.highlight(args.index, hand=args.hand)
        else:
            state = await client.invoke(args.index, hand=args.hand)

    print(_format_state(state.is_open, state.items, state.highlighted_index))
    return 0
