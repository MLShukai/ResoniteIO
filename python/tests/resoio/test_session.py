"""Behaviour tests for :class:`resoio.session.SessionClient`.

These are spec tests for the Session modality (the in-game Session
dialog: Settings / Users / Permissions tabs). They follow the canonical
"grpclib end-to-end round-trip" harness from testing-strategy: a real
``grpclib.server.Server`` listens on a real Unix Domain Socket with an
in-process, self-owned :class:`SessionBase` fake, and the
``SessionClient`` connects over the real wire. No grpclib / asyncio /
betterproto internals are mocked — the only fake is the self-owned
servicer ABC.

The recurring proof in this file is *wire presence*: the
``SessionSettingsPatch`` carries scalar / bool / string fields on the
proto3 ``optional`` presence flag, so a ``None`` kwarg must not appear on
the wire (the fake observes ``None``) while an explicit ``False`` / ``0``
must (the fake observes the value). Because the patch crosses a real
socket, presence is verified against the *deserialized* message the
server received, not the object the client built.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

import pytest

from resoio._generated.resonite_io.v1 import (
    ApplySettingsResponse,
    BanUserRequest,
    BanUserResponse,
    GetSettingsRequest,
    GetUserRoleOverridesRequest,
    GetUserRoleOverridesResponse,
    KickKind as PbKickKind,
    KickUserRequest,
    KickUserResponse,
    ListRolesRequest,
    ListRolesResponse,
    ListUsersRequest,
    ListUsersResponse,
    RespawnUserRequest,
    RespawnUserResponse,
    SessionAccessLevel as PbSessionAccessLevel,
    SessionBase,
    SessionRole as PbSessionRole,
    SessionSettings as PbSessionSettings,
    SessionSettingsPatch,
    SessionUser as PbSessionUser,
    SetUserRoleRequest,
    SetUserRoleResponse,
    SilenceUserRequest,
    SilenceUserResponse,
)
from resoio.session import (
    KickKind,
    SessionAccessLevel,
    SessionClient,
    SessionRole,
    SessionRoles,
    SessionSettings,
    SessionUser,
    UserRoleOverride,
)

if TYPE_CHECKING:
    from grpclib._typing import IServable

UdsServer = Callable[["IServable"], Awaitable[str]]


# ---------------------------------------------------------------------------
# In-process fake (self-owned SessionBase ABC).
# ---------------------------------------------------------------------------


def _full_settings_pb() -> PbSessionSettings:
    """A SessionSettings snapshot with a distinct value in every field.

    Distinct values let the mapping test catch a field that is wired to
    the wrong source attribute (a copy/paste swap), which identical
    placeholder values would silently pass.
    """
    return PbSessionSettings(
        world_name="My World",
        world_description="a place",
        max_users=24,
        access_level=PbSessionAccessLevel.CONTACTS_PLUS,
        hide_from_listing=True,
        mobile_friendly=False,
        away_kick_enabled=True,
        away_kick_minutes=12.5,
        auto_save_enabled=True,
        auto_save_interval_minutes=7.0,
        auto_cleanup_enabled=False,
        auto_cleanup_interval_seconds=90.0,
        tags=["game", "social"],
        session_id="S-abc",
        is_host=True,
    )


class _FakeSession(SessionBase):
    """Records each request and serves configurable canned responses."""

    def __init__(
        self,
        *,
        settings: PbSessionSettings | None = None,
        users: list[PbSessionUser] | None = None,
        roles_response: ListRolesResponse | None = None,
        overrides_response: GetUserRoleOverridesResponse | None = None,
        silence_user: PbSessionUser | None = None,
        set_role_user: PbSessionUser | None = None,
    ) -> None:
        # NB: use explicit `is None` checks, never `x or default`. An
        # all-default protobuf message is *falsy*, so `settings or ...` would
        # silently replace a caller's "all zeros" snapshot (e.g. one with
        # access_level=UNSPECIFIED) with the default — masking the very case
        # under test.
        self._settings = settings if settings is not None else _full_settings_pb()
        self._users = users if users is not None else []
        self._roles_response = (
            roles_response if roles_response is not None else ListRolesResponse()
        )
        self._overrides_response = (
            overrides_response
            if overrides_response is not None
            else GetUserRoleOverridesResponse()
        )
        self._silence_user = (
            silence_user if silence_user is not None else PbSessionUser()
        )
        self._set_role_user = (
            set_role_user if set_role_user is not None else PbSessionUser()
        )

        self.last_patch: SessionSettingsPatch | None = None
        self.last_kick: KickUserRequest | None = None
        self.last_ban: BanUserRequest | None = None
        self.last_silence: SilenceUserRequest | None = None
        self.last_respawn: RespawnUserRequest | None = None
        self.last_set_role: SetUserRoleRequest | None = None

    async def get_settings(self, message: GetSettingsRequest) -> PbSessionSettings:
        return self._settings

    async def apply_settings(
        self, message: SessionSettingsPatch
    ) -> ApplySettingsResponse:
        self.last_patch = message
        return ApplySettingsResponse()

    async def list_users(self, message: ListUsersRequest) -> ListUsersResponse:
        return ListUsersResponse(users=self._users)

    async def kick_user(self, message: KickUserRequest) -> KickUserResponse:
        self.last_kick = message
        return KickUserResponse()

    async def ban_user(self, message: BanUserRequest) -> BanUserResponse:
        self.last_ban = message
        return BanUserResponse()

    async def silence_user(self, message: SilenceUserRequest) -> SilenceUserResponse:
        self.last_silence = message
        return SilenceUserResponse(user=self._silence_user)

    async def respawn_user(self, message: RespawnUserRequest) -> RespawnUserResponse:
        self.last_respawn = message
        return RespawnUserResponse()

    async def set_user_role(self, message: SetUserRoleRequest) -> SetUserRoleResponse:
        self.last_set_role = message
        return SetUserRoleResponse(user=self._set_role_user)

    async def list_roles(self, message: ListRolesRequest) -> ListRolesResponse:
        return self._roles_response

    async def get_user_role_overrides(
        self, message: GetUserRoleOverridesRequest
    ) -> GetUserRoleOverridesResponse:
        return self._overrides_response


# ===========================================================================
# get_settings: wire -> SessionSettings dataclass mapping.
# ===========================================================================


class TestGetSettings:
    async def test_maps_every_field_into_the_settings_dataclass(
        self, uds_server: UdsServer
    ):
        await uds_server(_FakeSession(settings=_full_settings_pb()))
        async with SessionClient() as client:
            settings = await client.get_settings()
        assert settings == SessionSettings(
            world_name="My World",
            world_description="a place",
            max_users=24,
            access_level=SessionAccessLevel.CONTACTS_PLUS,
            hide_from_listing=True,
            mobile_friendly=False,
            away_kick_enabled=True,
            away_kick_minutes=12.5,
            auto_save_enabled=True,
            auto_save_interval_minutes=7.0,
            auto_cleanup_enabled=False,
            auto_cleanup_interval_seconds=90.0,
            tags=("game", "social"),
            session_id="S-abc",
            is_host=True,
        )

    async def test_tags_are_decoded_as_a_tuple(self, uds_server: UdsServer):
        """``tags`` is exposed as an immutable tuple (the dataclass is frozen),
        not the mutable list that crosses the wire."""
        await uds_server(
            _FakeSession(
                settings=PbSessionSettings(
                    access_level=PbSessionAccessLevel.ANYONE,
                    tags=["a", "b", "c"],
                )
            )
        )
        async with SessionClient() as client:
            settings = await client.get_settings()
        assert settings.tags == ("a", "b", "c")
        assert isinstance(settings.tags, tuple)

    @pytest.mark.parametrize(
        ("wire", "public"),
        [
            (PbSessionAccessLevel.PRIVATE, SessionAccessLevel.PRIVATE),
            (PbSessionAccessLevel.LAN, SessionAccessLevel.LAN),
            (PbSessionAccessLevel.CONTACTS, SessionAccessLevel.CONTACTS),
            (
                PbSessionAccessLevel.CONTACTS_PLUS,
                SessionAccessLevel.CONTACTS_PLUS,
            ),
            (
                PbSessionAccessLevel.REGISTERED_USERS,
                SessionAccessLevel.REGISTERED_USERS,
            ),
            (PbSessionAccessLevel.ANYONE, SessionAccessLevel.ANYONE),
        ],
    )
    async def test_each_wire_access_level_maps_to_its_public_member(
        self,
        uds_server: UdsServer,
        wire: PbSessionAccessLevel,
        public: SessionAccessLevel,
    ):
        """The wire enum is offset from the public one by UNSPECIFIED=0, so it
        is mapped by meaning, not numeric value — pin every level."""
        await uds_server(_FakeSession(settings=PbSessionSettings(access_level=wire)))
        async with SessionClient() as client:
            settings = await client.get_settings()
        assert settings.access_level is public

    async def test_unspecified_access_level_is_rejected_not_coerced(
        self, uds_server: UdsServer
    ):
        """UNSPECIFIED has no public counterpart ("leave unchanged" is only an
        ApplySettings input).

        If it arrives on a GetSettings snapshot the client must raise
        rather than silently coerce it to an arbitrary level.
        """
        await uds_server(
            _FakeSession(
                settings=PbSessionSettings(
                    access_level=PbSessionAccessLevel.UNSPECIFIED
                )
            )
        )
        async with SessionClient() as client:
            with pytest.raises(RuntimeError, match="access level"):
                await client.get_settings()

    async def test_raises_when_not_connected(self):
        client = SessionClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.get_settings()


# ===========================================================================
# apply_settings: proto3 optional presence on the wire.
#
# The defining contract: a None kwarg must NOT be put on the wire (the
# server observes None on the deserialized patch), while an explicit
# False / 0 must (the server observes the value). Verified against the
# message the fake actually received over the real socket.
# ===========================================================================


class TestApplySettings:
    async def test_returns_none(self, uds_server: UdsServer):
        """By contract apply returns None — the engine applies on its own
        thread, so no post-apply snapshot rides back."""
        fake = _FakeSession()
        await uds_server(fake)
        async with SessionClient() as client:
            result = await client.apply_settings(world_name="X")
        assert result is None

    async def test_omitted_kwargs_are_absent_on_the_wire(self, uds_server: UdsServer):
        """Setting only ``world_name`` must leave every other optional field
        unset — the server sees None for them (proto3 explicit presence), so it
        can leave those engine fields untouched."""
        fake = _FakeSession()
        await uds_server(fake)
        async with SessionClient() as client:
            await client.apply_settings(world_name="Renamed")
        patch = fake.last_patch
        assert patch is not None
        assert patch.world_name == "Renamed"
        # Every other presence-gated field stayed off the wire.
        assert patch.world_description is None
        assert patch.max_users is None
        assert patch.hide_from_listing is None
        assert patch.mobile_friendly is None
        assert patch.away_kick_enabled is None
        assert patch.away_kick_minutes is None
        assert patch.auto_save_enabled is None
        assert patch.auto_save_interval_minutes is None
        assert patch.auto_cleanup_enabled is None
        assert patch.auto_cleanup_interval_seconds is None

    async def test_explicit_false_bool_rides_on_the_wire(self, uds_server: UdsServer):
        """``hide_from_listing=False`` is a real intent ("make it visible"),
        not an omission.

        proto3 ``optional`` must carry it as False, distinct from
        None, so the server applies the change.
        """
        fake = _FakeSession()
        await uds_server(fake)
        async with SessionClient() as client:
            await client.apply_settings(hide_from_listing=False)
        patch = fake.last_patch
        assert patch is not None
        assert patch.hide_from_listing is False
        # Untouched bool stays absent — proves False != None on the wire.
        assert patch.mobile_friendly is None

    async def test_explicit_zero_scalar_rides_on_the_wire(self, uds_server: UdsServer):
        """``max_users=0`` (and a 0.0 interval) are valid values, not omissions
        — they must cross the wire, not collapse to None."""
        fake = _FakeSession()
        await uds_server(fake)
        async with SessionClient() as client:
            await client.apply_settings(max_users=0, away_kick_minutes=0.0)
        patch = fake.last_patch
        assert patch is not None
        assert patch.max_users == 0
        assert patch.away_kick_minutes == 0.0
        assert patch.auto_save_interval_minutes is None

    async def test_empty_string_rides_on_the_wire(self, uds_server: UdsServer):
        """``world_description=""`` clears the description (a real intent); the
        empty string must cross the wire distinct from None."""
        fake = _FakeSession()
        await uds_server(fake)
        async with SessionClient() as client:
            await client.apply_settings(world_description="")
        patch = fake.last_patch
        assert patch is not None
        assert patch.world_description == ""
        assert patch.world_name is None

    async def test_access_level_none_sends_unspecified_sentinel(
        self, uds_server: UdsServer
    ):
        """``access_level=None`` means "leave unchanged"; the access_level enum
        has no optional flag, so the sentinel UNSPECIFIED carries that
        intent."""
        fake = _FakeSession()
        await uds_server(fake)
        async with SessionClient() as client:
            await client.apply_settings(world_name="X")  # access_level omitted
        patch = fake.last_patch
        assert patch is not None
        assert patch.access_level == PbSessionAccessLevel.UNSPECIFIED

    @pytest.mark.parametrize(
        ("public", "wire"),
        [
            (SessionAccessLevel.PRIVATE, PbSessionAccessLevel.PRIVATE),
            (SessionAccessLevel.LAN, PbSessionAccessLevel.LAN),
            (SessionAccessLevel.CONTACTS, PbSessionAccessLevel.CONTACTS),
            (
                SessionAccessLevel.CONTACTS_PLUS,
                PbSessionAccessLevel.CONTACTS_PLUS,
            ),
            (
                SessionAccessLevel.REGISTERED_USERS,
                PbSessionAccessLevel.REGISTERED_USERS,
            ),
            (SessionAccessLevel.ANYONE, PbSessionAccessLevel.ANYONE),
        ],
    )
    async def test_concrete_access_level_maps_to_its_wire_value(
        self,
        uds_server: UdsServer,
        public: SessionAccessLevel,
        wire: PbSessionAccessLevel,
    ):
        fake = _FakeSession()
        await uds_server(fake)
        async with SessionClient() as client:
            await client.apply_settings(access_level=public)
        patch = fake.last_patch
        assert patch is not None
        assert patch.access_level == wire

    async def test_tags_sequence_sets_replace_flag_and_carries_values(
        self, uds_server: UdsServer
    ):
        """Passing a tags sequence is replace-all: ``replace_tags`` gates on, the
        values cross the wire."""
        fake = _FakeSession()
        await uds_server(fake)
        async with SessionClient() as client:
            await client.apply_settings(tags=["a", "b"])
        patch = fake.last_patch
        assert patch is not None
        assert patch.replace_tags is True
        assert list(patch.tags) == ["a", "b"]

    async def test_empty_tags_sequence_clears_via_replace_flag(
        self, uds_server: UdsServer
    ):
        """``tags=[]`` is "clear the whole tag set", not "leave unchanged":

        ``replace_tags`` is still True with an empty list.
        """
        fake = _FakeSession()
        await uds_server(fake)
        async with SessionClient() as client:
            await client.apply_settings(tags=[])
        patch = fake.last_patch
        assert patch is not None
        assert patch.replace_tags is True
        assert list(patch.tags) == []

    async def test_tags_none_leaves_replace_flag_off(self, uds_server: UdsServer):
        """``tags=None`` (the default) leaves the tag set untouched: the
        ``replace_tags`` gate stays False so the server ignores the tags
        field."""
        fake = _FakeSession()
        await uds_server(fake)
        async with SessionClient() as client:
            await client.apply_settings(world_name="X")  # tags omitted
        patch = fake.last_patch
        assert patch is not None
        assert patch.replace_tags is False

    async def test_raises_when_not_connected(self):
        client = SessionClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.apply_settings(world_name="X")


# ===========================================================================
# list_users: wire -> SessionUser tuple mapping.
# ===========================================================================


class TestListUsers:
    async def test_decodes_every_user_field(self, uds_server: UdsServer):
        await uds_server(
            _FakeSession(
                users=[
                    PbSessionUser(
                        user_id="U-1",
                        user_name="alice",
                        is_host=True,
                        is_local_user=True,
                        is_present_in_world=True,
                        is_silenced=False,
                        # 0.5 is exactly representable in proto float32; an
                        # inexact value (e.g. 0.8) would survive the wire as
                        # 0.800000011920929 and the dataclass equality would be
                        # asserting float precision, not the field mapping.
                        local_volume=0.5,
                        role_name="Admin",
                        platform="Windows",
                        head_device="Index",
                    )
                ]
            )
        )
        async with SessionClient() as client:
            users = await client.list_users()
        assert users == (
            SessionUser(
                user_id="U-1",
                user_name="alice",
                is_host=True,
                is_local_user=True,
                is_present_in_world=True,
                is_silenced=False,
                local_volume=0.5,
                role_name="Admin",
                platform="Windows",
                head_device="Index",
            ),
        )

    async def test_returns_a_tuple_preserving_server_order(self, uds_server: UdsServer):
        await uds_server(
            _FakeSession(
                users=[
                    PbSessionUser(user_name="first"),
                    PbSessionUser(user_name="second"),
                    PbSessionUser(user_name="third"),
                ]
            )
        )
        async with SessionClient() as client:
            users = await client.list_users()
        assert isinstance(users, tuple)
        assert [u.user_name for u in users] == ["first", "second", "third"]

    async def test_empty_session_yields_empty_tuple(self, uds_server: UdsServer):
        await uds_server(_FakeSession(users=[]))
        async with SessionClient() as client:
            users = await client.list_users()
        assert users == ()

    async def test_raises_when_not_connected(self):
        client = SessionClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.list_users()


# ===========================================================================
# UserTarget mapping across the moderation RPCs.
# ===========================================================================


class TestUserTargeting:
    async def test_kick_forwards_user_id_name_and_local(self, uds_server: UdsServer):
        fake = _FakeSession()
        await uds_server(fake)
        async with SessionClient() as client:
            await client.kick_user(user_id="U-9", user_name="bob", local=False)
        assert fake.last_kick is not None
        target = fake.last_kick.target
        assert target is not None
        assert target.user_id == "U-9"
        assert target.user_name == "bob"
        assert target.local is False

    async def test_ban_forwards_target(self, uds_server: UdsServer):
        fake = _FakeSession()
        await uds_server(fake)
        async with SessionClient() as client:
            await client.ban_user(user_name="charlie")
        assert fake.last_ban is not None
        target = fake.last_ban.target
        assert target is not None
        assert target.user_name == "charlie"
        assert target.user_id == ""
        assert target.local is False

    async def test_local_flag_targets_self(self, uds_server: UdsServer):
        """``local=True`` rides on the target so the server resolves "self"
        without an id/name."""
        fake = _FakeSession()
        await uds_server(fake)
        async with SessionClient() as client:
            await client.ban_user(local=True)
        assert fake.last_ban is not None
        target = fake.last_ban.target
        assert target is not None
        assert target.local is True
        assert target.user_id == ""
        assert target.user_name == ""

    async def test_respawn_self_targets_the_local_user(self, uds_server: UdsServer):
        """``respawn_self()`` is sugar for ``respawn_user(local=True)`` — the
        target's ``local`` flag must be set with no id/name."""
        fake = _FakeSession()
        await uds_server(fake)
        async with SessionClient() as client:
            await client.respawn_self()
        assert fake.last_respawn is not None
        target = fake.last_respawn.target
        assert target is not None
        assert target.local is True
        assert target.user_id == ""
        assert target.user_name == ""

    async def test_respawn_user_forwards_target(self, uds_server: UdsServer):
        fake = _FakeSession()
        await uds_server(fake)
        async with SessionClient() as client:
            await client.respawn_user(user_id="U-3")
        assert fake.last_respawn is not None
        target = fake.last_respawn.target
        assert target is not None
        assert target.user_id == "U-3"
        assert target.local is False


