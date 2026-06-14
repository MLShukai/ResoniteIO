"""CLI surface tests for ``resoio session <group> <action>``.

The ``session`` command group mirrors ``world``: a parent parser holds
nested group parsers (``settings`` / ``users`` / ``user`` / ``roles`` /
``overrides``), each holding its action leaves.

Two complementary layers, matching ``cli/test_world.py``:

1. Parser-only tests build the real parser via ``_build_parser`` and
   assert that each flag lands on the right namespace value and that the
   group/leaf structure rejects bad input. No I/O.
2. End-to-end dispatch tests stand up an in-process recording
   :class:`SessionBase` server over a real UDS and drive ``_amain`` so
   the *request actually sent on the wire* proves the CLI selected the
   right RPC and mapped its flags. This avoids coupling to internal
   handler names and does NOT mock grpclib internals (real round-trip).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from grpclib.server import Server

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
    UserRoleOverride as PbUserRoleOverride,
)
from resoio.cli import _amain, _build_parser

# ===========================================================================
# Parser-only tests: group/leaf structure + flag -> namespace mapping.
# ===========================================================================


@pytest.mark.parametrize(
    "argv",
    [
        ["session"],
        ["session", "settings"],
        ["session", "users"],
        ["session", "user"],
        ["session", "roles"],
        ["session", "overrides"],
    ],
)
def test_group_without_action_is_rejected(argv: list[str]):
    """Each group (``settings``/``users``/``user``/``roles``/``overrides``) is
    a parent with a required action leaf — naming the group alone must error
    (argparse exit code 2)."""
    parser = _build_parser()
    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(argv)
    assert excinfo.value.code == 2


def test_settings_set_collects_all_scalar_and_bool_flags():
    parser = _build_parser()
    args = parser.parse_args(
        [
            "session",
            "settings",
            "set",
            "--world-name",
            "Hub",
            "--description",
            "a place",
            "--max-users",
            "16",
            "--access-level",
            "anyone",
            "--hide-from-listing",
            "--away-kick-minutes",
            "5.5",
        ]
    )
    assert args.world_name == "Hub"
    assert args.world_description == "a place"
    assert args.max_users == 16
    assert args.access_level == "anyone"
    assert args.hide_from_listing is True
    assert args.away_kick_minutes == 5.5


def test_settings_set_bool_flag_defaults_to_none_when_absent():
    """A BooleanOptionalAction flag left off is None (= "leave unchanged"),
    distinct from an explicit ``--no-*`` which is False."""
    parser = _build_parser()
    args = parser.parse_args(["session", "settings", "set", "--world-name", "X"])
    assert args.hide_from_listing is None
    assert args.mobile_friendly is None


def test_settings_set_no_variant_maps_to_false():
    parser = _build_parser()
    args = parser.parse_args(["session", "settings", "set", "--no-hide-from-listing"])
    assert args.hide_from_listing is False


def test_settings_set_access_level_rejects_unknown_choice():
    parser = _build_parser()
    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["session", "settings", "set", "--access-level", "nope"])
    assert excinfo.value.code == 2


def test_kick_target_id_name_self_are_mutually_exclusive():
    """The target is exactly one of ``--id`` / ``--name`` / ``--self``; giving
    two must be rejected at parse time."""
    parser = _build_parser()
    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["session", "user", "kick", "--id", "U-1", "--name", "bob"])
    assert excinfo.value.code == 2


def test_kick_requires_a_target():
    """``user kick`` with no target flag is rejected — a kick needs a
    subject."""
    parser = _build_parser()
    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["session", "user", "kick"])
    assert excinfo.value.code == 2


def test_kick_kind_choice_defaults_to_kick_and_revoke():
    parser = _build_parser()
    args = parser.parse_args(["session", "user", "kick", "--id", "U-1"])
    assert args.kind == "kick-and-revoke"


def test_silence_on_off_flags_default_to_on():
    parser = _build_parser()
    on = parser.parse_args(["session", "user", "silence", "--id", "U-1"])
    assert on.silenced is True
    off = parser.parse_args(["session", "user", "silence", "--id", "U-1", "--off"])
    assert off.silenced is False


def test_respawn_allows_no_target_at_parse_time():
    """Unlike kick/ban, ``user respawn`` may omit the target (it then targets
    self); the parser must accept that with local defaulting off."""
    parser = _build_parser()
    args = parser.parse_args(["session", "user", "respawn"])
    assert args.user_id == ""
    assert args.user_name == ""
    assert args.local is False


def test_role_takes_positional_role_name_and_a_target():
    parser = _build_parser()
    args = parser.parse_args(["session", "user", "role", "Builder", "--name", "dave"])
    assert args.role_name == "Builder"
    assert args.user_name == "dave"


@pytest.mark.parametrize(
    "argv",
    [
        ["session", "settings", "get"],
        ["session", "users", "list"],
        ["session", "roles", "list"],
        ["session", "overrides", "list"],
    ],
)
def test_socket_flag_accepted_on_each_leaf(argv: list[str], tmp_path: Path):
    """``-s/--socket`` is re-attached on each leaf (argparse does not inherit
    parent-subparser flags)."""
    parser = _build_parser()
    sock = str(tmp_path / "x.sock")
    args = parser.parse_args([*argv, "-s", sock])
    assert args.socket == sock


# ===========================================================================
# End-to-end dispatch: argv -> _amain -> in-process SessionBase server.
#
# A recording fake proves the CLI selected the right RPC and mapped flags
# into the request. Real UDS + real grpclib round-trip (no mocks).
# ===========================================================================


class _RecordingSession(SessionBase):
    """In-process Session server capturing each request for assertion."""

    def __init__(self) -> None:
        self.settings = PbSessionSettings(
            world_name="Hub",
            access_level=PbSessionAccessLevel.ANYONE,
        )
        self.users = [
            PbSessionUser(user_id="U-1", user_name="alice", is_host=True),
            PbSessionUser(user_id="U-2", user_name="bob"),
        ]
        self.last_patch: SessionSettingsPatch | None = None
        self.kick_requests: list[KickUserRequest] = []
        self.ban_requests: list[BanUserRequest] = []
        self.silence_requests: list[SilenceUserRequest] = []
        self.respawn_requests: list[RespawnUserRequest] = []
        self.set_role_requests: list[SetUserRoleRequest] = []
        self.list_users_requests: list[ListUsersRequest] = []
        self.list_roles_requests: list[ListRolesRequest] = []
        self.overrides_requests: list[GetUserRoleOverridesRequest] = []

    async def get_settings(self, message: GetSettingsRequest) -> PbSessionSettings:
        return self.settings

    async def apply_settings(
        self, message: SessionSettingsPatch
    ) -> ApplySettingsResponse:
        self.last_patch = message
        return ApplySettingsResponse()

    async def list_users(self, message: ListUsersRequest) -> ListUsersResponse:
        self.list_users_requests.append(message)
        return ListUsersResponse(users=self.users)

    async def kick_user(self, message: KickUserRequest) -> KickUserResponse:
        self.kick_requests.append(message)
        return KickUserResponse()

    async def ban_user(self, message: BanUserRequest) -> BanUserResponse:
        self.ban_requests.append(message)
        return BanUserResponse()

    async def silence_user(self, message: SilenceUserRequest) -> SilenceUserResponse:
        self.silence_requests.append(message)
        return SilenceUserResponse(
            user=PbSessionUser(user_name="alice", is_silenced=message.silenced)
        )

    async def respawn_user(self, message: RespawnUserRequest) -> RespawnUserResponse:
        self.respawn_requests.append(message)
        return RespawnUserResponse()

    async def set_user_role(self, message: SetUserRoleRequest) -> SetUserRoleResponse:
        self.set_role_requests.append(message)
        return SetUserRoleResponse(
            user=PbSessionUser(user_name="alice", role_name=message.role_name)
        )

    async def list_roles(self, message: ListRolesRequest) -> ListRolesResponse:
        self.list_roles_requests.append(message)
        return ListRolesResponse(
            roles=[PbSessionRole(role_name="Admin", is_highest=True)],
            default_host_role="Admin",
        )

    async def get_user_role_overrides(
        self, message: GetUserRoleOverridesRequest
    ) -> GetUserRoleOverridesResponse:
        self.overrides_requests.append(message)
        return GetUserRoleOverridesResponse(
            overrides=[PbUserRoleOverride(user_id="U-1", role_name="Admin")]
        )


async def _run_session(
    argv: list[str],
    socket_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> int:
    monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
    args = _build_parser().parse_args(argv)
    return await _amain(args)


async def _serve(socket_path: Path) -> tuple[Server, _RecordingSession]:
    fake = _RecordingSession()
    server = Server([fake])
    await server.start(path=str(socket_path))
    return server, fake


async def test_settings_get_dispatches_get_settings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    socket_path = tmp_path / "rio-session.sock"
    server, fake = await _serve(socket_path)
    try:
        rc = await _run_session(
            ["session", "settings", "get"], socket_path, monkeypatch
        )
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()
    # get must not patch; output names a settings field.
    assert fake.last_patch is None
    assert "world_name" in capsys.readouterr().out


async def test_settings_set_maps_flags_into_patch_and_refetches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """``settings set`` maps the kebab CLI flags onto the patch (kebab access
    level -> wire enum, --no-* -> explicit False) and re-fetches afterwards
    (get_settings) to print the post-apply state."""
    socket_path = tmp_path / "rio-session.sock"
    server, fake = await _serve(socket_path)
    try:
        rc = await _run_session(
            [
                "session",
                "settings",
                "set",
                "--world-name",
                "Renamed",
                "--max-users",
                "8",
                "--access-level",
                "contacts-plus",
                "--no-hide-from-listing",
            ],
            socket_path,
            monkeypatch,
        )
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    patch = fake.last_patch
    assert patch is not None
    assert patch.world_name == "Renamed"
    assert patch.max_users == 8
    assert patch.access_level == PbSessionAccessLevel.CONTACTS_PLUS
    # --no-hide-from-listing is an explicit False, not an omission.
    assert patch.hide_from_listing is False
    # An untouched bool stayed off the wire (None), proving False != None.
    assert patch.mobile_friendly is None


async def test_settings_set_tags_are_split_and_replace_flag_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """``--tags a,b,c`` is split on commas into the replace-all tag set."""
    socket_path = tmp_path / "rio-session.sock"
    server, fake = await _serve(socket_path)
    try:
        rc = await _run_session(
            ["session", "settings", "set", "--tags", "a,b,c"],
            socket_path,
            monkeypatch,
        )
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    patch = fake.last_patch
    assert patch is not None
    assert patch.replace_tags is True
    assert list(patch.tags) == ["a", "b", "c"]


async def test_settings_set_without_flags_exits_with_code_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """``settings set`` with no field flag is rejected with exit code 2;
    whether that happens at parse time or at dispatch is not part of the
    contract, so parse + dispatch run inside one raises-block (mirrors display
    set)."""
    socket_path = tmp_path / "rio-session.sock"
    server, fake = await _serve(socket_path)
    try:
        with pytest.raises(SystemExit) as excinfo:
            await _run_session(["session", "settings", "set"], socket_path, monkeypatch)
        assert excinfo.value.code == 2
    finally:
        server.close()
        await server.wait_closed()
    # Nothing was applied.
    assert fake.last_patch is None


async def test_users_list_dispatches_list_users(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    socket_path = tmp_path / "rio-session.sock"
    server, fake = await _serve(socket_path)
    try:
        rc = await _run_session(["session", "users", "list"], socket_path, monkeypatch)
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()
    assert len(fake.list_users_requests) == 1
    out = capsys.readouterr().out
    assert "alice" in out
    assert "bob" in out


async def test_kick_dispatch_maps_target_and_kind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    socket_path = tmp_path / "rio-session.sock"
    server, fake = await _serve(socket_path)
    try:
        rc = await _run_session(
            ["session", "user", "kick", "--id", "U-7", "--kind", "kick"],
            socket_path,
            monkeypatch,
        )
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    assert len(fake.kick_requests) == 1
    req = fake.kick_requests[0]
    assert req.target is not None
    assert req.target.user_id == "U-7"
    assert req.target.local is False
    # CLI 'kick' choice -> public KickKind.KICK -> wire KICK.
    assert req.kind == PbKickKind.KICK
    # Other RPCs untouched — proves leaf selection, not a fallthrough.
    assert fake.ban_requests == []


async def test_kick_default_kind_dispatches_kick_and_revoke(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    socket_path = tmp_path / "rio-session.sock"
    server, fake = await _serve(socket_path)
    try:
        rc = await _run_session(
            ["session", "user", "kick", "--name", "bob"],
            socket_path,
            monkeypatch,
        )
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    assert len(fake.kick_requests) == 1
    req = fake.kick_requests[0]
    assert req.target is not None
    assert req.target.user_name == "bob"
    assert req.kind == PbKickKind.KICK_AND_REVOKE


async def test_ban_self_dispatch_sets_local_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """``--self`` selects the local user: the target's ``local`` flag rides on
    the wire with no id/name."""
    socket_path = tmp_path / "rio-session.sock"
    server, fake = await _serve(socket_path)
    try:
        rc = await _run_session(
            ["session", "user", "ban", "--self"], socket_path, monkeypatch
        )
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    assert len(fake.ban_requests) == 1
    target = fake.ban_requests[0].target
    assert target is not None
    assert target.local is True
    assert target.user_id == ""
    assert target.user_name == ""


async def test_silence_off_dispatch_sends_silenced_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    socket_path = tmp_path / "rio-session.sock"
    server, fake = await _serve(socket_path)
    try:
        rc = await _run_session(
            ["session", "user", "silence", "--id", "U-1", "--off"],
            socket_path,
            monkeypatch,
        )
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    assert len(fake.silence_requests) == 1
    req = fake.silence_requests[0]
    assert req.silenced is False
    assert req.target is not None
    assert req.target.user_id == "U-1"


async def test_respawn_without_target_dispatches_local_true(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """``user respawn`` with no target flag respawns self: the handler resolves
    no-target to ``local=True`` on the wire even though the parser leaves
    ``local`` False."""
    socket_path = tmp_path / "rio-session.sock"
    server, fake = await _serve(socket_path)
    try:
        rc = await _run_session(
            ["session", "user", "respawn"], socket_path, monkeypatch
        )
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    assert len(fake.respawn_requests) == 1
    target = fake.respawn_requests[0].target
    assert target is not None
    assert target.local is True


async def test_respawn_with_target_dispatches_that_user(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    socket_path = tmp_path / "rio-session.sock"
    server, fake = await _serve(socket_path)
    try:
        rc = await _run_session(
            ["session", "user", "respawn", "--id", "U-9"],
            socket_path,
            monkeypatch,
        )
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    assert len(fake.respawn_requests) == 1
    target = fake.respawn_requests[0].target
    assert target is not None
    assert target.user_id == "U-9"
    # A concrete target must NOT be coerced to local=self.
    assert target.local is False


async def test_role_dispatch_sends_role_name_and_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    socket_path = tmp_path / "rio-session.sock"
    server, fake = await _serve(socket_path)
    try:
        rc = await _run_session(
            ["session", "user", "role", "Builder", "--name", "dave"],
            socket_path,
            monkeypatch,
        )
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    assert len(fake.set_role_requests) == 1
    req = fake.set_role_requests[0]
    assert req.role_name == "Builder"
    assert req.target is not None
    assert req.target.user_name == "dave"


async def test_roles_list_dispatches_list_roles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    socket_path = tmp_path / "rio-session.sock"
    server, fake = await _serve(socket_path)
    try:
        rc = await _run_session(["session", "roles", "list"], socket_path, monkeypatch)
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()
    assert len(fake.list_roles_requests) == 1
    assert "Admin" in capsys.readouterr().out


async def test_overrides_list_dispatches_get_user_role_overrides(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    socket_path = tmp_path / "rio-session.sock"
    server, fake = await _serve(socket_path)
    try:
        rc = await _run_session(
            ["session", "overrides", "list"], socket_path, monkeypatch
        )
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()
    assert len(fake.overrides_requests) == 1
    out = capsys.readouterr().out
    assert "U-1" in out
    assert "Admin" in out
