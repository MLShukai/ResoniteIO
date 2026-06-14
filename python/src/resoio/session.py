"""Client for the Resonite IO ``Session`` modality (session / world admin).

Unary RPCs covering the in-game Session dialog: reading and patching
session settings, listing and moderating connected users (kick / ban /
silence / respawn / role), and browsing the permission roles.

The wire enums carry an ``UNSPECIFIED = 0`` slot that the public enums
omit. For :class:`SessionAccessLevel` that slot means "leave unchanged"
on :meth:`SessionClient.apply_settings`, so it is intentionally not a
public member: pass ``access_level=None`` to leave it unchanged, or a
concrete :class:`SessionAccessLevel` to set it.
"""

from __future__ import annotations

import enum
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import override

from grpclib.client import Channel

from resoio._client import _BaseClient
from resoio._generated.resonite_io.v1 import (
    BanUserRequest,
    GetSettingsRequest,
    GetUserRoleOverridesRequest,
    KickKind as _PbKickKind,
    KickUserRequest,
    ListRolesRequest,
    ListRolesResponse as _PbListRolesResponse,
    ListUsersRequest,
    RespawnUserRequest,
    SessionAccessLevel as _PbSessionAccessLevel,
    SessionRole as _PbSessionRole,
    SessionSettings as _PbSessionSettings,
    SessionSettingsPatch,
    SessionStub,
    SessionUser as _PbSessionUser,
    SetUserRoleRequest,
    SilenceUserRequest,
    UserRoleOverride as _PbUserRoleOverride,
    UserTarget,
)

__all__ = [
    "KickKind",
    "SessionAccessLevel",
    "SessionClient",
    "SessionRole",
    "SessionRoles",
    "SessionSettings",
    "SessionUser",
    "UserRoleOverride",
]

_logger = logging.getLogger("resoio.session")


class SessionAccessLevel(enum.Enum):
    """Session access level (mirrors ``SkyFrost.Base.SessionAccessLevel``).

    The wire ``UNSPECIFIED`` sentinel ("leave unchanged" on
    :meth:`SessionClient.apply_settings`) is deliberately omitted; use
    ``access_level=None`` for that.
    """

    PRIVATE = "private"
    LAN = "lan"
    CONTACTS = "contacts"
    CONTACTS_PLUS = "contacts_plus"
    REGISTERED_USERS = "registered_users"
    ANYONE = "anyone"


class KickKind(enum.Enum):
    """Kick variant (mirrors the engine ``KickRequestState``)."""

    KICK = "kick"
    KICK_AND_REVOKE = "kick_and_revoke"


@dataclass(frozen=True, slots=True)
class SessionSettings:
    """Snapshot of the current session settings (Settings tab).

    ``session_id`` / ``is_host`` are read-only metadata; the rest mirror
    the engine ``WorldConfiguration``.
    """

    world_name: str
    world_description: str
    max_users: int
    access_level: SessionAccessLevel
    hide_from_listing: bool
    mobile_friendly: bool
    away_kick_enabled: bool
    away_kick_minutes: float
    auto_save_enabled: bool
    auto_save_interval_minutes: float
    auto_cleanup_enabled: bool
    auto_cleanup_interval_seconds: float
    tags: tuple[str, ...]
    session_id: str
    is_host: bool


@dataclass(frozen=True, slots=True)
class SessionUser:
    """One connected user (Users tab)."""

    user_id: str
    user_name: str
    is_host: bool
    is_local_user: bool
    is_present_in_world: bool
    is_silenced: bool
    local_volume: float
    role_name: str
    platform: str
    head_device: str


@dataclass(frozen=True, slots=True)
class SessionRole:
    """One permission role (Permissions tab)."""

    role_name: str
    role_description: str
    is_highest: bool
    is_lowest: bool


@dataclass(frozen=True, slots=True)
class SessionRoles:
    """The session's permission roles plus the default-role assignments."""

    roles: tuple[SessionRole, ...]
    default_anonymous_role: str
    default_visitor_role: str
    default_contact_role: str
    default_host_role: str
    default_owner_role: str


@dataclass(frozen=True, slots=True)
class UserRoleOverride:
    """One ``DefaultUserPermissions`` entry (user id -> role name)."""

    user_id: str
    role_name: str


# ---------------------------------------------------------------------------
# Public <-> wire enum mapping
#
# The wire enums offset the public ones by an ``UNSPECIFIED = 0`` slot, so
# they are mapped by meaning (name), not numeric value.
# ---------------------------------------------------------------------------

_ACCESS_LEVEL_TO_WIRE: dict[SessionAccessLevel, _PbSessionAccessLevel] = {
    SessionAccessLevel.PRIVATE: _PbSessionAccessLevel.PRIVATE,
    SessionAccessLevel.LAN: _PbSessionAccessLevel.LAN,
    SessionAccessLevel.CONTACTS: _PbSessionAccessLevel.CONTACTS,
    SessionAccessLevel.CONTACTS_PLUS: _PbSessionAccessLevel.CONTACTS_PLUS,
    SessionAccessLevel.REGISTERED_USERS: _PbSessionAccessLevel.REGISTERED_USERS,
    SessionAccessLevel.ANYONE: _PbSessionAccessLevel.ANYONE,
}

