"""``resoio world <subcommand>``: browse / join / start / manage worlds.

Nested subcommands mirror ``resoio locomotion``: a ``world`` parent
parser holds the leaves (``sessions`` / ``records`` / ``thumbnail`` /
``join`` / ``start`` / ``list`` / ``focus`` / ``leave`` / ``current``),
each with the shared ``-s/--socket`` parent re-attached (argparse does
not inherit it) and its own ``_run_*`` handler set via
``set_defaults(func=...)``. The heavy ``from resoio.world import ...`` is
deferred into each handler so ``resoio --help`` stays fast.
"""

from __future__ import annotations

import argparse
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from resoio.world import OpenWorld, WorldRecord, WorldSession


_SESSION_FILTER_CHOICES = ("all", "friends", "headless")
_RECORD_SOURCE_CHOICES = ("public", "featured", "own", "group")
_RECORD_SORT_CHOICES = (
    "creation",
    "updated",
    "published",
    "visits",
    "name",
    "random",
)

_DEFAULT_ROW_LIMIT = 20


def _add_table_args(parser: argparse.ArgumentParser) -> None:
    """Attach the shared ``--wide`` / ``--limit`` / ``--all`` table flags."""
    parser.add_argument(
        "-w",
        "--wide",
        action="store_true",
        help="Show all columns, including thumbnail_url.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=_DEFAULT_ROW_LIMIT,
        help=f"Max rows to print (default: {_DEFAULT_ROW_LIMIT}).",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        dest="show_all",
        help="Print every row (overrides --limit).",
    )


def register(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
    common: argparse.ArgumentParser,
) -> None:
    """Register the ``world`` subparser with its nested subcommands."""
    parser = subparsers.add_parser(
        "world",
        parents=[common],
        help="Browse, join, start, and manage Resonite worlds.",
        description=(
            "Drive the Resonite IO World service. Three browse/manage "
            "categories: 'sessions' lists 起動中ライブセッション (join で "
            "参加); 'records' lists 保存済みワールド (start で起動); 'list' "
            "lists ローカルに開いているワールド (focus / leave で管理). "
            "'thumbnail' downloads a session/record thumbnail image."
        ),
    )
    world_subs = parser.add_subparsers(dest="world_command", required=True)

    _register_sessions(world_subs, common)
    _register_records(world_subs, common)
    _register_thumbnail(world_subs, common)
    _register_join(world_subs, common)
    _register_start(world_subs, common)
    _register_list(world_subs, common)
    _register_focus(world_subs, common)
    _register_leave(world_subs, common)
    _register_current(world_subs, common)


def _register_sessions(
    subs: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
    common: argparse.ArgumentParser,
) -> None:
    parser = subs.add_parser(
        "sessions",
        parents=[common],
        help="List live sessions.",
    )
    parser.add_argument("--search", default="", help="Name substring filter.")
    parser.add_argument(
        "--filter",
        choices=_SESSION_FILTER_CHOICES,
        default="all",
        help="Session filter (default: all).",
    )
    parser.add_argument(
        "--min-users",
        type=int,
        default=0,
        dest="min_users",
        help="Minimum active users (default: 0 = no lower bound).",
    )
    parser.add_argument(
        "--page", type=int, default=0, help="0-based page number (default: 0)."
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=0,
        dest="page_size",
        help="Items per page (default: 0 = unlimited).",
    )
    _add_table_args(parser)
    parser.set_defaults(func=_run_sessions)


def _register_records(
    subs: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
    common: argparse.ArgumentParser,
) -> None:
    parser = subs.add_parser(
        "records",
        parents=[common],
        help="List world records.",
    )
    parser.add_argument(
        "--source",
        choices=_RECORD_SOURCE_CHOICES,
        default="public",
        help="Record source (default: public).",
    )
    parser.add_argument(
        "--tag",
        action="append",
        default=None,
        dest="tags",
        help="Required tag (AND condition; repeatable).",
    )
    parser.add_argument("--owner", default="", help="Owner id for group / own.")
    parser.add_argument(
        "--offset", type=int, default=0, help="Server-side paging offset."
    )
    parser.add_argument(
        "--count", type=int, default=0, help="Item count (default: 0 = server default)."
    )
    parser.add_argument(
        "--sort",
        choices=_RECORD_SORT_CHOICES,
        default="creation",
        help="Sort key (default: creation).",
    )
    parser.add_argument(
        "--asc",
        action="store_true",
        help="Ascending order (default: descending).",
    )
    _add_table_args(parser)
    parser.set_defaults(func=_run_records)


def _register_thumbnail(
    subs: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
    common: argparse.ArgumentParser,
) -> None:
    parser = subs.add_parser(
        "thumbnail",
        parents=[common],
        help="Download a session / record thumbnail image.",
    )
    parser.add_argument(
        "uri",
        help="Thumbnail URI (resdb:/// or https://) from 'records --wide'.",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="Write image to this path; default writes raw bytes to stdout.",
    )
    parser.set_defaults(func=_run_thumbnail)


