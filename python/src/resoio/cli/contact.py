"""``resoio contact <subcommand>``: browse / manage Resonite contacts.

Nested subcommands mirror ``resoio world``: a ``contact`` parent parser
holds the leaves (``list`` / ``get`` / ``search`` / ``add`` / ``accept``
/ ``remove``), each with the shared ``-s/--socket`` parent re-attached
(argparse does not inherit it) and its own ``_run_*`` handler set via
``set_defaults(func=...)``. The heavy ``from resoio.contact import ...``
is deferred into each handler so ``resoio --help`` stays fast.
"""

from __future__ import annotations

import argparse
import sys
from typing import TYPE_CHECKING

from resoio.cli import output

if TYPE_CHECKING:
    from resoio.contact import ContactInfo, UserSearchResult


_CONTACT_FILTER_CHOICES = ("all", "accepted", "requests")
_CONTACT_FILTER_BY_NAME = {
    "all": "ALL",
    "accepted": "ACCEPTED",
    "requests": "REQUESTS",
}


def register(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
    common: argparse.ArgumentParser,
) -> None:
    """Register the ``contact`` subparser with its nested subcommands."""
    parser = subparsers.add_parser(
        "contact",
        parents=[common],
        help="Browse and manage Resonite contacts (friends).",
        description=(
            "Drive the Resonite IO Contact service. 'list' shows existing "
            "contacts with presence; 'get' fetches one by user id; 'search' "
            "queries the cloud for users to add; 'add' / 'accept' / 'remove' "
            "mutate the contact list."
        ),
    )
    contact_subs = parser.add_subparsers(dest="contact_command", required=True)

    fmt = output.build_format_parent()
    _register_list(contact_subs, common, fmt)
    _register_get(contact_subs, common, fmt)
    _register_search(contact_subs, common, fmt)
    _register_add(contact_subs, common, fmt)
    _register_accept(contact_subs, common, fmt)
    _register_remove(contact_subs, common, fmt)


def _register_list(
    subs: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
    common: argparse.ArgumentParser,
    fmt: argparse.ArgumentParser,
) -> None:
    parser = subs.add_parser(
        "list",
        parents=[common, fmt],
        help="List contacts with presence.",
    )
    parser.add_argument("--search", default="", help="Username substring filter.")
    parser.add_argument(
        "--filter",
        choices=_CONTACT_FILTER_CHOICES,
        default="all",
        help="Contact filter (default: all).",
    )
    parser.set_defaults(func=_run_list)


def _register_get(
    subs: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
    common: argparse.ArgumentParser,
    fmt: argparse.ArgumentParser,
) -> None:
    parser = subs.add_parser(
        "get",
        parents=[common, fmt],
        help="Fetch a single contact by user id.",
    )
    parser.add_argument("user_id", help="Contact user id to fetch.")
    parser.set_defaults(func=_run_get)


def _register_search(
    subs: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
    common: argparse.ArgumentParser,
    fmt: argparse.ArgumentParser,
) -> None:
    parser = subs.add_parser(
        "search",
        parents=[common, fmt],
        help="Search the cloud for users to add.",
    )
    parser.add_argument("query", help="Username query.")
    parser.add_argument(
        "--exact",
        action="store_true",
        dest="exact_match",
        help="Match the username exactly (default: substring).",
    )
    parser.set_defaults(func=_run_search)


def _register_add(
    subs: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
    common: argparse.ArgumentParser,
    fmt: argparse.ArgumentParser,
) -> None:
    parser = subs.add_parser(
        "add",
        parents=[common, fmt],
        help="Add a user as a contact.",
    )
    parser.add_argument("user_id", help="User id to add.")
    parser.add_argument(
        "--username",
        default="",
        help="Username (resolved mod-side if omitted).",
    )
    parser.set_defaults(func=_run_add)


