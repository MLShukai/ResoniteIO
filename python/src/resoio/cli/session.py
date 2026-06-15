"""``resoio session <group> <action>``: read / patch session settings and
moderate the connected users.

Nested subcommands mirror ``resoio world``: a ``session`` parent parser
holds the group parsers (``settings`` / ``users`` / ``user`` / ``roles``
/ ``overrides``), each of which holds its action leaves. Every leaf
re-attaches the shared ``-s/--socket`` parent (argparse does not inherit
it) and sets its own ``_run_*`` handler via ``set_defaults(func=...)``.
The heavy ``from resoio.session import ...`` is deferred into each handler
so ``resoio --help`` stays fast.
"""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from resoio.session import (
        SessionRoles,
        SessionSettings,
        SessionUser,
    )

_ACCESS_LEVEL_CHOICES = (
    "private",
    "lan",
    "contacts",
    "contacts-plus",
    "registered",
    "anyone",
)
# CLI choice (kebab) -> public SessionAccessLevel member name.
_ACCESS_LEVEL_BY_NAME = {
    "private": "PRIVATE",
    "lan": "LAN",
    "contacts": "CONTACTS",
    "contacts-plus": "CONTACTS_PLUS",
    "registered": "REGISTERED_USERS",
    "anyone": "ANYONE",
}

_KICK_KIND_CHOICES = ("kick", "kick-and-revoke")
_KICK_KIND_BY_NAME = {
    "kick": "KICK",
    "kick-and-revoke": "KICK_AND_REVOKE",
}


def register(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
    common: argparse.ArgumentParser,
) -> None:
    """Register the ``session`` subparser with its nested group subcommands."""
    parser = subparsers.add_parser(
        "session",
        parents=[common],
        help="Read/patch session settings and moderate connected users.",
        description=(
            "Drive the Resonite IO Session service (the in-game Session "
            "dialog). Groups: 'settings' reads/patches the session config; "
            "'users' lists connected users; 'user' moderates one user "
            "(kick/ban/silence/respawn/role); 'roles' and 'overrides' list "
            "the permission roles and per-user role overrides."
        ),
    )
    session_subs = parser.add_subparsers(dest="session_command", required=True)

    _register_settings(session_subs, common)
    _register_users(session_subs, common)
    _register_user(session_subs, common)
    _register_roles(session_subs, common)
    _register_overrides(session_subs, common)


# ---------------------------------------------------------------------------
# settings get/set
# ---------------------------------------------------------------------------


def _register_settings(
    subs: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
    common: argparse.ArgumentParser,
) -> None:
    parser = subs.add_parser(
        "settings",
        parents=[common],
        help="Read or patch the session settings.",
    )
    settings_subs = parser.add_subparsers(dest="settings_command", required=True)

    get_parser = settings_subs.add_parser(
        "get",
        parents=[common],
        help="Print the current session settings.",
    )
    get_parser.set_defaults(func=_run_settings_get)

    set_parser = settings_subs.add_parser(
        "set",
        parents=[common],
        help="Patch the session settings (omitted flags are left unchanged).",
        description=(
            "Patch the session settings. Omitted flags are left unchanged. "
            "At least one flag is required. --tags replaces the whole tag "
            "set (empty value clears it)."
        ),
    )
    set_parser.add_argument(
        "--world-name", dest="world_name", default=None, help="Set the world name."
    )
    set_parser.add_argument(
        "--description",
        dest="world_description",
        default=None,
        help="Set the world description.",
    )
    set_parser.add_argument(
        "--max-users",
        dest="max_users",
        type=int,
        default=None,
        help="Set the maximum number of users.",
    )
    set_parser.add_argument(
        "--access-level",
        dest="access_level",
        choices=_ACCESS_LEVEL_CHOICES,
        default=None,
        help="Set the session access level.",
    )
    set_parser.add_argument(
        "--hide-from-listing",
        dest="hide_from_listing",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Hide the session from the public listing.",
    )
    set_parser.add_argument(
        "--mobile-friendly",
        dest="mobile_friendly",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Mark the session as mobile-friendly.",
    )
    set_parser.add_argument(
        "--away-kick-enabled",
        dest="away_kick_enabled",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Enable kicking away users.",
    )
    set_parser.add_argument(
        "--away-kick-minutes",
        dest="away_kick_minutes",
        type=float,
        default=None,
        help="Minutes before an away user is kicked.",
    )
    set_parser.add_argument(
        "--auto-save-enabled",
        dest="auto_save_enabled",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Enable periodic auto-save.",
    )
    set_parser.add_argument(
        "--auto-save-interval-minutes",
        dest="auto_save_interval_minutes",
        type=float,
        default=None,
        help="Auto-save interval in minutes.",
    )
    set_parser.add_argument(
        "--auto-cleanup-enabled",
        dest="auto_cleanup_enabled",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Enable periodic auto-cleanup.",
    )
    set_parser.add_argument(
        "--auto-cleanup-interval-seconds",
        dest="auto_cleanup_interval_seconds",
        type=float,
        default=None,
        help="Auto-cleanup interval in seconds.",
    )
    set_parser.add_argument(
        "--tags",
        dest="tags",
        default=None,
        help="Comma-separated tags to replace the whole set (empty clears it).",
    )
    set_parser.add_argument(
        "--resonite-link",
        dest="resonite_link_enabled",
        action="store_const",
        const=True,
        default=None,
        help=(
            "Enable the engine ResoniteLink endpoint (host only; idempotent). "
            "There is no disable flag: the engine exposes no runtime-disable API."
        ),
    )
    set_parser.set_defaults(func=_run_settings_set, _parser=set_parser)


