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

import dataclasses
import json
import re
from pathlib import Path

import pytest
from grpclib.server import Server

from resoio._generated.resonite_io.v1 import (
    FetchThumbnailRequest,
    FetchThumbnailResponse,
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


def test_records_search_collects_free_text_query():
    """``records --search`` carries the free-text World-tab query verbatim,
    including the ``+required`` / ``-excluded`` operators (no client-side re-
    parsing)."""
    parser = _build_parser()
    args = parser.parse_args(["world", "records", "--search", "hub +game -nsfw"])
    assert args.search == "hub +game -nsfw"


def test_records_search_defaults_to_empty_string():
    """Without ``--search`` the records query is the empty string (= no free-
    text filter), mirroring ``WorldClient.list_records(search="")``."""
    parser = _build_parser()
    args = parser.parse_args(["world", "records"])
    assert args.search == ""


def test_records_asc_defaults_to_descending():
    """Without ``--asc`` the sort direction is descending (the documented
    default); the flag is a plain store_true switch."""
    parser = _build_parser()
    args = parser.parse_args(["world", "records"])
    assert args.asc is False


def test_random_subcommand_is_removed():
    """The ``world random`` leaf was removed; random worlds are now obtained
    via ``records --sort random``.

    ``world random`` must no longer parse.
    """
    parser = _build_parser()
    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["world", "random"])
    assert excinfo.value.code == 2


def test_records_sort_choices_still_include_random():
    """``random`` remains a valid ``--sort`` choice on the records leaf — it is
    the replacement for the removed ``random`` subcommand."""
    parser = _build_parser()
    args = parser.parse_args(["world", "records", "--sort", "random"])
    assert args.sort == "random"


def test_sessions_paging_display_flags_default():
    """The display flags default to: bounded output (limit 20), compact (no
    thumbnail column), cap enabled (``--all`` off)."""
    parser = _build_parser()
    args = parser.parse_args(["world", "sessions"])
    assert args.limit == 20
    assert args.wide is False
    assert args.show_all is False


def test_sessions_paging_display_flags_collected():
    parser = _build_parser()
    args = parser.parse_args(["world", "sessions", "--wide", "--limit", "5", "--all"])
    assert args.wide is True
    assert args.limit == 5
    assert args.show_all is True


def test_sessions_wide_short_flag_is_dash_w():
    parser = _build_parser()
    args = parser.parse_args(["world", "sessions", "-w"])
    assert args.wide is True


def test_records_paging_display_flags_default():
    parser = _build_parser()
    args = parser.parse_args(["world", "records"])
    assert args.limit == 20
    assert args.wide is False
    assert args.show_all is False


def test_records_paging_display_flags_collected():
    parser = _build_parser()
    args = parser.parse_args(["world", "records", "--wide", "--limit", "5", "--all"])
    assert args.wide is True
    assert args.limit == 5
    assert args.show_all is True


def test_records_wide_short_flag_is_dash_w():
    parser = _build_parser()
    args = parser.parse_args(["world", "records", "-w"])
    assert args.wide is True


def test_thumbnail_requires_uri():
    parser = _build_parser()
    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["world", "thumbnail"])
    assert excinfo.value.code == 2


def test_thumbnail_collects_uri_and_output():
    parser = _build_parser()
    args = parser.parse_args(
        ["world", "thumbnail", "resdb:///abc", "--output", "/tmp/x.webp"]
    )
    assert args.uri == "resdb:///abc"
    assert args.output == "/tmp/x.webp"


def test_thumbnail_output_short_flag_is_dash_o():
    parser = _build_parser()
    args = parser.parse_args(
        ["world", "thumbnail", "resdb:///abc", "-o", "/tmp/y.webp"]
    )
    assert args.output == "/tmp/y.webp"


def test_thumbnail_output_defaults_to_none():
    """Without ``-o`` the parsed output is None, the sentinel the handler maps
    to a CWD-relative date-stamped file (``-o -`` is the explicit stdout
    sentinel; see the dispatch tests below)."""
    parser = _build_parser()
    args = parser.parse_args(["world", "thumbnail", "resdb:///abc"])
    assert args.output is None


def test_thumbnail_output_dash_means_stdout():
    """``-o -`` is the explicit stdout sentinel and parses verbatim as ``"-"``;
    the handler writes raw bytes to stdout for it (no path line)."""
    parser = _build_parser()
    args = parser.parse_args(["world", "thumbnail", "resdb:///abc", "-o", "-"])
    assert args.output == "-"


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