# ===========================================================================
# kick: KickKind propagation.
# ===========================================================================


class TestKickKind:
    async def test_default_kind_is_kick_and_revoke(self, uds_server: UdsServer):
        """No ``kind`` given defaults to KICK_AND_REVOKE (revoke the session
        invite too) — the stronger, documented default."""
        fake = _FakeSession()
        await uds_server(fake)
        async with SessionClient() as client:
            await client.kick_user(user_id="U-1")
        assert fake.last_kick is not None
        assert fake.last_kick.kind == PbKickKind.KICK_AND_REVOKE

    async def test_kick_only_maps_to_kick_wire_value(self, uds_server: UdsServer):
        fake = _FakeSession()
        await uds_server(fake)
        async with SessionClient() as client:
            await client.kick_user(user_id="U-1", kind=KickKind.KICK)
        assert fake.last_kick is not None
        assert fake.last_kick.kind == PbKickKind.KICK

    async def test_kick_and_revoke_maps_to_its_wire_value(self, uds_server: UdsServer):
        fake = _FakeSession()
        await uds_server(fake)
        async with SessionClient() as client:
            await client.kick_user(user_id="U-1", kind=KickKind.KICK_AND_REVOKE)
        assert fake.last_kick is not None
        assert fake.last_kick.kind == PbKickKind.KICK_AND_REVOKE


