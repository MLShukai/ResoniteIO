"""CLI surface tests for ``resoio world <subcommand>``.

These tests pin the **argument-parsing + dispatch** contract of the
``world`` command group described in the World Python contract:

    resoio world sessions | records | random | join | start
                | list | focus | leave | current

Two complementary layers are exercised:

1. Pure parser tests build the real parser via ``_build_parser`` and
   assert that each flag lands on the right namespace value and that the
   right leaf subcommand was selected. No I/O.
2. End-to-end dispatch tests stand up an in-process ``WorldBase`` server
   over a real UDS and drive ``_amain`` so that the *request actually
   sent on the wire* proves the CLI selected the correct RPC and mapped
   its flags into the request body. This avoids coupling to the names of
   the CLI's internal handler functions (which are not part of the spec)
   while still proving handler selection — and it does NOT mock grpclib
   internals (a real server / real client round-trip).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from grpclib.server import Server

from resoio._generated.resonite_io.v1 import (
    FocusRequest,
    FocusResponse,
    GetCurrentRequest,
    GetCurrentResponse,
    JoinRequest,
    JoinResponse,
    LeaveRequest,
    LeaveResponse,
    ListOpenWorldsRequest,
    ListOpenWorldsResponse,
    ListRecordsRequest,
    ListRecordsResponse,
    ListSessionsRequest,
    ListSessionsResponse,
    OpenWorld,
    RecordSort,
    RecordSortDirection,
    RecordSource,
    SessionFilter,
    StartWorldRequest,
    StartWorldResponse,
    WorldBase,
    WorldRecord,
    WorldSession,
)
from resoio.cli import _amain, _build_parser

# ===========================================================================
# Parser-only tests: flag -> namespace mapping + leaf selection.
# ===========================================================================


def test_world_without_subcommand_is_rejected():
    """``world`` is a command group, not a leaf — bare ``world`` must error out
    (argparse exit code 2), mirroring ``locomotion``'s required nested
    subparser."""
    parser = _build_parser()
    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["world"])
    assert excinfo.value.code == 2


def test_sessions_collects_search_filter_and_paging_flags():
    parser = _build_parser()
    args = parser.parse_args(
        [
            "world",
            "sessions",
            "--search",
            "neos",
            "--filter",
            "friends",
            "--min-users",
            "3",
            "--page",
            "2",
            "--page-size",
            "25",
        ]
    )
    assert args.search == "neos"
    assert args.filter == "friends"
    assert args.min_users == 3
    assert args.page == 2
    assert args.page_size == 25


def test_sessions_filter_choices_reject_unknown_value():
    """``--filter`` is constrained to all/friends/headless; an unknown
    value must be rejected at parse time rather than silently forwarded."""
    parser = _build_parser()
    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["world", "sessions", "--filter", "nope"])
    assert excinfo.value.code == 2


def test_sessions_filter_defaults_to_all():
    parser = _build_parser()
    args = parser.parse_args(["world", "sessions"])
    assert args.filter == "all"


def test_records_collects_source_tags_and_sort_flags():
    parser = _build_parser()
    args = parser.parse_args(
        [
            "world",
            "records",
            "--source",
            "own",
            "--tag",
            "game",
            "--tag",
            "avatar",
            "--owner",
            "U-me",
            "--offset",
            "60",
            "--count",
            "30",
            "--sort",
            "visits",
            "--asc",
        ]
    )
    assert args.source == "own"
    # Repeated --tag accumulates into a list (AND-conditioned tags).
    assert args.tags == ["game", "avatar"]
    assert args.owner == "U-me"
    assert args.offset == 60
    assert args.count == 30
    assert args.sort == "visits"
    assert args.asc is True


def test_records_asc_defaults_to_descending():
    """Without ``--asc`` the sort direction is descending (the documented
    default); the flag is a plain store_true switch."""
    parser = _build_parser()
    args = parser.parse_args(["world", "records"])
    assert args.asc is False


def test_random_collects_source_and_count_flags():
    parser = _build_parser()
    args = parser.parse_args(
        ["world", "random", "--source", "featured", "--count", "5"]
    )
    assert args.source == "featured"
    assert args.count == 5


def test_join_accepts_session_id():
    parser = _build_parser()
    args = parser.parse_args(["world", "join", "--session-id", "S-123"])
    assert args.session_id == "S-123"


def test_join_accepts_url_alternative():
    parser = _build_parser()
    args = parser.parse_args(["world", "join", "--url", "lnl-nat://abc"])
    assert args.url == "lnl-nat://abc"


def test_join_session_id_and_url_are_mutually_exclusive():
    """The spec requires exactly one of ``--session-id`` / ``--url``; supplying
    both must be rejected at parse time."""
    parser = _build_parser()
    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(
            ["world", "join", "--session-id", "S-1", "--url", "lnl-nat://x"]
        )
    assert excinfo.value.code == 2


def test_join_requires_one_of_session_id_or_url():
    """Neither target supplied is also rejected (a join needs a target)."""
    parser = _build_parser()
    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["world", "join"])
    assert excinfo.value.code == 2


def test_join_no_focus_flag_parses():
    parser = _build_parser()
    args = parser.parse_args(["world", "join", "--session-id", "S-1", "--no-focus"])
    assert args.no_focus is True


def test_join_focus_is_default_on():
    parser = _build_parser()
    args = parser.parse_args(["world", "join", "--session-id", "S-1"])
    assert args.no_focus is False


def test_start_requires_record_id():
    parser = _build_parser()
    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["world", "start"])
    assert excinfo.value.code == 2


def test_start_collects_record_owner_and_no_focus():
    parser = _build_parser()
    args = parser.parse_args(
        [
            "world",
            "start",
            "--record-id",
            "R-1",
            "--owner-id",
            "U-owner",
            "--no-focus",
        ]
    )
    assert args.record_id == "R-1"
    assert args.owner_id == "U-owner"
    assert args.no_focus is True


def test_focus_parses_handle_as_int():
    parser = _build_parser()
    args = parser.parse_args(["world", "focus", "3"])
    assert args.handle == 3
    assert isinstance(args.handle, int)


def test_focus_rejects_non_integer_handle():
    parser = _build_parser()
    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["world", "focus", "abc"])
    assert excinfo.value.code == 2


def test_leave_parses_handle_as_int():
    parser = _build_parser()
    args = parser.parse_args(["world", "leave", "7"])
    assert args.handle == 7
    assert isinstance(args.handle, int)


def test_list_and_current_take_no_positional():
    parser = _build_parser()
    # Both are bare leaf commands; they parse cleanly with no extra args.
    assert _build_parser().parse_args(["world", "list"]).command == "world"
    assert parser.parse_args(["world", "current"]).command == "world"


@pytest.mark.parametrize(
    "leaf",
    ["sessions", "records", "list", "current"],
)
def test_socket_flag_accepted_on_each_leaf(leaf: str, tmp_path: Path):
    """``-s/--socket`` is re-attached on the leaf (argparse does not inherit
    parent-subparser flags), matching locomotion/display."""
    parser = _build_parser()
    sock = str(tmp_path / "x.sock")
    args = parser.parse_args(["world", leaf, "-s", sock])
    assert args.socket == sock


# ===========================================================================
# End-to-end dispatch: argv -> _amain -> in-process WorldBase server.
#
# A recording fake server proves the CLI selected the right RPC and mapped
# flags into the request. Real UDS + real grpclib round-trip (no mocks).
# ===========================================================================


def _open_world(handle: int = 1, name: str = "Demo") -> OpenWorld:
    return OpenWorld(
        handle=handle,
        session_id="S-1",
        name=name,
        focused=True,
        user_count=2,
        access_level="Anyone",
    )


class _RecordingWorld(WorldBase):
    """In-process World server capturing each request for assertion."""

    def __init__(self) -> None:
        self.list_sessions_requests: list[ListSessionsRequest] = []
        self.list_records_requests: list[ListRecordsRequest] = []
        self.join_requests: list[JoinRequest] = []
        self.start_requests: list[StartWorldRequest] = []
        self.list_open_requests: list[ListOpenWorldsRequest] = []
        self.focus_requests: list[FocusRequest] = []
        self.leave_requests: list[LeaveRequest] = []
        self.get_current_requests: list[GetCurrentRequest] = []

    async def list_sessions(self, message: ListSessionsRequest) -> ListSessionsResponse:
        self.list_sessions_requests.append(message)
        return ListSessionsResponse(
            sessions=[
                WorldSession(
                    session_id="S-1",
                    name="Hub",
                    host_username="alice",
                    active_users=4,
                    access_level="Anyone",
                )
            ],
            total_count=1,
            page=message.page,
            page_size=message.page_size,
        )

    async def list_records(self, message: ListRecordsRequest) -> ListRecordsResponse:
        self.list_records_requests.append(message)
        return ListRecordsResponse(
            records=[
                WorldRecord(
                    record_id="R-1",
                    owner_id="U-me",
                    name="MyWorld",
                    record_url="resrec:///U-me/R-1",
                )
            ],
            has_more=False,
            offset=message.offset,
        )

    async def join(self, message: JoinRequest) -> JoinResponse:
        self.join_requests.append(message)
        return JoinResponse(world=_open_world(name="Joined"))

    async def start_world(self, message: StartWorldRequest) -> StartWorldResponse:
        self.start_requests.append(message)
        return StartWorldResponse(world=_open_world(name="Started"))

    async def list_open_worlds(
        self, message: ListOpenWorldsRequest
    ) -> ListOpenWorldsResponse:
        self.list_open_requests.append(message)
        return ListOpenWorldsResponse(worlds=[_open_world(handle=2, name="Open")])

    async def focus(self, message: FocusRequest) -> FocusResponse:
        self.focus_requests.append(message)
        return FocusResponse(world=_open_world(handle=message.handle, name="Focused"))

    async def leave(self, message: LeaveRequest) -> LeaveResponse:
        self.leave_requests.append(message)
        return LeaveResponse()

    async def get_current(self, message: GetCurrentRequest) -> GetCurrentResponse:
        self.get_current_requests.append(message)
        return GetCurrentResponse(world=_open_world(name="Current"), has_world=True)


async def _run_world(
    argv: list[str],
    socket_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> int:
    monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
    args = _build_parser().parse_args(argv)
    return await _amain(args)


async def test_sessions_dispatch_maps_flags_into_list_sessions_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    socket_path = tmp_path / "rio-world.sock"
    fake = _RecordingWorld()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        rc = await _run_world(
            [
                "world",
                "sessions",
                "--search",
                "hub",
                "--filter",
                "headless",
                "--min-users",
                "2",
                "--page",
                "1",
                "--page-size",
                "10",
            ],
            socket_path,
            monkeypatch,
        )
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    assert len(fake.list_sessions_requests) == 1
    req = fake.list_sessions_requests[0]
    assert req.search == "hub"
    # CLI 'headless' -> public SessionFilter.HEADLESS -> wire HEADLESS.
    assert req.filter == SessionFilter.HEADLESS
    assert req.min_active_users == 2
    assert req.page == 1
    assert req.page_size == 10
    # Other RPCs were not touched — proves leaf selection, not a fallthrough.
    assert fake.list_records_requests == []


async def test_records_dispatch_maps_source_tags_and_sort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    socket_path = tmp_path / "rio-world.sock"
    fake = _RecordingWorld()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        rc = await _run_world(
            [
                "world",
                "records",
                "--source",
                "own",
                "--tag",
                "game",
                "--tag",
                "avatar",
                "--owner",
                "U-me",
                "--offset",
                "60",
                "--count",
                "30",
                "--sort",
                "name",
                "--asc",
            ],
            socket_path,
            monkeypatch,
        )
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    assert len(fake.list_records_requests) == 1
    req = fake.list_records_requests[0]
    assert req.source == RecordSource.OWN
    assert list(req.required_tags) == ["game", "avatar"]
    assert req.owner_id == "U-me"
    assert req.offset == 60
    assert req.count == 30
    assert req.sort == RecordSort.NAME
    # --asc flips direction to ascending; default would be descending.
    assert req.sort_direction == RecordSortDirection.ASCENDING


async def test_random_dispatch_uses_random_sort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """``world random`` is sugar over list_records with sort=RANDOM."""
    socket_path = tmp_path / "rio-world.sock"
    fake = _RecordingWorld()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        rc = await _run_world(
            ["world", "random", "--source", "public", "--count", "5"],
            socket_path,
            monkeypatch,
        )
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    assert len(fake.list_records_requests) == 1
    req = fake.list_records_requests[0]
    assert req.sort == RecordSort.RANDOM
    assert req.source == RecordSource.PUBLIC
    assert req.count == 5


async def test_join_dispatch_sends_session_id_and_focus(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    socket_path = tmp_path / "rio-world.sock"
    fake = _RecordingWorld()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        rc = await _run_world(
            ["world", "join", "--session-id", "S-42"],
            socket_path,
            monkeypatch,
        )
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    assert len(fake.join_requests) == 1
    req = fake.join_requests[0]
    assert req.session_id == "S-42"
    assert req.session_url == ""
    # focus defaults on (no --no-focus given).
    assert req.focus is True


async def test_join_dispatch_url_with_no_focus(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    socket_path = tmp_path / "rio-world.sock"
    fake = _RecordingWorld()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        rc = await _run_world(
            ["world", "join", "--url", "lnl-nat://abc", "--no-focus"],
            socket_path,
            monkeypatch,
        )
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    assert len(fake.join_requests) == 1
    req = fake.join_requests[0]
    # The CLI's --url maps onto the proto session_url field.
    assert req.session_url == "lnl-nat://abc"
    assert req.session_id == ""
    assert req.focus is False


async def test_start_dispatch_sends_record_and_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    socket_path = tmp_path / "rio-world.sock"
    fake = _RecordingWorld()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        rc = await _run_world(
            ["world", "start", "--record-id", "R-9", "--owner-id", "U-x"],
            socket_path,
            monkeypatch,
        )
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    assert len(fake.start_requests) == 1
    req = fake.start_requests[0]
    assert req.record_id == "R-9"
    assert req.owner_id == "U-x"
    assert req.focus is True


async def test_list_dispatch_calls_list_open_worlds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    socket_path = tmp_path / "rio-world.sock"
    fake = _RecordingWorld()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        rc = await _run_world(["world", "list"], socket_path, monkeypatch)
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    assert len(fake.list_open_requests) == 1
    assert fake.focus_requests == []


async def test_focus_dispatch_sends_handle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    socket_path = tmp_path / "rio-world.sock"
    fake = _RecordingWorld()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        rc = await _run_world(["world", "focus", "5"], socket_path, monkeypatch)
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    assert len(fake.focus_requests) == 1
    assert fake.focus_requests[0].handle == 5


async def test_leave_dispatch_sends_handle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    socket_path = tmp_path / "rio-world.sock"
    fake = _RecordingWorld()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        rc = await _run_world(["world", "leave", "8"], socket_path, monkeypatch)
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    assert len(fake.leave_requests) == 1
    assert fake.leave_requests[0].handle == 8


async def test_current_dispatch_calls_get_current(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    socket_path = tmp_path / "rio-world.sock"
    fake = _RecordingWorld()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        rc = await _run_world(["world", "current"], socket_path, monkeypatch)
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    assert len(fake.get_current_requests) == 1
