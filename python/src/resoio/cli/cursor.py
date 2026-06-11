"""``resoio cursor <subcommand>``: move / hold / read the desktop cursor.

Nested subcommands mirror ``resoio world``: a ``cursor`` parent parser
holds the leaves, each with the shared ``-s/--socket`` parent re-attached
(argparse does not inherit it) and its own handler set via
``set_defaults(func=...)``:

* ``set <x> <y>`` — move the cursor to normalized ``(x, y)`` in ``[0, 1]``
  and hold it there until ``release``
* ``center`` — move the cursor to the screen center ``(0.5, 0.5)`` and
  hold it there until ``release``
* ``get`` — print the current cursor position and hold state (no movement)
* ``release`` — release the hold (idempotent)

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
    """Register the ``cursor`` subparser with its nested subcommands."""
    parser = subparsers.add_parser(
        "cursor",
        parents=[common],
        help="Move / hold / read the desktop cursor (set/center/get/release).",
        description=(
            "Drive the Resonite IO Cursor service from the shell. Pick a "
            "subcommand: 'set' needs normalized x y in [0,1] and holds the "
            "cursor there until 'release'; 'center' moves to (0.5, 0.5) and "
            "holds; 'get' prints the current position and hold state; "
            "'release' releases the hold. The resulting cursor state is "
            "printed after every action."
        ),
    )
    cursor_subs = parser.add_subparsers(dest="cursor_command", required=True)

    set_parser = cursor_subs.add_parser(
        "set",
        parents=[common],
        help="Move the cursor to normalized (x, y) and hold it until 'release'.",
    )
    set_parser.add_argument("x", type=float, help="Normalized x in [0,1].")
    set_parser.add_argument("y", type=float, help="Normalized y in [0,1].")
    set_parser.set_defaults(func=_run_set)

    center_parser = cursor_subs.add_parser(
        "center",
        parents=[common],
        help="Move the cursor to (0.5, 0.5) and hold it until 'release'.",
    )
    center_parser.set_defaults(func=_run_center)

    get_parser = cursor_subs.add_parser(
        "get",
        parents=[common],
        help="Print the current cursor position and hold state (no movement).",
    )
    get_parser.set_defaults(func=_run_get)

    release_parser = cursor_subs.add_parser(
        "release",
        parents=[common],
        help="Release the cursor hold (idempotent).",
    )
    release_parser.set_defaults(func=_run_release)


def _format_state(state: CursorState) -> str:
    return (
        f"x={state.x} y={state.y} "
        f"window={state.window_width}x{state.window_height} held={state.held}"
    )


async def _run_set(args: argparse.Namespace) -> int:
    # Deferred to keep `resoio --help` and shell completion fast.
    from resoio.cursor import CursorClient

    if not (0.0 <= args.x <= 1.0) or not (0.0 <= args.y <= 1.0):
        print(
            f"error: x and y must be in [0,1], got ({args.x}, {args.y})",
            file=sys.stderr,
        )
        return 2

    async with CursorClient(args.socket) as client:
        state = await client.set_position(args.x, args.y)
    print(_format_state(state))
    return 0


async def _run_center(args: argparse.Namespace) -> int:
    from resoio.cursor import CursorClient

    async with CursorClient(args.socket) as client:
        state = await client.set_position(0.5, 0.5)
    print(_format_state(state))
    return 0


async def _run_get(args: argparse.Namespace) -> int:
    from resoio.cursor import CursorClient

    async with CursorClient(args.socket) as client:
        state = await client.get_position()
    print(_format_state(state))
    return 0


async def _run_release(args: argparse.Namespace) -> int:
    from resoio.cursor import CursorClient

    async with CursorClient(args.socket) as client:
        state = await client.release()
    print(_format_state(state))
    return 0
