"""``resoio dash <subcommand>``: drive the Esc dash (userspace overlay) menu.

Nested subcommands mirror ``resoio world``: a ``dash`` parent parser
holds the leaves, each with the shared ``-s/--socket`` parent re-attached
(argparse does not inherit it) and its own handler set via
``set_defaults(func=...)``:

* ``open`` / ``close`` / ``state`` — open/close the dash or read its state
* ``tree`` — list the current dash UI tree; each element carries a
  language-independent ``ref_id`` (engine RefID) and ``locale_key``
* ``invoke <ref_id>`` — press the element identified by ``ref_id``
* ``screens`` — list the dash screens (tabs); each carries a
  language-independent ``key`` and ``ref_id`` (browse)
* ``set-screen <key>`` / ``set-screen --ref-id <ref_id>`` — navigate to a
  screen by its language-independent ``key`` or exact ``ref_id`` (select)

``--interactable-only`` filters ``tree`` to interactable elements and
``--root-ref-id`` scopes it to a subtree. The CLI surface is intentionally
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
    """Register the ``dash`` subparser with its nested subcommands."""
    parser = subparsers.add_parser(
        "dash",
        parents=[common],
        help="Drive the Esc dash menu (open/close/state/tree/invoke/screens).",
        description=(
            "Drive the Resonite IO Dash service from the shell. Pick a "
            "subcommand (open / close / state / tree / invoke / screens / "
            "set-screen); invoke requires a language-independent ref_id from "
            "'tree', and set-screen requires a screen key from 'screens' (or "
            "--ref-id). The resulting state / tree / screen list / action "
            "result is printed."
        ),
    )
    dash_subs = parser.add_subparsers(dest="dash_command", required=True)

    open_parser = dash_subs.add_parser(
        "open",
        parents=[common],
        help="Open the dash.",
    )
    open_parser.set_defaults(func=_run_open)

    close_parser = dash_subs.add_parser(
        "close",
        parents=[common],
        help="Close the dash.",
    )
    close_parser.set_defaults(func=_run_close)

    state_parser = dash_subs.add_parser(
        "state",
        parents=[common],
        help="Read the dash open state.",
    )
    state_parser.set_defaults(func=_run_state)

    tree_parser = dash_subs.add_parser(
        "tree",
        parents=[common],
        help="List the current dash UI tree.",
    )
    tree_parser.add_argument(
        "--interactable-only",
        action="store_true",
        help="Only list interactable elements.",
    )
    tree_parser.add_argument(
        "--root-ref-id",
        default="",
        help="Scope the tree to this element's subtree.",
    )
    tree_parser.set_defaults(func=_run_tree)

    invoke_parser = dash_subs.add_parser(
        "invoke",
        parents=[common],
        help="Press the element identified by ref_id (from 'tree').",
    )
    invoke_parser.add_argument(
        "ref_id",
        help="Target ref_id (from 'tree').",
    )
    invoke_parser.set_defaults(func=_run_invoke)

    screens_parser = dash_subs.add_parser(
        "screens",
        parents=[common],
        help="List the dash screens (tabs).",
    )
    screens_parser.set_defaults(func=_run_screens)

    set_screen_parser = dash_subs.add_parser(
        "set-screen",
        parents=[common],
        help="Navigate to a screen by key (from 'screens') or --ref-id.",
    )
    set_screen_parser.add_argument(
        "key",
        nargs="?",
        default=None,
        help="Screen key (from 'screens').",
    )
    set_screen_parser.add_argument(
        "--ref-id",
        default="",
        help="Select the screen by its exact ref_id.",
    )
    set_screen_parser.set_defaults(func=_run_set_screen)


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


async def _run_open(args: argparse.Namespace) -> int:
    # Deferred to keep `resoio --help` and shell completion fast.
    from resoio.dash import DashClient

    async with DashClient(args.socket) as client:
        print(_format_state(await client.open()))
    return 0


async def _run_close(args: argparse.Namespace) -> int:
    from resoio.dash import DashClient

    async with DashClient(args.socket) as client:
        print(_format_state(await client.close()))
    return 0


async def _run_state(args: argparse.Namespace) -> int:
    from resoio.dash import DashClient

    async with DashClient(args.socket) as client:
        print(_format_state(await client.get_state()))
    return 0


async def _run_tree(args: argparse.Namespace) -> int:
    from resoio.dash import DashClient

    async with DashClient(args.socket) as client:
        tree = await client.get_tree(
            interactable_only=args.interactable_only,
            root_ref_id=args.root_ref_id,
        )
    print(_format_tree(tree))
    return 0


async def _run_invoke(args: argparse.Namespace) -> int:
    from resoio.dash import DashClient

    async with DashClient(args.socket) as client:
        print(_format_result(await client.invoke(args.ref_id)))
    return 0


async def _run_screens(args: argparse.Namespace) -> int:
    from resoio.dash import DashClient

    async with DashClient(args.socket) as client:
        print(_format_screens(await client.list_screens()))
    return 0


async def _run_set_screen(args: argparse.Namespace) -> int:
    from resoio.dash import DashClient

    key: str = args.key or ""
    ref_id: str = args.ref_id
    if not key and not ref_id:
        print("error: 'set-screen' requires a key or --ref-id", file=sys.stderr)
        return 2

    async with DashClient(args.socket) as client:
        result = await client.set_screen(ref_id=ref_id, key=key)
    print(_format_result(result))
    return 0