def _register_join(
    subs: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
    common: argparse.ArgumentParser,
) -> None:
    parser = subs.add_parser(
        "join",
        parents=[common],
        help="Join an existing session by id or url.",
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--session-id", dest="session_id", help="Session id to join.")
    target.add_argument("--url", help="Session url to join.")
    parser.add_argument(
        "--no-focus",
        action="store_true",
        dest="no_focus",
        help="Do not focus after joining.",
    )
    parser.set_defaults(func=_run_join)


def _register_start(
    subs: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
    common: argparse.ArgumentParser,
) -> None:
    parser = subs.add_parser(
        "start",
        parents=[common],
        help="Start a new session from a world record.",
    )
    parser.add_argument(
        "--record-id", dest="record_id", required=True, help="Record id to start."
    )
    parser.add_argument(
        "--owner-id", dest="owner_id", default="", help="Record owner id."
    )
    parser.add_argument(
        "--no-focus",
        action="store_true",
        dest="no_focus",
        help="Do not focus after starting.",
    )
    parser.set_defaults(func=_run_start)


def _register_list(
    subs: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
    common: argparse.ArgumentParser,
) -> None:
    parser = subs.add_parser(
        "list",
        parents=[common],
        help="List locally-open worlds.",
    )
    parser.set_defaults(func=_run_list)


def _register_focus(
    subs: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
    common: argparse.ArgumentParser,
) -> None:
    parser = subs.add_parser(
        "focus",
        parents=[common],
        help="Focus a locally-open world by handle.",
    )
    parser.add_argument("handle", type=int, help="World handle to focus.")
    parser.set_defaults(func=_run_focus)


def _register_leave(
    subs: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
    common: argparse.ArgumentParser,
) -> None:
    parser = subs.add_parser(
        "leave",
        parents=[common],
        help="Leave a locally-open world by handle.",
    )
    parser.add_argument("handle", type=int, help="World handle to leave.")
    parser.set_defaults(func=_run_leave)


def _register_current(
    subs: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
    common: argparse.ArgumentParser,
) -> None:
    parser = subs.add_parser(
        "current",
        parents=[common],
        help="Show the currently focused world.",
    )
    parser.set_defaults(func=_run_current)


# ---------------------------------------------------------------------------
# Table rendering
# ---------------------------------------------------------------------------

_SESSION_HEADERS = (
    "name",
    "host",
    "users",
    "access",
    "session_id",
)
_RECORD_HEADERS = (
    "name",
    "owner",
    "tags",
    "record_id",
)
_THUMBNAIL_HEADER = "thumbnail_url"
_OPEN_HEADERS = (
    "name",
    "focused",
    "users",
    "access",
    "handle",
)


def _print_table(headers: tuple[str, ...], rows: list[tuple[str, ...]]) -> None:
    """Print a compact whitespace-aligned table to stdout."""
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    print(line.rstrip())
    for row in rows:
        line = "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row))
        print(line.rstrip())


def _cap_rows(
    rows: list[tuple[str, ...]], limit: int, show_all: bool
) -> list[tuple[str, ...]]:
    """Return the rows to print, emitting a STDERR footer when truncated."""
    total = len(rows)
    if show_all or total <= limit:
        return rows
    print(f"... showing {limit} of {total} (use --all)", file=sys.stderr)
    return rows[:limit]


def _print_listing(
    headers: tuple[str, ...],
    rows: list[tuple[str, ...]],
    wide_cells: list[str],
    *,
    wide: bool,
    limit: int,
    show_all: bool,
) -> None:
    """Render a session / record listing, optionally appending the
    ``thumbnail_url`` column, and capping rows with a truncation footer.

    ``rows`` are the compact cells per row; ``wide_cells`` are the matching
    ``thumbnail_url`` values appended only when ``wide`` is set.
    """
    if wide:
        headers += (_THUMBNAIL_HEADER,)
        rows = [row + (cell,) for row, cell in zip(rows, wide_cells)]
    _print_table(headers, _cap_rows(rows, limit, show_all))


def _print_sessions(
    sessions: tuple[WorldSession, ...], *, wide: bool, limit: int, show_all: bool
) -> None:
    rows = [
        (
            s.name,
            s.host_username,
            f"{s.active_users}/{s.maximum_users}",
            s.access_level,
            s.session_id,
        )
        for s in sessions
    ]
    wide_cells = [s.thumbnail_url for s in sessions]
    _print_listing(
        _SESSION_HEADERS, rows, wide_cells, wide=wide, limit=limit, show_all=show_all
    )


def _print_records(
    records: tuple[WorldRecord, ...], *, wide: bool, limit: int, show_all: bool
) -> None:
    rows = [
        (
            r.name,
            r.owner_id,
            ",".join(r.tags),
            r.record_id,
        )
        for r in records
    ]
    wide_cells = [r.thumbnail_url for r in records]
    _print_listing(
        _RECORD_HEADERS, rows, wide_cells, wide=wide, limit=limit, show_all=show_all
    )


def _print_open_worlds(worlds: list[OpenWorld]) -> None:
    rows = [
        (
            w.name,
            "yes" if w.focused else "no",
            str(w.user_count),
            w.access_level,
            str(w.handle),
        )
        for w in worlds
    ]
    _print_table(_OPEN_HEADERS, rows)


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

_SESSION_FILTER_BY_NAME = {
    "all": "ALL",
    "friends": "FRIENDS",
    "headless": "HEADLESS",
}
_RECORD_SOURCE_BY_NAME = {
    "public": "PUBLIC",
    "featured": "FEATURED",
    "own": "OWN",
    "group": "GROUP",
}
_RECORD_SORT_BY_NAME = {
    "creation": "CREATION_DATE",
    "updated": "LAST_UPDATE",
    "published": "FIRST_PUBLISH",
    "visits": "TOTAL_VISITS",
    "name": "NAME",
    "random": "RANDOM",
}


async def _run_sessions(args: argparse.Namespace) -> int:
    from resoio.world import SessionFilter, WorldClient

    filter_value = SessionFilter[_SESSION_FILTER_BY_NAME[args.filter]]
    async with WorldClient(args.socket) as client:
        page = await client.list_sessions(
            search=args.search,
            filter=filter_value,
            min_active_users=args.min_users,
            page=args.page,
            page_size=args.page_size,
        )
    _print_sessions(
        page.sessions, wide=args.wide, limit=args.limit, show_all=args.show_all
    )
    return 0


async def _run_records(args: argparse.Namespace) -> int:
    from resoio.world import (
        RecordSort,
        RecordSortDirection,
        RecordSource,
        WorldClient,
    )

    source = RecordSource[_RECORD_SOURCE_BY_NAME[args.source]]
    sort = RecordSort[_RECORD_SORT_BY_NAME[args.sort]]
    direction = (
        RecordSortDirection.ASCENDING if args.asc else RecordSortDirection.DESCENDING
    )
    async with WorldClient(args.socket) as client:
        page = await client.list_records(
            source=source,
            required_tags=tuple(args.tags) if args.tags else (),
            owner_id=args.owner,
            offset=args.offset,
            count=args.count,
            sort=sort,
            sort_direction=direction,
        )
    _print_records(
        page.records, wide=args.wide, limit=args.limit, show_all=args.show_all
    )
    return 0


async def _run_thumbnail(args: argparse.Namespace) -> int:
    from resoio.world import WorldClient

    async with WorldClient(args.socket) as client:
        thumb = await client.fetch_thumbnail(args.uri)
    if args.output is None:
        sys.stdout.buffer.write(thumb.data)
        sys.stdout.buffer.flush()
        return 0
    with open(args.output, "wb") as fp:
        fp.write(thumb.data)
    print(
        f"saved {len(thumb.data)} bytes ({thumb.content_type}) -> {args.output}",
        file=sys.stderr,
    )
    return 0


async def _run_join(args: argparse.Namespace) -> int:
    from resoio.world import WorldClient

    async with WorldClient(args.socket) as client:
        world = await client.join(
            session_id=args.session_id or "",
            url=args.url or "",
            focus=not args.no_focus,
        )
    _print_open_worlds([world])
    return 0


async def _run_start(args: argparse.Namespace) -> int:
    from resoio.world import WorldClient

    async with WorldClient(args.socket) as client:
        world = await client.start_world(
            record_id=args.record_id,
            owner_id=args.owner_id,
            focus=not args.no_focus,
        )
    _print_open_worlds([world])
    return 0


async def _run_list(args: argparse.Namespace) -> int:
    from resoio.world import WorldClient

    async with WorldClient(args.socket) as client:
        worlds = await client.list_open_worlds()
    _print_open_worlds(worlds)
    return 0


async def _run_focus(args: argparse.Namespace) -> int:
    from resoio.world import WorldClient

    async with WorldClient(args.socket) as client:
        world = await client.focus(args.handle)
    _print_open_worlds([world])
    return 0


async def _run_leave(args: argparse.Namespace) -> int:
    from resoio.world import WorldClient

    async with WorldClient(args.socket) as client:
        await client.leave(args.handle)
    return 0


async def _run_current(args: argparse.Namespace) -> int:
    from resoio.world import WorldClient

    async with WorldClient(args.socket) as client:
        world = await client.get_current()
    if world is None:
        print("no focused world (userspace)", file=sys.stderr)
        return 0
    _print_open_worlds([world])
    return 0