def _register_accept(
    subs: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
    common: argparse.ArgumentParser,
    fmt: argparse.ArgumentParser,
) -> None:
    parser = subs.add_parser(
        "accept",
        parents=[common, fmt],
        help="Accept an incoming contact request.",
    )
    parser.add_argument("user_id", help="User id of the request to accept.")
    parser.set_defaults(func=_run_accept)


def _register_remove(
    subs: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
    common: argparse.ArgumentParser,
    fmt: argparse.ArgumentParser,
) -> None:
    parser = subs.add_parser(
        "remove",
        parents=[common, fmt],
        help="Remove a contact / reject a request.",
    )
    parser.add_argument("user_id", help="User id to remove.")
    parser.set_defaults(func=_run_remove)


# ---------------------------------------------------------------------------
# Table rendering
# ---------------------------------------------------------------------------

_CONTACT_HEADERS = (
    "username",
    "user_id",
    "status",
    "online",
    "session",
)
_SEARCH_HEADERS = (
    "username",
    "user_id",
    "verified",
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


def _contact_row(contact: ContactInfo) -> tuple[str, ...]:
    return (
        contact.username,
        contact.user_id,
        contact.status.name,
        contact.online_status.name,
        contact.current_session_name,
    )


def _print_contacts(contacts: list[ContactInfo]) -> None:
    _print_table(_CONTACT_HEADERS, [_contact_row(c) for c in contacts])


def _print_search_results(results: list[UserSearchResult]) -> None:
    rows = [(r.username, r.user_id, "yes" if r.is_verified else "no") for r in results]
    _print_table(_SEARCH_HEADERS, rows)


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


async def _run_list(args: argparse.Namespace) -> int:
    from resoio.contact import ContactClient, ContactFilter

    filter_value = ContactFilter[_CONTACT_FILTER_BY_NAME[args.filter]]
    async with ContactClient(args.socket) as client:
        resp = await client.list_contacts(search=args.search, filter=filter_value)
    if output.is_structured(args.format):
        output.emit(resp.contacts, args.format)
    else:
        _print_contacts(resp.contacts)
    return 0


async def _run_get(args: argparse.Namespace) -> int:
    from resoio.contact import ContactClient

    async with ContactClient(args.socket) as client:
        resp = await client.get_contact(args.user_id)
    if output.is_structured(args.format):
        output.emit(resp.contact if resp.found else None, args.format)
        return 0
    if not resp.found or resp.contact is None:
        print("no such contact", file=sys.stderr)
        return 0
    _print_contacts([resp.contact])
    return 0


async def _run_search(args: argparse.Namespace) -> int:
    from resoio.contact import ContactClient

    async with ContactClient(args.socket) as client:
        resp = await client.search_users(args.query, exact_match=args.exact_match)
    if output.is_structured(args.format):
        output.emit(resp.results, args.format)
    else:
        _print_search_results(resp.results)
    return 0


async def _run_add(args: argparse.Namespace) -> int:
    from resoio.contact import ContactClient

    async with ContactClient(args.socket) as client:
        resp = await client.add_contact(args.user_id, username=args.username)
    _emit_contact(resp.contact, args.format)
    return 0


async def _run_accept(args: argparse.Namespace) -> int:
    from resoio.contact import ContactClient

    async with ContactClient(args.socket) as client:
        resp = await client.accept_request(args.user_id)
    _emit_contact(resp.contact, args.format)
    return 0


async def _run_remove(args: argparse.Namespace) -> int:
    from resoio.contact import ContactClient

    async with ContactClient(args.socket) as client:
        await client.remove_contact(args.user_id)
    if output.is_structured(args.format):
        output.emit({"user_id": args.user_id, "removed": True}, args.format)
    return 0


def _emit_contact(contact: ContactInfo | None, fmt: str) -> None:
    """Emit a single contact as json or the compact table, per ``fmt``."""
    if output.is_structured(fmt):
        output.emit(contact, fmt)
    elif contact is not None:
        _print_contacts([contact])