# ===========================================================================
# silence / set_user_role: request body + returned SessionUser snapshot.
# ===========================================================================


class TestSilenceUser:
    async def test_default_silences_and_returns_updated_user(
        self, uds_server: UdsServer
    ):
        """``silence_user`` defaults to silenced=True and returns the updated
        SessionUser snapshot the server reports."""
        fake = _FakeSession(
            silence_user=PbSessionUser(user_name="muted", is_silenced=True)
        )
        await uds_server(fake)
        async with SessionClient() as client:
            user = await client.silence_user(user_id="U-1")
        assert fake.last_silence is not None
        assert fake.last_silence.silenced is True
        assert user.user_name == "muted"
        assert user.is_silenced is True

    async def test_unsilence_sends_silenced_false(self, uds_server: UdsServer):
        fake = _FakeSession(
            silence_user=PbSessionUser(user_name="unmuted", is_silenced=False)
        )
        await uds_server(fake)
        async with SessionClient() as client:
            user = await client.silence_user(user_id="U-1", silenced=False)
        assert fake.last_silence is not None
        assert fake.last_silence.silenced is False
        assert user.is_silenced is False


class TestSetUserRole:
    async def test_sends_role_name_and_target_and_returns_updated_user(
        self, uds_server: UdsServer
    ):
        fake = _FakeSession(
            set_role_user=PbSessionUser(user_name="dave", role_name="Builder")
        )
        await uds_server(fake)
        async with SessionClient() as client:
            user = await client.set_user_role("Builder", user_name="dave")
        assert fake.last_set_role is not None
        assert fake.last_set_role.role_name == "Builder"
        target = fake.last_set_role.target
        assert target is not None
        assert target.user_name == "dave"
        assert user == SessionUser(
            user_id="",
            user_name="dave",
            is_host=False,
            is_local_user=False,
            is_present_in_world=False,
            is_silenced=False,
            local_volume=0.0,
            role_name="Builder",
            platform="",
            head_device="",
        )