# ---------------------------------------------------------------------------
# users list
# ---------------------------------------------------------------------------


def _register_users(
    subs: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
    common: argparse.ArgumentParser,
) -> None:
    parser = subs.add_parser(
        "users",
        parents=[common],
        help="List the connected users.",
    )
    users_subs = parser.add_subparsers(dest="users_command", required=True)
    list_parser = users_subs.add_parser(
        "list",
        parents=[common],
        help="List the users connected to the session.",
    )
    list_parser.set_defaults(func=_run_users_list)


# ---------------------------------------------------------------------------
# user kick/ban/silence/respawn/role
# ---------------------------------------------------------------------------


def _add_target_args(parser: argparse.ArgumentParser, *, required: bool) -> None:
    """Attach the mutually exclusive ``--id`` / ``--name`` / ``--self``
    flags."""
    target = parser.add_mutually_exclusive_group(required=required)
    target.add_argument("--id", dest="user_id", default="", help="Target user id.")
    target.add_argument(
        "--name", dest="user_name", default="", help="Target user name."
    )
    target.add_argument(
        "--self",
        dest="local",
        action="store_true",
        help="Target the local user (self).",
    )


def _register_user(
    subs: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
    common: argparse.ArgumentParser,
) -> None:
    parser = subs.add_parser(
        "user",
        parents=[common],
        help="Moderate a single user (kick/ban/silence/respawn/role).",
    )
    user_subs = parser.add_subparsers(dest="user_command", required=True)

    kick_parser = user_subs.add_parser(
        "kick", parents=[common], help="Kick a user from the session."
    )
    _add_target_args(kick_parser, required=True)
    kick_parser.add_argument(
        "--kind",
        choices=_KICK_KIND_CHOICES,
        default="kick-and-revoke",
        help="Kick variant (default: kick-and-revoke).",
    )
    kick_parser.set_defaults(func=_run_user_kick)

    ban_parser = user_subs.add_parser(
        "ban", parents=[common], help="Ban a user from the session."
    )
    _add_target_args(ban_parser, required=True)
    ban_parser.set_defaults(func=_run_user_ban)

    silence_parser = user_subs.add_parser(
        "silence", parents=[common], help="Silence or unsilence a user."
    )
    _add_target_args(silence_parser, required=True)
    silence_parser.add_argument(
        "--on",
        dest="silenced",
        action="store_true",
        default=True,
        help="Silence the user (default).",
    )
    silence_parser.add_argument(
        "--off",
        dest="silenced",
        action="store_false",
        help="Unsilence the user.",
    )
    silence_parser.set_defaults(func=_run_user_silence)

    respawn_parser = user_subs.add_parser(
        "respawn",
        parents=[common],
        help="Respawn a user (defaults to self when no target is given).",
    )
    _add_target_args(respawn_parser, required=False)
    respawn_parser.set_defaults(func=_run_user_respawn)

    role_parser = user_subs.add_parser(
        "role", parents=[common], help="Assign a role to a user."
    )
    _add_target_args(role_parser, required=True)
    role_parser.add_argument("role_name", help="Role name to assign.")
    role_parser.set_defaults(func=_run_user_role)