# Known thumbnail payload returned by the recording fake's FetchThumbnail.
# A non-trivial byte sequence (incl. a NUL) so a "bytes go to stdout verbatim"
# assertion proves the raw bytes — not a text re-encoding — reached the buffer.
_THUMB_BYTES = b"\x89PNG\r\n\x00fake-webp-bytes"
_THUMB_CONTENT_TYPE = "image/webp"

# Per-row thumbnail_url values the listing fakes return. The compact view must
# hide these; --wide must surface them.
_SESSION_THUMB_URLS = (
    "resdb:///session-thumb-0",
    "resdb:///session-thumb-1",
    "resdb:///session-thumb-2",
)
_RECORD_THUMB_URLS = (
    "resdb:///record-thumb-0",
    "resdb:///record-thumb-1",
    "resdb:///record-thumb-2",
)


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
        self.fetch_thumbnail_requests: list[FetchThumbnailRequest] = []

    async def list_sessions(self, message: ListSessionsRequest) -> ListSessionsResponse:
        self.list_sessions_requests.append(message)
        # Return 3 rows (each with a thumbnail_url) so the output tests can
        # exercise compact vs --wide columns and the --limit truncation footer.
        sessions = [
            WorldSession(
                session_id=f"S-{i + 1}",
                name=f"Hub{i + 1}",
                host_username="alice",
                active_users=4,
                access_level="Anyone",
                thumbnail_url=_SESSION_THUMB_URLS[i],
            )
            for i in range(3)
        ]
        return ListSessionsResponse(
            sessions=sessions,
            total_count=len(sessions),
            page=message.page,
            page_size=message.page_size,
        )

    async def list_records(self, message: ListRecordsRequest) -> ListRecordsResponse:
        self.list_records_requests.append(message)
        # Return 3 rows (each with a thumbnail_url) — see list_sessions.
        records = [
            WorldRecord(
                record_id=f"R-{i + 1}",
                owner_id="U-me",
                name=f"MyWorld{i + 1}",
                record_url=f"resrec:///U-me/R-{i + 1}",
                thumbnail_url=_RECORD_THUMB_URLS[i],
            )
            for i in range(3)
        ]
        return ListRecordsResponse(
            records=records,
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

    async def fetch_thumbnail(
        self, message: FetchThumbnailRequest
    ) -> FetchThumbnailResponse:
        self.fetch_thumbnail_requests.append(message)
        return FetchThumbnailResponse(
            data=_THUMB_BYTES, content_type=_THUMB_CONTENT_TYPE
        )


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


async def test_records_dispatch_maps_search_into_list_records_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """``records --search avatar`` forwards the free-text query onto the wire
    as ``ListRecordsRequest.search`` (the mod-side refine applies it)."""
    socket_path = tmp_path / "rio-world.sock"
    fake = _RecordingWorld()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        rc = await _run_world(
            ["world", "records", "--search", "avatar"],
            socket_path,
            monkeypatch,
        )
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    assert len(fake.list_records_requests) == 1
    assert fake.list_records_requests[0].search == "avatar"


async def test_records_sort_random_dispatch_uses_random_sort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """``records --sort random`` carries the RANDOM sort enum — the replacement
    for the removed ``world random`` subcommand."""
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
                "public",
                "--sort",
                "random",
                "--count",
                "5",
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
    assert req.sort == RecordSort.RANDOM
    assert req.source == RecordSource.PUBLIC
    assert req.count == 5


# ---------------------------------------------------------------------------
# Output shaping: compact vs --wide columns, --limit truncation footer.
# ---------------------------------------------------------------------------


async def test_sessions_compact_output_omits_thumbnail_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """Default (compact) sessions output shows session_id but never the
    thumbnail_url column."""
    socket_path = tmp_path / "rio-world.sock"
    fake = _RecordingWorld()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        rc = await _run_world(["world", "sessions"], socket_path, monkeypatch)
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    out = capsys.readouterr().out
    assert "session_id" in out
    for url in _SESSION_THUMB_URLS:
        assert url not in out


async def test_sessions_wide_output_includes_thumbnail_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    socket_path = tmp_path / "rio-world.sock"
    fake = _RecordingWorld()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        rc = await _run_world(["world", "sessions", "--wide"], socket_path, monkeypatch)
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    out = capsys.readouterr().out
    for url in _SESSION_THUMB_URLS:
        assert url in out


async def test_records_compact_output_omits_thumbnail_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    socket_path = tmp_path / "rio-world.sock"
    fake = _RecordingWorld()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        rc = await _run_world(["world", "records"], socket_path, monkeypatch)
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    out = capsys.readouterr().out
    assert "record_id" in out
    for url in _RECORD_THUMB_URLS:
        assert url not in out


async def test_records_wide_output_includes_thumbnail_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    socket_path = tmp_path / "rio-world.sock"
    fake = _RecordingWorld()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        rc = await _run_world(["world", "records", "--wide"], socket_path, monkeypatch)
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    out = capsys.readouterr().out
    for url in _RECORD_THUMB_URLS:
        assert url in out


async def test_sessions_limit_truncates_rows_and_prints_footer_to_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """With 3 rows and ``--limit 2`` only 2 data rows print; a ``showing 2 of
    3`` footer goes to STDERR (not STDOUT)."""
    socket_path = tmp_path / "rio-world.sock"
    fake = _RecordingWorld()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        rc = await _run_world(
            ["world", "sessions", "--limit", "2"], socket_path, monkeypatch
        )
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    captured = capsys.readouterr()
    # Only the first two session ids appear as data rows; the third is dropped.
    assert "S-1" in captured.out
    assert "S-2" in captured.out
    assert "S-3" not in captured.out
    # Truncation footer goes to STDERR and names the shown/total counts.
    assert "showing 2 of 3" in captured.err
    assert "showing" not in captured.out


async def test_sessions_all_prints_every_row_without_footer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """``--all`` disables the cap: all 3 rows print and no truncation footer is
    emitted, even though the row count exceeds the default limit logic."""
    socket_path = tmp_path / "rio-world.sock"
    fake = _RecordingWorld()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        rc = await _run_world(
            ["world", "sessions", "--limit", "2", "--all"], socket_path, monkeypatch
        )
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    captured = capsys.readouterr()
    assert "S-1" in captured.out
    assert "S-2" in captured.out
    assert "S-3" in captured.out
    assert "showing" not in captured.err


async def test_records_limit_truncates_rows_and_prints_footer_to_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    socket_path = tmp_path / "rio-world.sock"
    fake = _RecordingWorld()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        rc = await _run_world(
            ["world", "records", "--limit", "2"], socket_path, monkeypatch
        )
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    captured = capsys.readouterr()
    assert "R-1" in captured.out
    assert "R-2" in captured.out
    assert "R-3" not in captured.out
    assert "showing 2 of 3" in captured.err
    assert "showing" not in captured.out


# ---------------------------------------------------------------------------
# world thumbnail: fetch_thumbnail dispatch + byte sink (file vs stdout).
# ---------------------------------------------------------------------------


async def test_thumbnail_with_output_path_writes_file_and_prints_abspath(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """``thumbnail <uri> -o <path>`` fetches the bytes, writes them verbatim to
    the file, and prints the saved file's **absolute path** as one line to
    STDOUT (replacing the old stderr ``saved ...

    -> path`` log).
    """
    socket_path = tmp_path / "rio-world.sock"
    out_file = tmp_path / "thumb.webp"
    fake = _RecordingWorld()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        rc = await _run_world(
            ["world", "thumbnail", "resdb:///abc", "-o", str(out_file)],
            socket_path,
            monkeypatch,
        )
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    # The exact uri reached the wire and the exact bytes hit the file.
    assert len(fake.fetch_thumbnail_requests) == 1
    assert fake.fetch_thumbnail_requests[0].uri == "resdb:///abc"
    assert out_file.read_bytes() == _THUMB_BYTES

    captured = capsys.readouterr()
    # The absolute path is the sole stdout line; no stderr "saved" log remains.
    assert captured.out.strip() == str(out_file.resolve())
    assert captured.out.count("\n") == 1
    assert "saved" not in captured.err


async def test_thumbnail_output_dash_writes_raw_bytes_to_stdout_no_path_line(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsysbinary: pytest.CaptureFixture[bytes],
):
    """``-o -`` is the explicit stdout sentinel: the raw image bytes are
    written to the stdout buffer verbatim (binary-safe) and **no** path line is
    printed, so the output can be piped to a file."""
    socket_path = tmp_path / "rio-world.sock"
    fake = _RecordingWorld()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        rc = await _run_world(
            ["world", "thumbnail", "resdb:///abc", "-o", "-"], socket_path, monkeypatch
        )
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    assert len(fake.fetch_thumbnail_requests) == 1
    out = capsysbinary.readouterr().out
    # Exactly the raw bytes — no trailing newline / abs-path line appended.
    assert out == _THUMB_BYTES


async def test_thumbnail_omitted_output_saves_dated_file_in_cwd_and_prints_abspath(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """With ``-o`` omitted the thumbnail is saved to the CWD as
    ``thumbnail_YYYYMMDD_HHMMSS.<ext>`` (extension derived from the fetched
    ``content_type``: ``image/webp`` -> ``webp``), and the saved file's
    **absolute path** is printed as the sole stdout line."""
    socket_path = tmp_path / "rio-world.sock"
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    fake = _RecordingWorld()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        rc = await _run_world(
            ["world", "thumbnail", "resdb:///abc"], socket_path, monkeypatch
        )
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    assert len(fake.fetch_thumbnail_requests) == 1
    # Exactly one date-stamped file landed in the CWD with the webp extension.
    saved = list(cwd.iterdir())
    assert len(saved) == 1
    created = saved[0]
    assert re.fullmatch(r"thumbnail_\d{8}_\d{6}\.webp", created.name)
    assert created.read_bytes() == _THUMB_BYTES

    captured = capsys.readouterr()
    # The absolute path of the created file is the sole stdout line.
    assert captured.out.strip() == str(created.resolve())
    assert captured.out.count("\n") == 1


class _ContentTypeWorld(WorldBase):
    """World server whose ``fetch_thumbnail`` returns a configurable
    ``content_type`` so the omitted-``-o`` extension mapping can be pinned."""

    def __init__(self, content_type: str) -> None:
        self._content_type = content_type

    async def fetch_thumbnail(
        self, message: FetchThumbnailRequest
    ) -> FetchThumbnailResponse:
        return FetchThumbnailResponse(
            data=_THUMB_BYTES, content_type=self._content_type
        )


async def _run_thumbnail_omitted_ext(
    content_type: str,
    cwd: Path,
    socket_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> str:
    """Drive ``thumbnail <uri>`` (no ``-o``) against a server returning
    ``content_type`` and return the created filename's extension."""
    monkeypatch.chdir(cwd)
    server = Server([_ContentTypeWorld(content_type)])
    await server.start(path=str(socket_path))
    try:
        rc = await _run_world(
            ["world", "thumbnail", "resdb:///abc"], socket_path, monkeypatch
        )
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()
    saved = list(cwd.iterdir())
    assert len(saved) == 1
    return saved[0].suffix.lstrip(".")


async def test_thumbnail_omitted_output_png_content_type_uses_png_ext(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    ext = await _run_thumbnail_omitted_ext(
        "image/png", cwd, tmp_path / "rio-world.sock", monkeypatch
    )
    assert ext == "png"


async def test_thumbnail_omitted_output_jpeg_content_type_uses_jpg_ext(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    ext = await _run_thumbnail_omitted_ext(
        "image/jpeg", cwd, tmp_path / "rio-world.sock", monkeypatch
    )
    assert ext == "jpg"


async def test_thumbnail_omitted_output_unknown_content_type_uses_bin_ext(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """An unrecognized ``content_type`` falls back to the ``bin`` extension."""
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    ext = await _run_thumbnail_omitted_ext(
        "application/octet-stream", cwd, tmp_path / "rio-world.sock", monkeypatch
    )
    assert ext == "bin"


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


# ===========================================================================
# --format json: structured leaves emit one JSON document on STDOUT.
#
# The binary 'thumbnail' leaf has NO --format; only the structured leaves
# (sessions / records / list / join / start / focus / leave / current) do.
# json mode always emits every row and every proto field with no truncation
# and no footer — the --wide/--limit/--all flags are HUMAN-ONLY.
# ===========================================================================

# The full snake_case proto field-name sets. json mode must emit every field
# (a regression guard against Message.to_dict() camelCasing / dropping
# defaults). Derived from the proto contract, not from CLI internals.
_OPEN_WORLD_FIELDS = {f.name for f in dataclasses.fields(OpenWorld)}
_SESSION_FIELDS = {f.name for f in dataclasses.fields(WorldSession)}
_RECORD_FIELDS = {f.name for f in dataclasses.fields(WorldRecord)}


def _sole_json_document(stdout: str) -> object:
    """Parse ``stdout`` as exactly one JSON document, asserting it is the only
    thing written (one trailing newline, no extra trailing content)."""
    assert stdout.endswith("\n")
    body = stdout[:-1]
    # A single json.dumps document never contains a bare top-level newline gap
    # between two documents; json.loads of the whole buffer must succeed once.
    return json.loads(body)


async def test_sessions_json_emits_array_of_full_session_objects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """``--format json`` on sessions emits a JSON array of the full proto
    messages: every row, every snake_case field, no footer."""
    socket_path = tmp_path / "rio-world.sock"
    fake = _RecordingWorld()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        rc = await _run_world(
            ["world", "sessions", "--format", "json"], socket_path, monkeypatch
        )
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    captured = capsys.readouterr()
    payload = _sole_json_document(captured.out)
    assert isinstance(payload, list)
    # All 3 fake rows present (no truncation in json mode).
    assert len(payload) == 3
    for i, row in enumerate(payload):
        assert isinstance(row, dict)
        # Every proto field name is present (snake_case, no camelCase drift).
        assert set(row.keys()) == _SESSION_FIELDS
        assert row["session_id"] == f"S-{i + 1}"
        assert row["name"] == f"Hub{i + 1}"
        assert row["host_username"] == "alice"
        assert row["active_users"] == 4
        # thumbnail_url is included in json even though compact human hides it.
        assert row["thumbnail_url"] == _SESSION_THUMB_URLS[i]
    # No footer text leaked anywhere in json mode.
    assert "showing" not in captured.out
    assert "showing" not in captured.err


async def test_sessions_json_ignores_wide_limit_all_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """The ``--wide`` / ``--limit`` / ``--all`` flags are human-only: json mode
    emits every row and every field regardless, with no truncation footer."""
    socket_path = tmp_path / "rio-world.sock"
    fake = _RecordingWorld()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        rc = await _run_world(
            ["world", "sessions", "--format", "json", "--limit", "1"],
            socket_path,
            monkeypatch,
        )
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    captured = capsys.readouterr()
    payload = _sole_json_document(captured.out)
    assert isinstance(payload, list)
    # --limit 1 would cap human output to 1 row + footer; json keeps all 3.
    assert len(payload) == 3
    assert "showing" not in captured.err


async def test_records_json_emits_array_of_full_record_objects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    socket_path = tmp_path / "rio-world.sock"
    fake = _RecordingWorld()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        rc = await _run_world(
            ["world", "records", "--format", "json"], socket_path, monkeypatch
        )
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    captured = capsys.readouterr()
    payload = _sole_json_document(captured.out)
    assert isinstance(payload, list)
    assert len(payload) == 3
    for i, row in enumerate(payload):
        assert isinstance(row, dict)
        assert set(row.keys()) == _RECORD_FIELDS
        assert row["record_id"] == f"R-{i + 1}"
        assert row["owner_id"] == "U-me"
        assert row["thumbnail_url"] == _RECORD_THUMB_URLS[i]
    assert "showing" not in captured.err


async def test_list_json_emits_array_of_open_world_objects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    socket_path = tmp_path / "rio-world.sock"
    fake = _RecordingWorld()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        rc = await _run_world(
            ["world", "list", "--format", "json"], socket_path, monkeypatch
        )
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    payload = _sole_json_document(capsys.readouterr().out)
    assert payload == [
        {
            "handle": 2,
            "session_id": "S-1",
            "name": "Open",
            "focused": True,
            "user_count": 2,
            "access_level": "Anyone",
        }
    ]


async def test_join_json_emits_single_open_world_object(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """``join --format json`` emits a single OpenWorld **object** (not an
    array): all 6 fields, snake_case."""
    socket_path = tmp_path / "rio-world.sock"
    fake = _RecordingWorld()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        rc = await _run_world(
            ["world", "join", "--session-id", "S-42", "--format", "json"],
            socket_path,
            monkeypatch,
        )
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    payload = _sole_json_document(capsys.readouterr().out)
    assert isinstance(payload, dict)
    assert set(payload.keys()) == _OPEN_WORLD_FIELDS
    assert payload["name"] == "Joined"


async def test_start_json_emits_single_open_world_object(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    socket_path = tmp_path / "rio-world.sock"
    fake = _RecordingWorld()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        rc = await _run_world(
            ["world", "start", "--record-id", "R-9", "--format", "json"],
            socket_path,
            monkeypatch,
        )
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    payload = _sole_json_document(capsys.readouterr().out)
    assert isinstance(payload, dict)
    assert set(payload.keys()) == _OPEN_WORLD_FIELDS
    assert payload["name"] == "Started"


async def test_focus_json_emits_single_open_world_object(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    socket_path = tmp_path / "rio-world.sock"
    fake = _RecordingWorld()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        rc = await _run_world(
            ["world", "focus", "5", "--format", "json"], socket_path, monkeypatch
        )
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    payload = _sole_json_document(capsys.readouterr().out)
    assert isinstance(payload, dict)
    assert set(payload.keys()) == _OPEN_WORLD_FIELDS
    assert payload["handle"] == 5
    assert payload["name"] == "Focused"


async def test_leave_json_emits_handle_and_left_true(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """``leave --format json`` emits ``{handle: <requested handle>, left:

    true}`` — a synthesized acknowledgement (the wire LeaveResponse is
    empty).
    """
    socket_path = tmp_path / "rio-world.sock"
    fake = _RecordingWorld()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        rc = await _run_world(
            ["world", "leave", "8", "--format", "json"], socket_path, monkeypatch
        )
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    payload = _sole_json_document(capsys.readouterr().out)
    assert payload == {"handle": 8, "left": True}


async def test_current_json_focused_emits_single_open_world_object(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """``current --format json`` with a focused world emits a single OpenWorld
    object."""
    socket_path = tmp_path / "rio-world.sock"
    fake = _RecordingWorld()
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        rc = await _run_world(
            ["world", "current", "--format", "json"], socket_path, monkeypatch
        )
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    payload = _sole_json_document(capsys.readouterr().out)
    assert isinstance(payload, dict)
    assert set(payload.keys()) == _OPEN_WORLD_FIELDS
    assert payload["name"] == "Current"


class _UserspaceWorld(WorldBase):
    """World server reporting userspace (no focused world) for
    ``get_current``."""

    async def get_current(self, message: GetCurrentRequest) -> GetCurrentResponse:
        return GetCurrentResponse(has_world=False)


async def test_current_json_userspace_emits_null_document_with_rc_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """In userspace (no focused world), ``current --format json`` emits a JSON
    ``null`` document and returns rc 0; the human stderr guidance does NOT
    print in json mode."""
    socket_path = tmp_path / "rio-world.sock"
    server = Server([_UserspaceWorld()])
    await server.start(path=str(socket_path))
    try:
        rc = await _run_world(
            ["world", "current", "--format", "json"], socket_path, monkeypatch
        )
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    captured = capsys.readouterr()
    payload = _sole_json_document(captured.out)
    assert payload is None
    # The human-only "userspace" stderr guidance must be suppressed in json.
    assert captured.err == ""


async def test_sessions_json_preserves_non_ascii_world_name_verbatim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """``ensure_ascii=False``: a Japanese session name survives json round-trip
    literally (not ``\\uXXXX`` escaped) and parses back to the same string."""
    socket_path = tmp_path / "rio-world.sock"

    class _JapaneseWorld(WorldBase):
        async def list_sessions(
            self, message: ListSessionsRequest
        ) -> ListSessionsResponse:
            return ListSessionsResponse(
                sessions=[WorldSession(session_id="S-1", name="ホームワールド")],
                total_count=1,
            )

    server = Server([_JapaneseWorld()])
    await server.start(path=str(socket_path))
    try:
        rc = await _run_world(
            ["world", "sessions", "--format", "json"], socket_path, monkeypatch
        )
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    out = capsys.readouterr().out
    # The literal (unescaped) glyphs appear in the raw stdout text...
    assert "ホームワールド" in out
    assert "\\u" not in out
    # ...and the parsed value is the exact same string.
    payload = _sole_json_document(out)
    assert isinstance(payload, list)
    assert payload[0]["name"] == "ホームワールド"


async def test_records_json_round_trips_large_unix_nanos_exactly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """A ``last_modification_unix_nanos`` ~1.7e18 (> 2**53) round-trips through
    json exactly — no lossy float coercion."""
    large_nanos = 1_700_000_000_123_456_789
    socket_path = tmp_path / "rio-world.sock"

    class _NanosWorld(WorldBase):
        async def list_records(
            self, message: ListRecordsRequest
        ) -> ListRecordsResponse:
            return ListRecordsResponse(
                records=[
                    WorldRecord(
                        record_id="R-1",
                        name="W",
                        last_modification_unix_nanos=large_nanos,
                    )
                ],
                has_more=False,
            )

    server = Server([_NanosWorld()])
    await server.start(path=str(socket_path))
    try:
        rc = await _run_world(
            ["world", "records", "--format", "json"], socket_path, monkeypatch
        )
        assert rc == 0
    finally:
        server.close()
        await server.wait_closed()

    payload = _sole_json_document(capsys.readouterr().out)
    assert isinstance(payload, list)
    assert payload[0]["last_modification_unix_nanos"] == large_nanos
