"""``resoio grab`` subcommand: grab objects and operate them in Resonite.

A single parser with an optional positional ``action`` (default
``grab``), so flags resolve naturally whether placed before or after
the action:

* ``resoio grab`` / ``resoio grab grab`` — try to grab a grabbable
  within ``--radius`` metres of the cursor ray hit point (desktop mode
  only)
* ``resoio grab release`` — release everything the hand holds
* ``resoio grab state`` — print the hand's current hold state
* ``resoio grab use`` — press ``--button`` and hold it down (left-click
  aligns a grabbed object / activates an equipped tool)
* ``resoio grab unuse`` — release the held ``--button``
* ``resoio grab click`` — press and release ``--button`` once
* ``resoio grab equip`` / ``resoio grab dequip`` — equip a grabbed tool
  into the hand / remove the equipped tool
* ``resoio grab interactive`` — a key-driven loop (``g`` grab /
  ``r`` release / ``s`` state / ``u`` use / ``i`` unuse / ``c`` click /
  ``e`` equip / ``d`` dequip / ``q`` quit; upper-case ``U``/``I``/``C``
  use the secondary button)

``--hand {primary,left,right}`` selects the target hand (default
``primary``); ``--radius`` only affects grab; ``--button
{primary,secondary}`` selects the button for use/unuse/click (default
``primary``). The shared ``-s/--socket`` flag comes from the common
parent parser. All flags work both before and after the action (e.g.
``resoio grab --hand left use`` and ``resoio grab use --hand left``).
After every action the resulting state is printed.
"""

from __future__ import annotations

import argparse
import os
import sys
import termios
import tty
from contextlib import contextmanager
from typing import TYPE_CHECKING, TextIO

from resoio.cli import output

if TYPE_CHECKING:
    from collections.abc import Generator

    from resoio.grabber import GrabState


def register(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
    common: argparse.ArgumentParser,
) -> None:
    """Register the ``grab`` subparser.

    One flat parser: the positional ``action`` is optional
    (``nargs="?"``, default ``grab``) and dispatch happens on
    ``args.action`` inside :func:`_run`.
    """
    parser = subparsers.add_parser(
        "grab",
        parents=[common],
        help="Grab and operate objects (grab/use/equip/...).",
        description=(
            "Drive the Resonite IO Grabber service from the shell. "
            "Without an action the grab action runs, taking a --radius "
            "around the cursor ray hit point (desktop mode only). use / "
            "unuse press and release --button (left/right click) with "
            "hold semantics; equip / dequip handle tools. The resulting "
            "hold state is printed after every action."
        ),
    )
    parser.add_argument(
        "action",
        nargs="?",
        default="grab",
        choices=[
            "grab",
            "release",
            "state",
            "use",
            "unuse",
            "click",
            "equip",
            "dequip",
            "interactive",
        ],
        help="The grab action to perform (default: grab).",
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
    parser.add_argument(
        "--button",
        choices=["primary", "secondary"],
        default="primary",
        help="Button for use/unuse/click (default: primary = left-click).",
    )
    parser.add_argument(
        "--strength",
        type=float,
        default=1.0,
        help=(
            "Primary press strength 0..1 for use/click (default 1.0); "
            "ignored for other actions and for the secondary button."
        ),
    )
    output.add_format_argument(parser)
    parser.set_defaults(func=_run)


def _format_state(state: GrabState) -> str:
    names = ", ".join(state.object_names)
    held = ", ".join(state.held_buttons)
    return (
        f"hand={state.hand} is_holding={state.is_holding} "
        f"objects=[{names}] equipped={state.is_tool_equipped} "
        f"tool={state.equipped_tool_name} held=[{held}] "
        f"unix_nanos={state.unix_nanos}"
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
        "resoio grab interactive — controls\n"
        "  g : grab at cursor ray hit point\n"
        "  r : release\n"
        "  s : print current state\n"
        "  u : use (hold primary) / U : use secondary\n"
        "  i : unuse primary / I : unuse secondary\n"
        "  c : click primary / C : click secondary\n"
        "  e : equip grabbed tool / d : dequip\n"
        "  q : quit",
        file=stream,
    )


async def _run_interactive(args: argparse.Namespace) -> int:
    """Key-driven grab / use / equip loop over the Grabber UDS."""
    from resoio.grabber import GrabberButtonArg, GrabberClient, GrabberHandArg

    hand: GrabberHandArg = args.hand
    button: GrabberButtonArg

    _print_interactive_help(sys.stderr)

    try:
        stdin_fd = sys.stdin.fileno()
    except (OSError, ValueError):
        print("resoio grab interactive: stdin has no fd", file=sys.stderr)
        return 1

    async with GrabberClient(args.socket) as client:
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
                    elif key in ("u", "U"):
                        button = "secondary" if key.isupper() else "primary"
                        state = await client.use(hand=hand, button=button)
                        print(_format_state(state))
                    elif key in ("i", "I"):
                        button = "secondary" if key.isupper() else "primary"
                        state = await client.unuse(hand=hand, button=button)
                        print(_format_state(state))
                    elif key in ("c", "C"):
                        button = "secondary" if key.isupper() else "primary"
                        state = await client.click(hand=hand, button=button)
                        print(_format_state(state))
                    elif key == "e":
                        state = await client.equip(hand=hand)
                        print(_format_state(state))
                    elif key == "d":
                        state = await client.dequip(hand=hand)
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
        # ``--format`` lives on the shared flat parser so grab/release/state
        # can emit json, but the interactive loop is human-only (a carve-out):
        # reject a structured request rather than silently ignoring it.
        if output.is_structured(args.format):
            print(
                "resoio grab interactive: --format is not supported "
                "(interactive output is human-only); use grab / release / "
                "state for structured output.",
                file=sys.stderr,
            )
            return 2
        return await _run_interactive(args)

    # Deferred to keep `resoio --help` and shell completion fast.
    from resoio.grabber import GrabberClient

    async with GrabberClient(args.socket) as client:
        if action == "grab":
            result = await client.grab(hand=args.hand, radius=args.radius)
            if output.is_structured(args.format):
                output.emit(
                    {
                        "grabbed": result.grabbed,
                        "hand": result.state.hand,
                        "is_holding": result.state.is_holding,
                        "object_names": list(result.state.object_names),
                        "is_tool_equipped": result.state.is_tool_equipped,
                        "equipped_tool_name": result.state.equipped_tool_name,
                        "held_buttons": list(result.state.held_buttons),
                        "unix_nanos": result.state.unix_nanos,
                    },
                    args.format,
                )
            else:
                print(f"grabbed={result.grabbed}")
                print(_format_state(result.state))
            return 0
        if action == "release":
            state = await client.release(hand=args.hand)
        elif action == "state":
            state = await client.get_state(hand=args.hand)
        elif action == "use":
            state = await client.use(
                hand=args.hand, button=args.button, strength=args.strength
            )
        elif action == "unuse":
            state = await client.unuse(hand=args.hand, button=args.button)
        elif action == "click":
            state = await client.click(
                hand=args.hand, button=args.button, strength=args.strength
            )
        elif action == "equip":
            state = await client.equip(hand=args.hand)
        else:
            state = await client.dequip(hand=args.hand)

    if output.is_structured(args.format):
        output.emit(state, args.format)
    else:
        print(_format_state(state))
    return 0