_ACCESS_LEVEL_FROM_WIRE: dict[_PbSessionAccessLevel, SessionAccessLevel] = {
    wire: public for public, wire in _ACCESS_LEVEL_TO_WIRE.items()
}

_KICK_KIND_TO_WIRE: dict[KickKind, _PbKickKind] = {
    KickKind.KICK: _PbKickKind.KICK,
    KickKind.KICK_AND_REVOKE: _PbKickKind.KICK_AND_REVOKE,
}


def _access_level_from_wire(wire: _PbSessionAccessLevel) -> SessionAccessLevel:
    """Map a wire access level to its public value.

    The engine always returns a concrete (non-UNSPECIFIED) level for
    :meth:`SessionClient.get_settings`. If an UNSPECIFIED somehow arrives it
    has no public counterpart, so raise rather than silently coercing it to
    an arbitrary level.
    """
    try:
        return _ACCESS_LEVEL_FROM_WIRE[wire]
    except KeyError as exc:
        raise RuntimeError(
            f"Session returned an unmappable access level: {wire!r}."
        ) from exc


def _target(user_id: str, user_name: str, local: bool) -> UserTarget:
    """Build a :class:`UserTarget` from the standard targeting kwargs."""
    return UserTarget(user_id=user_id, user_name=user_name, local=local)


def _settings_from_proto(pb: _PbSessionSettings) -> SessionSettings:
    return SessionSettings(
        world_name=pb.world_name,
        world_description=pb.world_description,
        max_users=pb.max_users,
        access_level=_access_level_from_wire(pb.access_level),
        hide_from_listing=pb.hide_from_listing,
        mobile_friendly=pb.mobile_friendly,
        away_kick_enabled=pb.away_kick_enabled,
        away_kick_minutes=pb.away_kick_minutes,
        auto_save_enabled=pb.auto_save_enabled,
        auto_save_interval_minutes=pb.auto_save_interval_minutes,
        auto_cleanup_enabled=pb.auto_cleanup_enabled,
        auto_cleanup_interval_seconds=pb.auto_cleanup_interval_seconds,
        tags=tuple(pb.tags),
        session_id=pb.session_id,
        is_host=pb.is_host,
    )


def _user_from_proto(pb: _PbSessionUser) -> SessionUser:
    return SessionUser(
        user_id=pb.user_id,
        user_name=pb.user_name,
        is_host=pb.is_host,
        is_local_user=pb.is_local_user,
        is_present_in_world=pb.is_present_in_world,
        is_silenced=pb.is_silenced,
        local_volume=pb.local_volume,
        role_name=pb.role_name,
        platform=pb.platform,
        head_device=pb.head_device,
    )


def _role_from_proto(pb: _PbSessionRole) -> SessionRole:
    return SessionRole(
        role_name=pb.role_name,
        role_description=pb.role_description,
        is_highest=pb.is_highest,
        is_lowest=pb.is_lowest,
    )


def _roles_from_proto(pb: _PbListRolesResponse) -> SessionRoles:
    return SessionRoles(
        roles=tuple(_role_from_proto(r) for r in pb.roles),
        default_anonymous_role=pb.default_anonymous_role,
        default_visitor_role=pb.default_visitor_role,
        default_contact_role=pb.default_contact_role,
        default_host_role=pb.default_host_role,
        default_owner_role=pb.default_owner_role,
    )


def _override_from_proto(pb: _PbUserRoleOverride) -> UserRoleOverride:
    return UserRoleOverride(user_id=pb.user_id, role_name=pb.role_name)


def _require_user(user: _PbSessionUser | None) -> SessionUser:
    """Unwrap the ``user`` field of a moderation response.

    The ``silence`` / ``set_user_role`` RPCs return the updated user
    snapshot; a missing user is a protocol violation, not a normal signal.
    """
    if user is None:
        raise RuntimeError("Session response did not include a SessionUser.")
    return _user_from_proto(user)


