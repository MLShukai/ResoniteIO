"""``resoio dash`` subcommand: drive the Esc dash (userspace overlay) menu.

Flat dispatch via a positional ``action`` (no nested subparsers per
project convention):

* ``open`` / ``close`` / ``state`` — open/close the dash or read its state
* ``tree`` — list the current dash UI tree; each element carries a
  language-independent ``ref_id`` (engine RefID) and ``locale_key``
* ``invoke <ref_id>`` — press the element identified by ``ref_id``
* ``screens`` — list the dash screens (tabs); each carries a
  language-independent ``key`` and ``ref_id`` (browse)
* ``set-screen <key>`` / ``set-screen --ref-id <ref_id>`` — navigate to a
  screen by its language-independent ``key`` or exact ``ref_id`` (select)

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
    from resoio.dash import DashActionResult, DashScreen, DashState, DashTree


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
        help="Drive the Esc dash menu (open/close/state/tree/invoke/screens).",
        description=(
            "Drive the Resonite IO Dash service from the shell. Pick an "
            "action (open / close / state / tree / invoke / screens / "
            "set-screen); invoke requires a language-independent ref_id from "
            "'tree', and set-screen requires a screen key from 'screens' (or "
            "--ref-id). The resulting state / tree / screen list / action "
            "result is printed."
        ),
    )
    parser.add_argument(
        "action",
        choices=["open", "close", "state", "tree", "invoke", "screens", "set-screen"],
        help="The dash action to perform.",
    )
    parser.add_argument(
        "target",
        nargs="?",
        default=None,
        help=(
            "For 'invoke': target ref_id (from 'tree'). For 'set-screen': "
            "screen key (from 'screens')."
        ),
    )
    parser.add_argument(
        "--ref-id",
        default="",
        help="For 'set-screen': select the screen by its exact ref_id.",
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


def _format_screens(screens: list[DashScreen]) -> str:
    return "\n".join(
        f"[{s.ref_id}] {s.key} {s.name} is_current={s.is_current} "
        f"enabled={s.enabled} label={s.label!r}"
        for s in screens
    )


async def _run(args: argparse.Namespace) -> int:
    """Dispatch on ``args.action`` and print the resulting
    state/tree/result."""
    # Deferred to keep `resoio --help` and shell completion fast.
    from resoio.dash import DashClient

    action: str = args.action
    if action == "invoke" and args.target is None:
        print("error: 'invoke' requires a ref_id", file=sys.stderr)
        return 2

    set_screen_ref_id: str = args.ref_id
    set_screen_key: str = args.target or ""
    if action == "set-screen" and not set_screen_ref_id and not set_screen_key:
        print("error: 'set-screen' requires a key or --ref-id", file=sys.stderr)
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
        elif action == "screens":
            print(_format_screens(await client.list_screens()))
        elif action == "set-screen":
            result = await client.set_screen(
                ref_id=set_screen_ref_id, key=set_screen_key
            )
            print(_format_result(result))
        else:
            print(_format_result(await client.invoke(args.target)))
    return 0
