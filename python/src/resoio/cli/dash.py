"""``resoio dash`` subcommand: drive the Esc dash (userspace overlay) menu.

Flat dispatch via a positional ``action`` (no nested subparsers per
project convention):

* ``open`` / ``close`` / ``state`` — open/close the dash or read its state
* ``tree`` — list the current dash UI tree; each element carries a
  language-independent ``ref_id`` (engine RefID) and ``locale_key``
* ``invoke <ref_id>`` — press the element identified by ``ref_id``

``--interactable-only`` filters ``tree`` to interactable elements and
``--root-ref-id`` scopes it to a subtree. The shared ``-s/--socket`` flag
comes from the common parent parser. The CLI surface is intentionally
"browse + select"; ``highlight`` / ``scroll`` live on
:class:`resoio.dash.DashClient` (and the e2e harness) only.
"""

from __future__ import annotations

import argparse
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from resoio.dash import DashActionResult, DashState, DashTree


def register(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
    common: argparse.ArgumentParser,
) -> None:
    """Register the flat ``dash`` subparser.

    Dispatch rules (no nested subcommands) live in the module docstring.
    """
    parser = subparsers.add_parser(
        "dash",
        parents=[common],
        help="Drive the Esc dash menu (open/close/state/tree/invoke).",
        description=(
            "Drive the Resonite IO Dash service from the shell. Pick an "
            "action (open / close / state / tree / invoke); invoke requires "
            "a language-independent ref_id obtained from 'tree'. The "
            "resulting state / tree / action result is printed."
        ),
    )
    parser.add_argument(
        "action",
        choices=["open", "close", "state", "tree", "invoke"],
        help="The dash action to perform.",
    )
    parser.add_argument(
        "ref_id",
        nargs="?",
        default=None,
        help="Target element ref_id for 'invoke' (from 'tree').",
    )
    parser.add_argument(
        "--interactable-only",
        action="store_true",
        help="For 'tree': only list interactable elements.",
    )
    parser.add_argument(
        "--root-ref-id",
        default="",
        help="For 'tree': scope the tree to this element's subtree.",
    )
    parser.set_defaults(func=_run)


def _format_state(state: DashState) -> str:
    return f"is_open={state.is_open}\nopen_lerp={state.open_lerp}"


def _format_tree(tree: DashTree) -> str:
    lines: list[str] = [f"screen={tree.screen_width}x{tree.screen_height}"]
    for e in tree.elements:
        space = "screen" if e.rect.is_screen_space else "canvas"
        lines.append(
            f"[{e.ref_id}] {e.type} locale={e.locale_key!r} label={e.label!r} "
            f"enabled={e.enabled} interactable={e.interactable} "
            f"rect=({e.rect.x}, {e.rect.y}, {e.rect.width}, {e.rect.height}, {space})"
        )
    return "\n".join(lines)


def _format_result(result: DashActionResult) -> str:
    return (
        f"ok={result.ok} found={result.found} "
        f"ref_id={result.ref_id} detail={result.detail!r}"
    )


async def _run(args: argparse.Namespace) -> int:
    """Dispatch on ``args.action`` and print the resulting
    state/tree/result."""
    # Deferred to keep `resoio --help` and shell completion fast.
    from resoio.dash import DashClient

    action: str = args.action
    if action == "invoke" and args.ref_id is None:
        print("error: 'invoke' requires a ref_id", file=sys.stderr)
        return 2

    async with DashClient(args.socket) as client:
        if action == "open":
            print(_format_state(await client.open()))
        elif action == "close":
            print(_format_state(await client.close()))
        elif action == "state":
            print(_format_state(await client.get_state()))
        elif action == "tree":
            tree = await client.get_tree(
                interactable_only=args.interactable_only,
                root_ref_id=args.root_ref_id,
            )
            print(_format_tree(tree))
        else:
            print(_format_result(await client.invoke(args.ref_id)))
    return 0