class SessionClient(_BaseClient[SessionStub]):
    """Async client for the Resonite IO ``Session`` service over a UDS.

    Use as an async context manager so the gRPC channel closes
    deterministically.

    Targeting (``kick`` / ``ban`` / ``silence`` / ``respawn`` / ``role``):
    pass ``local=True`` to target yourself, otherwise ``user_id`` is tried
    first and ``user_name`` is the fallback. ``user_name`` resolution
    fails if several connected users share the name -- prefer ``user_id``
    for guests. Moderation and settings writes are host-gated: calling them
    without host permission raises gRPC ``PermissionDenied``.
    """

    _logger = _logger
    _log_label = "Session"

    @override
    def _make_stub(self, channel: Channel) -> SessionStub:
        return SessionStub(channel)

    async def get_settings(self) -> SessionSettings:
        """Return the current session settings snapshot."""
        stub = self._require_stub()
        return _settings_from_proto(await stub.get_settings(GetSettingsRequest()))

    async def apply_settings(
        self,
        *,
        world_name: str | None = None,
        world_description: str | None = None,
        max_users: int | None = None,
        access_level: SessionAccessLevel | None = None,
        hide_from_listing: bool | None = None,
        mobile_friendly: bool | None = None,
        away_kick_enabled: bool | None = None,
        away_kick_minutes: float | None = None,
        auto_save_enabled: bool | None = None,
        auto_save_interval_minutes: float | None = None,
        auto_cleanup_enabled: bool | None = None,
        auto_cleanup_interval_seconds: float | None = None,
        tags: Sequence[str] | None = None,
    ) -> None:
        """Patch the session settings; ``None`` kwargs are left unchanged.

        Scalar / bool / string fields ride on the proto3 ``optional``
        presence flag, so a ``None`` kwarg is simply not put on the wire.
        ``access_level=None`` sends the ``UNSPECIFIED`` sentinel ("leave
        unchanged"); a concrete value sets it. ``tags`` is replace-all: pass
        a sequence to replace the tag set (empty clears it) or ``None`` to
        leave the tags untouched.

        Returns ``None`` by contract: the engine applies settings on its own
        thread, so a post-apply snapshot is not reliable in the same RPC.
        Call :meth:`get_settings` afterwards if you need the new state.
        """
        stub = self._require_stub()
        wire_access = (
            _PbSessionAccessLevel.UNSPECIFIED
            if access_level is None
            else _ACCESS_LEVEL_TO_WIRE[access_level]
        )
        patch = SessionSettingsPatch(
            world_name=world_name,
            world_description=world_description,
            max_users=max_users,
            access_level=wire_access,
            hide_from_listing=hide_from_listing,
            mobile_friendly=mobile_friendly,
            away_kick_enabled=away_kick_enabled,
            away_kick_minutes=away_kick_minutes,
            auto_save_enabled=auto_save_enabled,
            auto_save_interval_minutes=auto_save_interval_minutes,
            auto_cleanup_enabled=auto_cleanup_enabled,
            auto_cleanup_interval_seconds=auto_cleanup_interval_seconds,
            replace_tags=tags is not None,
            tags=list(tags) if tags is not None else [],
        )
        await stub.apply_settings(patch)

    async def list_users(self) -> tuple[SessionUser, ...]:
        """List the users connected to the current session."""
        stub = self._require_stub()
        response = await stub.list_users(ListUsersRequest())
        return tuple(_user_from_proto(u) for u in response.users)

    async def kick_user(
        self,
        *,
        user_id: str = "",
        user_name: str = "",
        local: bool = False,
        kind: KickKind = KickKind.KICK_AND_REVOKE,
    ) -> None:
        """Kick a user from the session."""
        stub = self._require_stub()
        request = KickUserRequest(
            target=_target(user_id, user_name, local),
            kind=_KICK_KIND_TO_WIRE[kind],
        )
        await stub.kick_user(request)

    async def ban_user(
        self,
        *,
        user_id: str = "",
        user_name: str = "",
        local: bool = False,
    ) -> None:
        """Ban a user from the session."""
        stub = self._require_stub()
        request = BanUserRequest(target=_target(user_id, user_name, local))
        await stub.ban_user(request)

    async def silence_user(
        self,
        *,
        user_id: str = "",
        user_name: str = "",
        local: bool = False,
        silenced: bool = True,
    ) -> SessionUser:
        """Silence (or unsilence) a user; returns the updated snapshot."""
        stub = self._require_stub()
        request = SilenceUserRequest(
            target=_target(user_id, user_name, local),
            silenced=silenced,
        )
        response = await stub.silence_user(request)
        return _require_user(response.user)

    async def respawn_user(
        self,
        *,
        user_id: str = "",
        user_name: str = "",
        local: bool = False,
    ) -> None:
        """Respawn a user.

        With no target the engine respawns the local user.
        """
        stub = self._require_stub()
        request = RespawnUserRequest(target=_target(user_id, user_name, local))
        await stub.respawn_user(request)

    async def respawn_self(self) -> None:
        """Respawn the local user (convenience for
        ``respawn_user(local=True)``)."""
        await self.respawn_user(local=True)

    async def set_user_role(
        self,
        role_name: str,
        *,
        user_id: str = "",
        user_name: str = "",
        local: bool = False,
    ) -> SessionUser:
        """Assign ``role_name`` to a user; returns the updated snapshot."""
        stub = self._require_stub()
        request = SetUserRoleRequest(
            target=_target(user_id, user_name, local),
            role_name=role_name,
        )
        response = await stub.set_user_role(request)
        return _require_user(response.user)

    async def list_roles(self) -> SessionRoles:
        """List the session's permission roles and default-role assignments."""
        stub = self._require_stub()
        return _roles_from_proto(await stub.list_roles(ListRolesRequest()))

    async def get_user_role_overrides(self) -> tuple[UserRoleOverride, ...]:
        """List the per-user default-role overrides
        (``DefaultUserPermissions``)."""
        stub = self._require_stub()
        response = await stub.get_user_role_overrides(GetUserRoleOverridesRequest())
        return tuple(_override_from_proto(o) for o in response.overrides)
