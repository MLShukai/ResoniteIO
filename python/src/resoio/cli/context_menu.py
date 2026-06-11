"""``resoio context-menu <subcommand>``: drive the radial context menu.

Nested subcommands mirror ``resoio world``: a ``context-menu`` parent
parser holds the leaves, each with the shared ``-s/--socket`` parent
re-attached (argparse does not inherit it) and its own handler set via
``set_defaults(func=...)``:

* ``open`` / ``close`` / ``list`` — operate on the menu and print state
* ``highlight <index>`` — preview-select an item (no side effect)
* ``invoke <index>`` — press an item's action (may open a submenu / switch tool)

``--hand {primary,left,right}`` selects the target hand on every leaf
(default ``primary``). After every action the resulting state is printed.
"""

from __future__ import annotations

import argparse
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

    from resoio.context_menu import ContextMenuItem


def _add_hand_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--hand",
        choices=["primary", "left", "right"],
        default="primary",
        help="Target hand / interaction handler (default: primary).",
    )


def register(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
    common: argparse.ArgumentParser,
) -> None:
    """Register the ``context-menu`` subparser with its nested subcommands."""
    parser = subparsers.add_parser(
        "context-menu",
        parents=[common],
        help="Drive the radial context menu (open/close/list/highlight/invoke).",
        description=(
            "Drive the Resonite IO ContextMenu service from the shell. "
            "Pick a subcommand (open / close / list / highlight / invoke); "
            "highlight and invoke require an item index. The resulting "
            "menu state is printed after every action."
        ),
    )
    menu_subs = parser.add_subparsers(dest="context_menu_command", required=True)

    open_parser = menu_subs.add_parser(
        "open",
        parents=[common],
        help="Open the context menu at the current cursor position.",
    )
    _add_hand_arg(open_parser)
    open_parser.set_defaults(func=_run_open)

    close_parser = menu_subs.add_parser(
        "close",
        parents=[common],
        help="Close the context menu.",
    )
    _add_hand_arg(close_parser)
    close_parser.set_defaults(func=_run_close)

    list_parser = menu_subs.add_parser(
        "list",
        parents=[common],
        help="List the context menu items and state.",
    )
    _add_hand_arg(list_parser)
    list_parser.set_defaults(func=_run_list)

    highlight_parser = menu_subs.add_parser(
        "highlight",
        parents=[common],
        help="Preview-select an item by index (no side effect).",
    )
    highlight_parser.add_argument(
        "index",
        type=int,
        help="Item index (must be >= 0).",
    )
    _add_hand_arg(highlight_parser)
    highlight_parser.set_defaults(func=_run_highlight)

    invoke_parser = menu_subs.add_parser(
        "invoke",
        parents=[common],
        help="Press an item's action by index (may open a submenu / switch tool).",
    )
    invoke_parser.add_argument(
        "index",
        type=int,
        help="Item index (must be >= 0).",
    )
    _add_hand_arg(invoke_parser)
    invoke_parser.set_defaults(func=_run_invoke)


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


def _check_index(index: int) -> bool:
    """Validate a menu item index, printing an error when negative."""
    if index < 0:
        print(f"error: index must be >= 0, got {index}", file=sys.stderr)
        return False
    return True


async def _run_open(args: argparse.Namespace) -> int:
    # Deferred to keep `resoio --help` and shell completion fast.
    from resoio.context_menu import ContextMenuClient

    async with ContextMenuClient(args.socket) as client:
        state = await client.open(hand=args.hand)
    print(_format_state(state.is_open, state.items, state.highlighted_index))
    return 0


async def _run_close(args: argparse.Namespace) -> int:
    from resoio.context_menu import ContextMenuClient

    async with ContextMenuClient(args.socket) as client:
        state = await client.close(hand=args.hand)
    print(_format_state(state.is_open, state.items, state.highlighted_index))
    return 0


async def _run_list(args: argparse.Namespace) -> int:
    from resoio.context_menu import ContextMenuClient

    async with ContextMenuClient(args.socket) as client:
        state = await client.get_state(hand=args.hand)
    print(_format_state(state.is_open, state.items, state.highlighted_index))
    return 0


async def _run_highlight(args: argparse.Namespace) -> int:
    from resoio.context_menu import ContextMenuClient

    if not _check_index(args.index):
        return 2

    async with ContextMenuClient(args.socket) as client:
        state = await client.highlight(args.index, hand=args.hand)
    print(_format_state(state.is_open, state.items, state.highlighted_index))
    return 0


async def _run_invoke(args: argparse.Namespace) -> int:
    from resoio.context_menu import ContextMenuClient

    if not _check_index(args.index):
        return 2

    async with ContextMenuClient(args.socket) as client:
        state = await client.invoke(args.index, hand=args.hand)
    print(_format_state(state.is_open, state.items, state.highlighted_index))
    return 0
