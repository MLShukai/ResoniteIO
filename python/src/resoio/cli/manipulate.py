"""``resoio manipulate`` subcommand: grab / release objects in Resonite.

Flat dispatch via a positional ``action`` (no nested subparsers per
project convention):

* ``grab`` — try to grab a grabbable within ``--radius`` metres of the
  cursor ray hit point (desktop mode only)
* ``release`` — release everything the hand holds
* ``state`` — print the hand's current hold state
* ``interactive`` — a key-driven loop (``g`` grab / ``r`` release /
  ``s`` state / ``q`` quit)

``--hand {primary,left,right}`` selects the target hand (default
``primary``). The shared ``-s/--socket`` flag comes from the common
parent parser. After every action the resulting state is printed.
"""

from __future__ import annotations

import argparse
import os
import sys
import termios
import tty
from contextlib import contextmanager
from typing import TYPE_CHECKING, TextIO

if TYPE_CHECKING:
    from collections.abc import Generator

    from resoio.manipulation import GrabState


def register(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
    common: argparse.ArgumentParser,
) -> None:
    """Register the flat ``manipulate`` subparser.

    Dispatch rules (no nested subcommands) live in the module docstring.
    """
    parser = subparsers.add_parser(
        "manipulate",
        parents=[common],
        help="Grab / release objects (grab/release/state/interactive).",
        description=(
            "Drive the Resonite IO Manipulation service from the shell. "
            "Pick an action (grab / release / state / interactive); grab "
            "takes a --radius around the cursor ray hit point (desktop "
            "mode only). The resulting hold state is printed after every "
            "action."
        ),
    )
    parser.add_argument(
        "action",
        choices=["grab", "release", "state", "interactive"],
        help="The manipulation action to perform.",
    )
    parser.add_argument(
        "--hand",
        choices=["primary", "left", "right"],
        default="primary",
        help="Target hand / interaction handler (default: primary).",
    )
    parser.add_argument(
        "--radius",
        type=float,
        default=0.0,
        help="Grab sphere radius in metres (<= 0 uses the server default).",
    )
    parser.set_defaults(func=_run)


def _format_state(state: GrabState) -> str:
    names = ", ".join(state.object_names)
    return (
        f"hand={state.hand} is_holding={state.is_holding} "
        f"objects=[{names}] unix_nanos={state.unix_nanos}"
    )


@contextmanager
def _raw_tty(stream: TextIO) -> Generator[None]:
    """Put ``stream`` into cbreak mode and restore on exit.

    The ``finally`` branch is the load-bearing piece: if the loop
    crashes mid-session the terminal must end up echoing again or the
    user's shell is left effectively unusable. A non-tty fd (pipe /
    file) is a no-op rather than an error so end-to-end tests can feed
    canned input via ``os.pipe()`` without needing a pty.
    """
    fd: int
    try:
        fd = stream.fileno()
    except (OSError, ValueError):
        yield
        return
    if not os.isatty(fd):
        yield
        return
    original = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        yield
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, original)


def _print_interactive_help(stream: TextIO) -> None:
    """Print the interactive keymap to ``stream`` once at start."""
    print(
        "resoio manipulate interactive — controls\n"
        "  g : grab at cursor ray hit point\n"
        "  r : release\n"
        "  s : print current state\n"
        "  q : quit",
        file=stream,
    )


async def _run_interactive(args: argparse.Namespace) -> int:
    """Key-driven grab/release loop over the Manipulation UDS."""
    from resoio.manipulation import ManipulationClient, ManipulationHandArg

    hand: ManipulationHandArg = args.hand

    _print_interactive_help(sys.stderr)

    try:
        stdin_fd = sys.stdin.fileno()
    except (OSError, ValueError):
        print("resoio manipulate interactive: stdin has no fd", file=sys.stderr)
        return 1

    async with ManipulationClient(args.socket) as client:
        with _raw_tty(sys.stdin):
            while True:
                data = os.read(stdin_fd, 64)
                if not data:
                    # EOF (pipe closed / Ctrl-D): exit cleanly.
                    break
                stop = False
                for byte in data:
                    key = chr(byte)
                    if key == "g":
                        result = await client.grab(hand=hand)
                        print(f"grabbed={result.grabbed} {_format_state(result.state)}")
                    elif key == "r":
                        state = await client.release(hand=hand)
                        print(_format_state(state))
                    elif key == "s":
                        state = await client.get_state(hand=hand)
                        print(_format_state(state))
                    elif key == "q":
                        stop = True
                        break
                if stop:
                    break
    return 0


async def _run(args: argparse.Namespace) -> int:
    """Dispatch on ``args.action`` and print the resulting hold state."""
    action: str = args.action
    if action == "interactive":
        return await _run_interactive(args)

    # Deferred to keep `resoio --help` and shell completion fast.
    from resoio.manipulation import ManipulationClient

    async with ManipulationClient(args.socket) as client:
        if action == "grab":
            result = await client.grab(hand=args.hand, radius=args.radius)
            print(f"grabbed={result.grabbed}")
            print(_format_state(result.state))
            return 0
        if action == "release":
            state = await client.release(hand=args.hand)
        else:
            state = await client.get_state(hand=args.hand)

    print(_format_state(state))
    return 0
