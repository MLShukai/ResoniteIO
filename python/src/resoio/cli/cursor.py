"""``resoio cursor`` subcommand: move / hold / read the desktop cursor.

Flat dispatch via a positional ``action`` (no nested subparsers per
project convention):

* ``set <x> <y>`` — move the cursor to normalized ``(x, y)`` in ``[0, 1]``
  and hold it there until ``release``
* ``center`` — move the cursor to the screen center ``(0.5, 0.5)`` and
  hold it there until ``release``
* ``get`` — print the current cursor position and hold state (no movement)
* ``release`` — release the hold (idempotent)

The shared ``-s/--socket`` flag comes from the common parent parser.
After every action the resulting cursor state is printed.
"""

from __future__ import annotations

import argparse
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from resoio.cursor import CursorState


def register(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
    common: argparse.ArgumentParser,
) -> None:
    """Register the flat ``cursor`` subparser.

    Dispatch rules (no nested subcommands) live in the module docstring.
    """
    parser = subparsers.add_parser(
        "cursor",
        parents=[common],
        help="Move / hold / read the desktop cursor (set/center/get/release).",
        description=(
            "Drive the Resonite IO Cursor service from the shell. Pick an "
            "action: 'set' needs normalized x y in [0,1] and holds the cursor "
            "there until 'release'; 'center' moves to (0.5, 0.5) and holds; "
            "'get' prints the current position and hold state; 'release' "
            "releases the hold. The resulting cursor state is printed after "
            "every action."
        ),
    )
    parser.add_argument(
        "action",
        choices=["set", "center", "get", "release"],
        help="The cursor action to perform.",
    )
    parser.add_argument(
        "x",
        type=float,
        nargs="?",
        default=None,
        help="Normalized x in [0,1] (required for 'set').",
    )
    parser.add_argument(
        "y",
        type=float,
        nargs="?",
        default=None,
        help="Normalized y in [0,1] (required for 'set').",
    )
    parser.set_defaults(func=_run)


def _format_state(state: CursorState) -> str:
    return (
        f"x={state.x} y={state.y} "
        f"window={state.window_width}x{state.window_height} held={state.held}"
    )


async def _run(args: argparse.Namespace) -> int:
    """Dispatch on ``args.action`` and print the resulting cursor state."""
    # Deferred to keep `resoio --help` and shell completion fast.
    from resoio.cursor import CursorClient

    action: str = args.action
    if action == "set":
        if args.x is None or args.y is None:
            print("error: 'set' requires x and y", file=sys.stderr)
            return 2
        if not (0.0 <= args.x <= 1.0) or not (0.0 <= args.y <= 1.0):
            print(
                f"error: x and y must be in [0,1], got ({args.x}, {args.y})",
                file=sys.stderr,
            )
            return 2

    async with CursorClient(args.socket) as client:
        if action == "set":
            state = await client.set_position(args.x, args.y)
        elif action == "center":
            state = await client.set_position(0.5, 0.5)
        elif action == "release":
            state = await client.release()
        else:
            state = await client.get_position()

    print(_format_state(state))
    return 0