# ---------------------------------------------------------------------------
# roles list / overrides list
# ---------------------------------------------------------------------------


def _register_roles(
    subs: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
    common: argparse.ArgumentParser,
) -> None:
    parser = subs.add_parser(
        "roles",
        parents=[common],
        help="List the session's permission roles.",
    )
    roles_subs = parser.add_subparsers(dest="roles_command", required=True)
    list_parser = roles_subs.add_parser(
        "list",
        parents=[common],
        help="List the permission roles and default-role assignments.",
    )
    list_parser.set_defaults(func=_run_roles_list)


def _register_overrides(
    subs: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
    common: argparse.ArgumentParser,
) -> None:
    parser = subs.add_parser(
        "overrides",
        parents=[common],
        help="List the per-user default-role overrides.",
    )
    overrides_subs = parser.add_subparsers(dest="overrides_command", required=True)
    list_parser = overrides_subs.add_parser(
        "list",
        parents=[common],
        help="List the per-user default-role overrides.",
    )
    list_parser.set_defaults(func=_run_overrides_list)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _format_settings(settings: SessionSettings) -> str:
    fields: list[tuple[str, str]] = [
        ("world_name", settings.world_name),
        ("world_description", settings.world_description),
        ("max_users", str(settings.max_users)),
        ("access_level", settings.access_level.value),
        ("hide_from_listing", str(settings.hide_from_listing)),
        ("mobile_friendly", str(settings.mobile_friendly)),
        ("away_kick_enabled", str(settings.away_kick_enabled)),
        ("away_kick_minutes", str(settings.away_kick_minutes)),
        ("auto_save_enabled", str(settings.auto_save_enabled)),
        ("auto_save_interval_minutes", str(settings.auto_save_interval_minutes)),
        ("auto_cleanup_enabled", str(settings.auto_cleanup_enabled)),
        (
            "auto_cleanup_interval_seconds",
            str(settings.auto_cleanup_interval_seconds),
        ),
        ("tags", ",".join(settings.tags)),
        ("session_id", settings.session_id),
        ("is_host", str(settings.is_host)),
        ("resonite_link_enabled", str(settings.resonite_link_enabled)),
        ("resonite_link_port", str(settings.resonite_link_port)),
    ]
    width = max(len(key) for key, _ in fields)
    return "\n".join(f"{key.ljust(width)}  {value}" for key, value in fields)


def _format_user(user: SessionUser) -> str:
    flags: list[str] = []
    if user.is_host:
        flags.append("host")
    if user.is_local_user:
        flags.append("self")
    if user.is_present_in_world:
        flags.append("present")
    if user.is_silenced:
        flags.append("silenced")
    flag_text = ",".join(flags) if flags else "-"
    return (
        f"{user.user_name}  id={user.user_id or '-'}  role={user.role_name or '-'}  "
        f"platform={user.platform or '-'}  head={user.head_device or '-'}  "
        f"vol={user.local_volume}  [{flag_text}]"
    )


