"""``resoio dash [<subcommand>]``: drive the Esc dash (userspace overlay).

Structured, flat, agent-first commands. Running ``resoio dash`` with no
subcommand prints a **summary** ("what can I do now"): the open state, the
current tab, and a numbered list of the current tab's controls. The leaves
mirror ``resoio world``: a ``dash`` parent parser holds them, each with the
shared ``-s/--socket`` parent re-attached (argparse does not inherit it) and
its own handler set via ``set_defaults(func=...)``:

* ``open`` / ``close`` / ``state`` — open/close the dash or read its state
* ``tabs`` — list the bottom tab bar (``*`` marks the current tab)
* ``tab <selector>`` — switch to a tab
* ``ls`` — list the current tab's controls (numbered; ``--all`` adds disabled)
* ``invoke <selector>`` — press a control
* ``scroll <selector> <dx> <dy>`` — scroll a control by ``(dx, dy)``
* ``highlight <selector>`` — hover-highlight a control

A ``<selector>`` is resolved client-side against the just-fetched listing
(tabs for ``tab``; controls for ``invoke`` / ``scroll`` / ``highlight``):

1. a numeric, 0-based **index** into that listing (as shown in ``tabs`` /
   ``ls``) — valid only within this one invocation; or
2. an exact ``ref_id`` / a case-insensitive exact or unique substring of the
   label / ``locale_key`` / ``name`` (via
   :func:`resoio.dash._resolve_one`).

``ref_id`` is the stable handle; index handles are positional and only valid
within a single command. Ambiguous / no-match / out-of-range selectors print
a friendly candidate list to stderr and exit ``2``.
"""

from __future__ import annotations

import argparse
import sys
from typing import TYPE_CHECKING