# ===========================================================================
# list_roles / get_user_role_overrides: Permissions tab read mapping.
# ===========================================================================


class TestListRoles:
    async def test_maps_roles_and_default_assignments(self, uds_server: UdsServer):
        await uds_server(
            _FakeSession(
                roles_response=ListRolesResponse(
                    roles=[
                        PbSessionRole(
                            role_name="Admin",
                            role_description="full control",
                            is_highest=True,
                            is_lowest=False,
                        ),
                        PbSessionRole(
                            role_name="Guest",
                            role_description="",
                            is_highest=False,
                            is_lowest=True,
                        ),
                    ],
                    default_anonymous_role="Guest",
                    default_visitor_role="Guest",
                    default_contact_role="Builder",
                    default_host_role="Admin",
                    default_owner_role="Admin",
                )
            )
        )
        async with SessionClient() as client:
            roles = await client.list_roles()
        assert roles == SessionRoles(
            roles=(
                SessionRole(
                    role_name="Admin",
                    role_description="full control",
                    is_highest=True,
                    is_lowest=False,
                ),
                SessionRole(
                    role_name="Guest",
                    role_description="",
                    is_highest=False,
                    is_lowest=True,
                ),
            ),
            default_anonymous_role="Guest",
            default_visitor_role="Guest",
            default_contact_role="Builder",
            default_host_role="Admin",
            default_owner_role="Admin",
        )

    async def test_roles_collection_is_a_tuple(self, uds_server: UdsServer):
        await uds_server(
            _FakeSession(
                roles_response=ListRolesResponse(
                    roles=[PbSessionRole(role_name="Admin")]
                )
            )
        )
        async with SessionClient() as client:
            roles = await client.list_roles()
        assert isinstance(roles.roles, tuple)


class TestGetUserRoleOverrides:
    async def test_maps_each_override_entry(self, uds_server: UdsServer):
        from resoio._generated.resonite_io.v1 import (
            UserRoleOverride as PbUserRoleOverride,
        )

        await uds_server(
            _FakeSession(
                overrides_response=GetUserRoleOverridesResponse(
                    overrides=[
                        PbUserRoleOverride(user_id="U-1", role_name="Admin"),
                        PbUserRoleOverride(user_id="U-2", role_name="Guest"),
                    ]
                )
            )
        )
        async with SessionClient() as client:
            overrides = await client.get_user_role_overrides()
        assert overrides == (
            UserRoleOverride(user_id="U-1", role_name="Admin"),
            UserRoleOverride(user_id="U-2", role_name="Guest"),
        )

    async def test_empty_overrides_yield_empty_tuple(self, uds_server: UdsServer):
        await uds_server(_FakeSession())
        async with SessionClient() as client:
            overrides = await client.get_user_role_overrides()
        assert overrides == ()