def _format_roles(roles: SessionRoles) -> str:
    lines: list[str] = []
    for role in roles.roles:
        markers: list[str] = []
        if role.is_highest:
            markers.append("highest")
        if role.is_lowest:
            markers.append("lowest")
        marker_text = f" ({','.join(markers)})" if markers else ""
        desc = f" - {role.role_description}" if role.role_description else ""
        lines.append(f"{role.role_name}{marker_text}{desc}")
    lines.append("")
    lines.append(f"default_anonymous_role  {roles.default_anonymous_role or '-'}")
    lines.append(f"default_visitor_role    {roles.default_visitor_role or '-'}")
    lines.append(f"default_contact_role    {roles.default_contact_role or '-'}")
    lines.append(f"default_host_role       {roles.default_host_role or '-'}")
    lines.append(f"default_owner_role      {roles.default_owner_role or '-'}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


async def _run_settings_get(args: argparse.Namespace) -> int:
    from resoio.session import SessionClient

    async with SessionClient(args.socket) as client:
        settings = await client.get_settings()
    print(_format_settings(settings))
    return 0


async def _run_settings_set(args: argparse.Namespace) -> int:
    from resoio.session import SessionAccessLevel, SessionClient

    flag_values = (
        args.world_name,
        args.world_description,
        args.max_users,
        args.access_level,
        args.hide_from_listing,
        args.mobile_friendly,
        args.away_kick_enabled,
        args.away_kick_minutes,
        args.auto_save_enabled,
        args.auto_save_interval_minutes,
        args.auto_cleanup_enabled,
        args.auto_cleanup_interval_seconds,
        args.tags,
        args.resonite_link_enabled,
    )
    if all(value is None for value in flag_values):
        parser: argparse.ArgumentParser = args._parser
        parser.error("at least one setting flag is required")

    access_level = (
        None
        if args.access_level is None
        else SessionAccessLevel[_ACCESS_LEVEL_BY_NAME[args.access_level]]
    )
    tags = None if args.tags is None else _split_tags(args.tags)

    async with SessionClient(args.socket) as client:
        await client.apply_settings(
            world_name=args.world_name,
            world_description=args.world_description,
            max_users=args.max_users,
            access_level=access_level,
            hide_from_listing=args.hide_from_listing,
            mobile_friendly=args.mobile_friendly,
            away_kick_enabled=args.away_kick_enabled,
            away_kick_minutes=args.away_kick_minutes,
            auto_save_enabled=args.auto_save_enabled,
            auto_save_interval_minutes=args.auto_save_interval_minutes,
            auto_cleanup_enabled=args.auto_cleanup_enabled,
            auto_cleanup_interval_seconds=args.auto_cleanup_interval_seconds,
            tags=tags,
            resonite_link_enabled=args.resonite_link_enabled,
        )
        settings = await client.get_settings()
    print(_format_settings(settings))
    return 0


def _split_tags(raw: str) -> list[str]:
    """Split a comma-separated ``--tags`` value (empty string clears the
    set)."""
    return [tag for tag in (part.strip() for part in raw.split(",")) if tag]


async def _run_users_list(args: argparse.Namespace) -> int:
    from resoio.session import SessionClient

    async with SessionClient(args.socket) as client:
        users = await client.list_users()
    for user in users:
        print(_format_user(user))
    return 0


async def _run_user_kick(args: argparse.Namespace) -> int:
    from resoio.session import KickKind, SessionClient

    kind = KickKind[_KICK_KIND_BY_NAME[args.kind]]
    async with SessionClient(args.socket) as client:
        await client.kick_user(
            user_id=args.user_id,
            user_name=args.user_name,
            local=args.local,
            kind=kind,
        )
    return 0


async def _run_user_ban(args: argparse.Namespace) -> int:
    from resoio.session import SessionClient

    async with SessionClient(args.socket) as client:
        await client.ban_user(
            user_id=args.user_id,
            user_name=args.user_name,
            local=args.local,
        )
    return 0


async def _run_user_silence(args: argparse.Namespace) -> int:
    from resoio.session import SessionClient

    async with SessionClient(args.socket) as client:
        user = await client.silence_user(
            user_id=args.user_id,
            user_name=args.user_name,
            local=args.local,
            silenced=args.silenced,
        )
    print(_format_user(user))
    return 0


async def _run_user_respawn(args: argparse.Namespace) -> int:
    from resoio.session import SessionClient

    # No target flag -> respawn self (local=True).
    local = args.local or not (args.user_id or args.user_name)
    async with SessionClient(args.socket) as client:
        await client.respawn_user(
            user_id=args.user_id,
            user_name=args.user_name,
            local=local,
        )
    return 0


async def _run_user_role(args: argparse.Namespace) -> int:
    from resoio.session import SessionClient

    async with SessionClient(args.socket) as client:
        user = await client.set_user_role(
            args.role_name,
            user_id=args.user_id,
            user_name=args.user_name,
            local=args.local,
        )
    print(_format_user(user))
    return 0


async def _run_roles_list(args: argparse.Namespace) -> int:
    from resoio.session import SessionClient

    async with SessionClient(args.socket) as client:
        roles = await client.list_roles()
    print(_format_roles(roles))
    return 0


async def _run_overrides_list(args: argparse.Namespace) -> int:
    from resoio.session import SessionClient

    async with SessionClient(args.socket) as client:
        overrides = await client.get_user_role_overrides()
    for override in overrides:
        print(f"{override.user_id}  {override.role_name}")
    return 0