from resoio.cli import output
from resoio.dash import (
    DashAmbiguousMatchError,
    DashNoMatchError,
    _resolve_one,  # pyright: ignore[reportPrivateUsage]
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterable, Sequence

    from resoio.dash import (
        DashActionResult,
        DashClient,
        DashControl,
        DashState,
        DashTab,
    )


def register(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
    common: argparse.ArgumentParser,
) -> None:
    """Register the ``dash`` subparser with its nested subcommands."""
    parser = subparsers.add_parser(
        "dash",
        parents=[common],
        help="Drive the Esc dash menu (summary/open/close/tabs/tab/ls/invoke/...).",
        description=(
            "Drive the Resonite IO Dash service from the shell. With no "
            "subcommand, prints a summary of the current state, tab, and "
            "controls. Subcommands: open / close / state, tabs / tab "
            "<selector>, ls, invoke / scroll / highlight <selector>. A "
            "selector is a 0-based index from the 'tabs' / 'ls' listing, an "
            "exact ref_id, or a label / locale_key / name substring."
        ),
    )
    # No subcommand -> summary view ("what can I do now"); the summary is a
    # result-producing leaf, so --format goes on the parent parser too.
    fmt = output.build_format_parent()
    output.add_format_argument(parser)
    parser.set_defaults(func=_run_summary)
    dash_subs = parser.add_subparsers(dest="dash_command", required=False)

    open_parser = dash_subs.add_parser(
        "open",
        parents=[common, fmt],
        help="Open the dash.",
    )
    open_parser.set_defaults(func=_run_open)

    close_parser = dash_subs.add_parser(
        "close",
        parents=[common, fmt],
        help="Close the dash.",
    )
    close_parser.set_defaults(func=_run_close)

    state_parser = dash_subs.add_parser(
        "state",
        parents=[common, fmt],
        help="Read the dash open state.",
    )
    state_parser.set_defaults(func=_run_state)

    tabs_parser = dash_subs.add_parser(
        "tabs",
        parents=[common, fmt],
        help="List the bottom tab bar ('*' marks the current tab).",
    )
    tabs_parser.set_defaults(func=_run_tabs)

    tab_parser = dash_subs.add_parser(
        "tab",
        parents=[common, fmt],
        help="Switch to a tab (selector: index from 'tabs', ref_id, or label).",
    )
    tab_parser.add_argument(
        "selector",
        help="Tab selector: 0-based index, exact ref_id, or label substring.",
    )
    tab_parser.set_defaults(func=_run_tab)

    ls_parser = dash_subs.add_parser(
        "ls",
        parents=[common, fmt],
        help="List the current tab's controls (numbered).",
    )
    ls_parser.add_argument(
        "--all",
        action="store_true",
        help="Include disabled controls.",
    )
    ls_parser.set_defaults(func=_run_ls)

    invoke_parser = dash_subs.add_parser(
        "invoke",
        parents=[common, fmt],
        help="Press a control (selector: index from 'ls', ref_id, or label).",
    )
    invoke_parser.add_argument(
        "selector",
        help="Control selector: 0-based index, exact ref_id, or label substring.",
    )
    invoke_parser.set_defaults(func=_run_invoke)

    scroll_parser = dash_subs.add_parser(
        "scroll",
        parents=[common, fmt],
        help="Scroll a control by (dx, dy).",
    )
    scroll_parser.add_argument(
        "selector",
        help="Control selector: 0-based index, exact ref_id, or label substring.",
    )
    scroll_parser.add_argument("dx", type=float, help="Normalized scroll delta x.")
    scroll_parser.add_argument("dy", type=float, help="Normalized scroll delta y.")
    scroll_parser.set_defaults(func=_run_scroll)

    highlight_parser = dash_subs.add_parser(
        "highlight",
        parents=[common, fmt],
        help="Hover-highlight a control (selector: index, ref_id, or label).",
    )
    highlight_parser.add_argument(
        "selector",
        help="Control selector: 0-based index, exact ref_id, or label substring.",
    )
    highlight_parser.set_defaults(func=_run_highlight)


def _shortref(ref_id: str) -> str:
    """Trailing segment of a ``ReferenceID`` (the part that varies per
    slot)."""
    return ref_id.rsplit("@", 1)[0].rsplit("ID", 1)[-1] or ref_id


def _format_state(state: DashState) -> str:
    return f"is_open={state.is_open} open_lerp={state.open_lerp}"


def _format_tabs(tabs: list[DashTab]) -> str:
    lines: list[str] = []
    for idx, tab in enumerate(tabs):
        mark = "*" if tab.is_current else " "
        name = tab.name or tab.label or tab.locale_key
        lines.append(
            f"{mark} {idx:>2}  {name}  enabled={tab.enabled} "
            f"locale={tab.locale_key!r} label={tab.label!r} "
            f"ref_id={tab.ref_id}"
        )
    return "\n".join(lines)


def _format_controls(controls: list[DashControl]) -> str:
    lines: list[str] = []
    for idx, control in enumerate(controls):
        indent = "  " * control.depth
        lines.append(
            f"{idx:>2}  {control.control_type:<6}  enabled={control.enabled}  "
            f"{_shortref(control.ref_id)}  {indent}{control.label!r}"
        )
    return "\n".join(lines)


def _format_summary(
    state: DashState,
    tabs: list[DashTab],
    controls: list[DashControl],
) -> str:
    current = next((tab for tab in tabs if tab.is_current), None)
    if current is None:
        tab_line = "current tab: (none)"
    else:
        name = current.name or current.label or current.locale_key
        tab_line = f"current tab: {name} (ref_id={current.ref_id})"
    lines = [_format_state(state), tab_line, "controls:"]
    if controls:
        lines.append(_format_controls(controls))
    else:
        lines.append("  (none)")
    return "\n".join(lines)


def _format_result(result: DashActionResult) -> str:
    return (
        f"ok={result.ok} found={result.found} "
        f"ref_id={result.ref_id} detail={result.detail!r}"
    )


def _resolve_selector[T](
    items: Sequence[T],
    selector: str,
    keys: Callable[[T], Iterable[str]],
    hint: Callable[[T], str],
) -> T | None:
    """Resolve a selector against ``items``, printing a friendly error on
    failure.

    A numeric ``selector`` is a 0-based index into ``items`` (bounds-checked
    here); anything else is matched by :func:`resoio.dash._resolve_one` using
    ``keys``. Returns the matched item, or ``None`` after writing a candidate
    list (one ``hint`` per item) to stderr -- the caller then exits ``2``.
    """
    if selector.isdigit():
        index = int(selector)
        if 0 <= index < len(items):
            return items[index]
        _print_index_error(selector, len(items), [hint(i) for i in items])
        return None
    try:
        return _resolve_one(items, selector, keys)
    except (DashNoMatchError, DashAmbiguousMatchError) as exc:
        _print_match_error(exc, [hint(i) for i in items])
        return None


def _resolve_tab(tabs: list[DashTab], selector: str) -> DashTab | None:
    """Resolve a tab selector (index / ref_id / label), or ``None`` on
    error."""
    from resoio.dash import _tab_keys  # pyright: ignore[reportPrivateUsage]

    return _resolve_selector(tabs, selector, _tab_keys, _tab_hint)


def _resolve_control(controls: list[DashControl], selector: str) -> DashControl | None:
    """Resolve a control selector (index / ref_id / label), or ``None`` on
    error."""
    from resoio.dash import _control_keys  # pyright: ignore[reportPrivateUsage]

    return _resolve_selector(controls, selector, _control_keys, _control_hint)


def _tab_hint(tab: DashTab) -> str:
    label = tab.name or tab.label or tab.locale_key
    return f"{label!r} ({_shortref(tab.ref_id)})"


def _control_hint(control: DashControl) -> str:
    label = control.label or control.locale_key or control.control_type
    return f"{label!r} ({_shortref(control.ref_id)})"


def _print_index_error(selector: str, count: int, hints: list[str]) -> None:
    print(
        f"error: index {selector} out of range (0..{count - 1})",
        file=sys.stderr,
    )
    _print_candidates(hints)


def _print_match_error(exc: ValueError, hints: list[str]) -> None:
    print(f"error: {exc}", file=sys.stderr)
    _print_candidates(hints)


def _print_candidates(hints: list[str]) -> None:
    if not hints:
        print("  (no candidates)", file=sys.stderr)
        return
    print("candidates:", file=sys.stderr)
    for idx, hint in enumerate(hints):
        print(f"  [{idx}] {hint}", file=sys.stderr)


async def _run_summary(args: argparse.Namespace) -> int:
    # Deferred to keep `resoio --help` and shell completion fast.
    from resoio.dash import DashClient

    async with DashClient(args.socket) as client:
        state = await client.get_state()
        tabs = await client.list_tabs()
        controls = await client.list_controls()
    if output.is_structured(args.format):
        output.emit(
            {"state": state, "tabs": list(tabs), "controls": list(controls)},
            args.format,
        )
    else:
        print(_format_summary(state, tabs, controls))
    return 0


async def _run_open(args: argparse.Namespace) -> int:
    from resoio.dash import DashClient

    async with DashClient(args.socket) as client:
        state = await client.open()
    if output.is_structured(args.format):
        output.emit(state, args.format)
    else:
        print(_format_state(state))
    return 0


async def _run_close(args: argparse.Namespace) -> int:
    from resoio.dash import DashClient

    async with DashClient(args.socket) as client:
        state = await client.close()
    if output.is_structured(args.format):
        output.emit(state, args.format)
    else:
        print(_format_state(state))
    return 0


async def _run_state(args: argparse.Namespace) -> int:
    from resoio.dash import DashClient

    async with DashClient(args.socket) as client:
        state = await client.get_state()
    if output.is_structured(args.format):
        output.emit(state, args.format)
    else:
        print(_format_state(state))
    return 0


async def _run_tabs(args: argparse.Namespace) -> int:
    from resoio.dash import DashClient

    async with DashClient(args.socket) as client:
        tabs = await client.list_tabs()
    if output.is_structured(args.format):
        output.emit(list(tabs), args.format)
    else:
        print(_format_tabs(tabs))
    return 0


async def _run_tab(args: argparse.Namespace) -> int:
    from resoio.dash import DashClient

    async with DashClient(args.socket) as client:
        tabs = await client.list_tabs()
        tab = _resolve_tab(tabs, args.selector)
        if tab is None:
            return 2
        result = await client.set_tab(ref_id=tab.ref_id)
    if output.is_structured(args.format):
        output.emit(result, args.format)
    else:
        print(_format_result(result))
    return 0


async def _run_ls(args: argparse.Namespace) -> int:
    from resoio.dash import DashClient

    async with DashClient(args.socket) as client:
        controls = await client.list_controls(include_disabled=args.all)
    if output.is_structured(args.format):
        output.emit(list(controls), args.format)
    else:
        print(_format_controls(controls))
    return 0


async def _run_control_action(
    args: argparse.Namespace,
    action: Callable[[DashClient, DashControl], Awaitable[DashActionResult]],
) -> int:
    """Resolve ``args.selector`` against the current tab and apply ``action``.

    Fetches the current controls, resolves the selector (exit ``2`` with a
    candidate list on failure, without issuing any action RPC), then runs
    ``action`` against the resolved control and prints the result line.
    """
    from resoio.dash import DashClient

    async with DashClient(args.socket) as client:
        controls = await client.list_controls()
        control = _resolve_control(controls, args.selector)
        if control is None:
            return 2
        result = await action(client, control)
    if output.is_structured(args.format):
        output.emit(result, args.format)
    else:
        print(_format_result(result))
    return 0


async def _run_invoke(args: argparse.Namespace) -> int:
    return await _run_control_action(
        args, lambda client, control: client.invoke(control.ref_id)
    )


async def _run_scroll(args: argparse.Namespace) -> int:
    return await _run_control_action(
        args,
        lambda client, control: client.scroll(
            control.ref_id, delta_x=args.dx, delta_y=args.dy
        ),
    )


async def _run_highlight(args: argparse.Namespace) -> int:
    return await _run_control_action(
        args, lambda client, control: client.highlight(control.ref_id)
    )
