"""World client tests — real grpclib round-trip over a tmp_path UDS.

A real ``grpclib.server.Server`` is started on a real Unix Domain Socket with
an in-process fake ``WorldBase`` servicer; ``WorldClient`` is pointed at it via
``RESONITE_IO_SOCKET``. These tests assert two contracts of ``WorldClient``:

  1. wire response  -> public dataclass mapping (tuples for repeated fields,
     unix-nanos ints, ``OpenWorld`` unwrapping, ``has_world`` handling), and
  2. public request args -> wire request mapping, especially the public-enum to
     wire-enum translation (e.g. public ``SessionFilter.ALL`` is sent as wire
     ``SessionFilter.UNSPECIFIED``).

Per testing-strategy: no mocking of grpclib / asyncio / betterproto internals —
the only fake is the self-owned ``WorldBase`` servicer surface.
"""

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
    OpenWorld as WireOpenWorld,
    RecordSort as WireRecordSort,
    RecordSortDirection as WireRecordSortDirection,
    RecordSource as WireRecordSource,
    SessionFilter as WireSessionFilter,
    StartWorldRequest,
    StartWorldResponse,
    WorldBase,
    WorldRecord as WireWorldRecord,
    WorldSession as WireWorldSession,
)
from resoio.world import (
    OpenWorld,
    RecordPage,
    RecordSort,
    RecordSortDirection,
    RecordSource,
    SessionFilter,
    SessionPage,
    Thumbnail,
    WorldClient,
    WorldRecord,
    WorldSession,
)


class _FakeWorld(WorldBase):
    """In-process fake servicer.

    Records every request it receives so the test can assert the wire
    request the client built, and returns canned responses configured
    per-test.
    """

    def __init__(
        self,
        *,
        sessions_response: ListSessionsResponse | None = None,
        records_response: ListRecordsResponse | None = None,
        join_world: WireOpenWorld | None = None,
        start_world_world: WireOpenWorld | None = None,
        open_worlds: list[WireOpenWorld] | None = None,
        focus_world: WireOpenWorld | None = None,
        current_response: GetCurrentResponse | None = None,
        thumbnail_response: FetchThumbnailResponse | None = None,
    ) -> None:
        self.sessions_requests: list[ListSessionsRequest] = []
        self.records_requests: list[ListRecordsRequest] = []
        self.join_requests: list[JoinRequest] = []
        self.start_world_requests: list[StartWorldRequest] = []
        self.list_open_worlds_requests: list[ListOpenWorldsRequest] = []
        self.focus_requests: list[FocusRequest] = []
        self.leave_requests: list[LeaveRequest] = []
        self.get_current_requests: list[GetCurrentRequest] = []
        self.fetch_thumbnail_requests: list[FetchThumbnailRequest] = []

        self._sessions_response = sessions_response or ListSessionsResponse()
        self._records_response = records_response or ListRecordsResponse()
        self._join_world = join_world
        self._start_world_world = start_world_world
        self._open_worlds = open_worlds or []
        self._focus_world = focus_world
        self._current_response = current_response or GetCurrentResponse()
        self._thumbnail_response = thumbnail_response or FetchThumbnailResponse()

    async def list_sessions(self, message: ListSessionsRequest) -> ListSessionsResponse:
        self.sessions_requests.append(message)
        return self._sessions_response

    async def list_records(self, message: ListRecordsRequest) -> ListRecordsResponse:
        self.records_requests.append(message)
        return self._records_response

    async def join(self, message: JoinRequest) -> JoinResponse:
        self.join_requests.append(message)
        return JoinResponse(world=self._join_world)

    async def start_world(self, message: StartWorldRequest) -> StartWorldResponse:
        self.start_world_requests.append(message)
        return StartWorldResponse(world=self._start_world_world)

    async def list_open_worlds(
        self, message: ListOpenWorldsRequest
    ) -> ListOpenWorldsResponse:
        self.list_open_worlds_requests.append(message)
        return ListOpenWorldsResponse(worlds=list(self._open_worlds))

    async def focus(self, message: FocusRequest) -> FocusResponse:
        self.focus_requests.append(message)
        return FocusResponse(world=self._focus_world)

    async def leave(self, message: LeaveRequest) -> LeaveResponse:
        self.leave_requests.append(message)
        return LeaveResponse()

    async def get_current(self, message: GetCurrentRequest) -> GetCurrentResponse:
        self.get_current_requests.append(message)
        return self._current_response

    async def fetch_thumbnail(
        self, message: FetchThumbnailRequest
    ) -> FetchThumbnailResponse:
        self.fetch_thumbnail_requests.append(message)
        return self._thumbnail_response


async def _serve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake: _FakeWorld
) -> tuple[Server, str]:
    socket_path = tmp_path / "rio-world.sock"
    server = Server([fake])
    await server.start(path=str(socket_path))
    monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
    return server, str(socket_path)


class TestListSessions:
    async def test_maps_response_into_session_page_with_tuple_fields(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        wire_session = WireWorldSession(
            session_id="S-MyriaPolyworld",
            name="Myria",
            description="a busy session",
            host_user_id="U-host",
            host_username="Host",
            session_urls=["lnl-nat://abc/1", "lnl-nat://abc/2"],
            thumbnail_url="https://thumb/1.webp",
            joined_users=7,
            active_users=5,
            maximum_users=24,
            tags=["game", "social"],
            access_level="Anyone",
            headless_host=True,
            mobile_friendly=False,
            corresponding_world_id="R-world",
            universe_id="universe-7",
            session_begin_unix_nanos=1_700_000_000_000_000_000,
            last_update_unix_nanos=1_700_000_500_000_000_000,
        )
        fake = _FakeWorld(
            sessions_response=ListSessionsResponse(
                sessions=[wire_session],
                total_count=42,
                page=2,
                page_size=10,
            )
        )
        server, _ = await _serve(tmp_path, monkeypatch, fake)
        try:
            async with WorldClient() as client:
                page = await client.list_sessions()
        finally:
            server.close()
            await server.wait_closed()

        assert isinstance(page, SessionPage)
        assert page.total_count == 42
        assert page.page == 2
        assert page.page_size == 10
        assert isinstance(page.sessions, tuple)
        assert len(page.sessions) == 1

        got = page.sessions[0]
        assert got == WorldSession(
            session_id="S-MyriaPolyworld",
            name="Myria",
            description="a busy session",
            host_user_id="U-host",
            host_username="Host",
            session_urls=("lnl-nat://abc/1", "lnl-nat://abc/2"),
            thumbnail_url="https://thumb/1.webp",
            joined_users=7,
            active_users=5,
            maximum_users=24,
            tags=("game", "social"),
            access_level="Anyone",
            headless_host=True,
            mobile_friendly=False,
            corresponding_world_id="R-world",
            universe_id="universe-7",
            session_begin_unix_nanos=1_700_000_000_000_000_000,
            last_update_unix_nanos=1_700_000_500_000_000_000,
        )
        # Repeated fields must surface as tuples (frozen/hashable dataclass).
        assert isinstance(got.session_urls, tuple)
        assert isinstance(got.tags, tuple)

    async def test_request_carries_search_and_paging_with_all_filter_as_unspecified(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        fake = _FakeWorld()
        server, _ = await _serve(tmp_path, monkeypatch, fake)
        try:
            async with WorldClient() as client:
                await client.list_sessions(
                    search="hub",
                    filter=SessionFilter.ALL,
                    min_active_users=3,
                    page=4,
                    page_size=20,
                )
        finally:
            server.close()
            await server.wait_closed()

        assert len(fake.sessions_requests) == 1
        wire = fake.sessions_requests[0]
        assert wire.search == "hub"
        assert wire.min_active_users == 3
        assert wire.page == 4
        assert wire.page_size == 20
        # Public ALL is the "no filter" tab; it must travel as wire UNSPECIFIED,
        # NOT collide with FRIENDS/HEADLESS (which share numeric 1/2 publicly).
        assert wire.filter == WireSessionFilter.UNSPECIFIED

    async def test_request_maps_friends_filter(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        fake = _FakeWorld()
        server, _ = await _serve(tmp_path, monkeypatch, fake)
        try:
            async with WorldClient() as client:
                await client.list_sessions(filter=SessionFilter.FRIENDS)
        finally:
            server.close()
            await server.wait_closed()

        assert fake.sessions_requests[0].filter == WireSessionFilter.FRIENDS

    async def test_request_maps_headless_filter(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        fake = _FakeWorld()
        server, _ = await _serve(tmp_path, monkeypatch, fake)
        try:
            async with WorldClient() as client:
                await client.list_sessions(filter=SessionFilter.HEADLESS)
        finally:
            server.close()
            await server.wait_closed()

        assert fake.sessions_requests[0].filter == WireSessionFilter.HEADLESS

    async def test_raises_when_not_connected(self):
        client = WorldClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.list_sessions()


class TestListRecords:
    async def test_maps_response_into_record_page_with_tuple_fields(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        wire_record = WireWorldRecord(
            record_id="R-template",
            owner_id="U-owner",
            name="Template World",
            description="starter",
            thumbnail_url="https://thumb/r.webp",
            tags=["template", "starter"],
            record_url="resrec:///U-owner/R-template",
            last_modification_unix_nanos=1_699_000_000_000_000_000,
        )
        fake = _FakeWorld(
            records_response=ListRecordsResponse(
                records=[wire_record],
                has_more=True,
                offset=60,
            )
        )
        server, _ = await _serve(tmp_path, monkeypatch, fake)
        try:
            async with WorldClient() as client:
                page = await client.list_records()
        finally:
            server.close()
            await server.wait_closed()

        assert isinstance(page, RecordPage)
        assert page.has_more is True
        assert page.offset == 60
        assert isinstance(page.records, tuple)
        assert page.records == (
            WorldRecord(
                record_id="R-template",
                owner_id="U-owner",
                name="Template World",
                description="starter",
                thumbnail_url="https://thumb/r.webp",
                tags=("template", "starter"),
                record_url="resrec:///U-owner/R-template",
                last_modification_unix_nanos=1_699_000_000_000_000_000,
            ),
        )
        assert isinstance(page.records[0].tags, tuple)

    async def test_request_carries_source_tags_owner_offset_and_count(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        fake = _FakeWorld()
        server, _ = await _serve(tmp_path, monkeypatch, fake)
        try:
            async with WorldClient() as client:
                await client.list_records(
                    source=RecordSource.PUBLIC,
                    required_tags=["game", "avatar"],
                    owner_id="U-owner",
                    offset=120,
                    count=30,
                )
        finally:
            server.close()
            await server.wait_closed()

        assert len(fake.records_requests) == 1
        wire = fake.records_requests[0]
        # Public PUBLIC is offset from wire by the UNSPECIFIED=0 slot, so this
        # must NOT rely on numeric equality.
        assert wire.source == WireRecordSource.PUBLIC
        assert list(wire.required_tags) == ["game", "avatar"]
        assert wire.owner_id == "U-owner"
        assert wire.offset == 120
        assert wire.count == 30

    async def test_request_maps_default_sort_and_direction(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        fake = _FakeWorld()
        server, _ = await _serve(tmp_path, monkeypatch, fake)
        try:
            async with WorldClient() as client:
                # Defaults: CREATION_DATE / DESCENDING.
                await client.list_records()
        finally:
            server.close()
            await server.wait_closed()

        wire = fake.records_requests[0]
        assert wire.sort == WireRecordSort.CREATION_DATE
        assert wire.sort_direction == WireRecordSortDirection.DESCENDING

    async def test_request_maps_random_sort_and_ascending_direction(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        fake = _FakeWorld()
        server, _ = await _serve(tmp_path, monkeypatch, fake)
        try:
            async with WorldClient() as client:
                await client.list_records(
                    sort=RecordSort.RANDOM,
                    sort_direction=RecordSortDirection.ASCENDING,
                )
        finally:
            server.close()
            await server.wait_closed()

        wire = fake.records_requests[0]
        # The "random" tab is sort=RANDOM on the wire.
        assert wire.sort == WireRecordSort.RANDOM
        assert wire.sort_direction == WireRecordSortDirection.ASCENDING

    async def test_request_maps_featured_source(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        fake = _FakeWorld()
        server, _ = await _serve(tmp_path, monkeypatch, fake)
        try:
            async with WorldClient() as client:
                await client.list_records(source=RecordSource.FEATURED)
        finally:
            server.close()
            await server.wait_closed()

        assert fake.records_requests[0].source == WireRecordSource.FEATURED

    async def test_request_carries_search_query_verbatim(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        fake = _FakeWorld()
        server, _ = await _serve(tmp_path, monkeypatch, fake)
        try:
            async with WorldClient() as client:
                await client.list_records(search="puzzle +red")
        finally:
            server.close()
            await server.wait_closed()

        assert len(fake.records_requests) == 1
        # The free-text World-tab query must travel to the proto ``search``
        # field unchanged (including the ``+term`` operator syntax).
        assert fake.records_requests[0].search == "puzzle +red"

    async def test_request_defaults_search_to_empty_string(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        fake = _FakeWorld()
        server, _ = await _serve(tmp_path, monkeypatch, fake)
        try:
            async with WorldClient() as client:
                # No search arg: an empty query means "no search" on the wire.
                await client.list_records()
        finally:
            server.close()
            await server.wait_closed()

        assert fake.records_requests[0].search == ""

    async def test_raises_when_not_connected(self):
        client = WorldClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.list_records()


def _open_world() -> WireOpenWorld:
    return WireOpenWorld(
        handle=3,
        session_id="S-joined",
        name="Joined World",
        focused=True,
        user_count=4,
        access_level="Anyone",
    )


class TestJoin:
    async def test_join_by_session_id_returns_open_world(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        fake = _FakeWorld(join_world=_open_world())
        server, _ = await _serve(tmp_path, monkeypatch, fake)
        try:
            async with WorldClient() as client:
                world = await client.join(session_id="S-target")
        finally:
            server.close()
            await server.wait_closed()

        assert world == OpenWorld(
            handle=3,
            session_id="S-joined",
            name="Joined World",
            focused=True,
            user_count=4,
            access_level="Anyone",
        )
        assert len(fake.join_requests) == 1
        wire = fake.join_requests[0]
        assert wire.session_id == "S-target"
        assert wire.session_url == ""
        # Default focus is True.
        assert wire.focus is True

    async def test_join_by_url_lands_in_session_url_field(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        fake = _FakeWorld(join_world=_open_world())
        server, _ = await _serve(tmp_path, monkeypatch, fake)
        try:
            async with WorldClient() as client:
                await client.join(url="lnl-nat://abc/42", focus=False)
        finally:
            server.close()
            await server.wait_closed()

        wire = fake.join_requests[0]
        # The user-facing ``url`` arg must populate the proto ``session_url``
        # field, leaving ``session_id`` empty.
        assert wire.session_url == "lnl-nat://abc/42"
        assert wire.session_id == ""
        assert wire.focus is False

    async def test_join_with_neither_raises_value_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        fake = _FakeWorld(join_world=_open_world())
        server, _ = await _serve(tmp_path, monkeypatch, fake)
        try:
            async with WorldClient() as client:
                with pytest.raises(ValueError):
                    await client.join()
            # The invalid call must never reach the wire.
            assert fake.join_requests == []
        finally:
            server.close()
            await server.wait_closed()

    async def test_join_with_both_raises_value_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        fake = _FakeWorld(join_world=_open_world())
        server, _ = await _serve(tmp_path, monkeypatch, fake)
        try:
            async with WorldClient() as client:
                with pytest.raises(ValueError):
                    await client.join(session_id="S-x", url="lnl-nat://abc/1")
            assert fake.join_requests == []
        finally:
            server.close()
            await server.wait_closed()

    async def test_raises_when_not_connected(self):
        client = WorldClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.join(session_id="S-x")


class TestStartWorld:
    async def test_start_world_returns_open_world_and_carries_request(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        started = WireOpenWorld(
            handle=9,
            session_id="S-new",
            name="Fresh Session",
            focused=False,
            user_count=1,
            access_level="ContactsPlus",
        )
        fake = _FakeWorld(start_world_world=started)
        server, _ = await _serve(tmp_path, monkeypatch, fake)
        try:
            async with WorldClient() as client:
                world = await client.start_world(
                    record_id="R-template", owner_id="U-owner", focus=False
                )
        finally:
            server.close()
            await server.wait_closed()

        assert world == OpenWorld(
            handle=9,
            session_id="S-new",
            name="Fresh Session",
            focused=False,
            user_count=1,
            access_level="ContactsPlus",
        )
        assert len(fake.start_world_requests) == 1
        wire = fake.start_world_requests[0]
        assert wire.record_id == "R-template"
        assert wire.owner_id == "U-owner"
        assert wire.focus is False

    async def test_start_world_defaults_focus_true(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        fake = _FakeWorld(start_world_world=_open_world())
        server, _ = await _serve(tmp_path, monkeypatch, fake)
        try:
            async with WorldClient() as client:
                await client.start_world(record_id="R-template")
        finally:
            server.close()
            await server.wait_closed()

        wire = fake.start_world_requests[0]
        assert wire.owner_id == ""
        assert wire.focus is True

    async def test_raises_when_not_connected(self):
        client = WorldClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.start_world(record_id="R-template")


class TestListOpenWorlds:
    async def test_returns_list_of_open_worlds(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        worlds = [
            WireOpenWorld(
                handle=1,
                session_id="S-a",
                name="A",
                focused=True,
                user_count=2,
                access_level="Anyone",
            ),
            WireOpenWorld(
                handle=2,
                session_id="S-b",
                name="B",
                focused=False,
                user_count=0,
                access_level="Private",
            ),
        ]
        fake = _FakeWorld(open_worlds=worlds)
        server, _ = await _serve(tmp_path, monkeypatch, fake)
        try:
            async with WorldClient() as client:
                result = await client.list_open_worlds()
        finally:
            server.close()
            await server.wait_closed()

        assert result == [
            OpenWorld(
                handle=1,
                session_id="S-a",
                name="A",
                focused=True,
                user_count=2,
                access_level="Anyone",
            ),
            OpenWorld(
                handle=2,
                session_id="S-b",
                name="B",
                focused=False,
                user_count=0,
                access_level="Private",
            ),
        ]
        assert len(fake.list_open_worlds_requests) == 1

    async def test_returns_empty_list_when_no_worlds_open(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        fake = _FakeWorld(open_worlds=[])
        server, _ = await _serve(tmp_path, monkeypatch, fake)
        try:
            async with WorldClient() as client:
                result = await client.list_open_worlds()
        finally:
            server.close()
            await server.wait_closed()

        assert result == []

    async def test_raises_when_not_connected(self):
        client = WorldClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.list_open_worlds()


class TestFocus:
    async def test_focus_sends_handle_and_returns_open_world(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        focused = WireOpenWorld(
            handle=5,
            session_id="S-focused",
            name="Now Focused",
            focused=True,
            user_count=3,
            access_level="Anyone",
        )
        fake = _FakeWorld(focus_world=focused)
        server, _ = await _serve(tmp_path, monkeypatch, fake)
        try:
            async with WorldClient() as client:
                world = await client.focus(5)
        finally:
            server.close()
            await server.wait_closed()

        assert world == OpenWorld(
            handle=5,
            session_id="S-focused",
            name="Now Focused",
            focused=True,
            user_count=3,
            access_level="Anyone",
        )
        assert len(fake.focus_requests) == 1
        assert fake.focus_requests[0].handle == 5

    async def test_raises_when_not_connected(self):
        client = WorldClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.focus(1)


class TestLeave:
    async def test_leave_sends_handle_and_returns_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        fake = _FakeWorld()
        server, _ = await _serve(tmp_path, monkeypatch, fake)
        try:
            async with WorldClient() as client:
                result = await client.leave(7)
        finally:
            server.close()
            await server.wait_closed()

        assert result is None
        assert len(fake.leave_requests) == 1
        assert fake.leave_requests[0].handle == 7

    async def test_raises_when_not_connected(self):
        client = WorldClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.leave(1)


class TestGetCurrent:
    async def test_returns_open_world_when_has_world_true(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        current = WireOpenWorld(
            handle=2,
            session_id="S-current",
            name="Current",
            focused=True,
            user_count=6,
            access_level="Anyone",
        )
        fake = _FakeWorld(
            current_response=GetCurrentResponse(world=current, has_world=True)
        )
        server, _ = await _serve(tmp_path, monkeypatch, fake)
        try:
            async with WorldClient() as client:
                world = await client.get_current()
        finally:
            server.close()
            await server.wait_closed()

        assert world == OpenWorld(
            handle=2,
            session_id="S-current",
            name="Current",
            focused=True,
            user_count=6,
            access_level="Anyone",
        )

    async def test_returns_none_when_has_world_false(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        # Userspace-only: no joinable world is focused, so has_world is False
        # even though the response message technically carries a (default)
        # world. The client must return None, not an empty OpenWorld.
        fake = _FakeWorld(
            current_response=GetCurrentResponse(world=None, has_world=False)
        )
        server, _ = await _serve(tmp_path, monkeypatch, fake)
        try:
            async with WorldClient() as client:
                world = await client.get_current()
        finally:
            server.close()
            await server.wait_closed()

        assert world is None

    async def test_raises_when_not_connected(self):
        client = WorldClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.get_current()


class TestFetchThumbnail:
    async def test_sends_uri_and_returns_thumbnail_with_bytes_and_content_type(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        webp_bytes = b"RIFF\x00\x00\x00\x00WEBPVP8 "
        fake = _FakeWorld(
            thumbnail_response=FetchThumbnailResponse(
                data=webp_bytes,
                content_type="image/webp",
            )
        )
        server, _ = await _serve(tmp_path, monkeypatch, fake)
        try:
            async with WorldClient() as client:
                thumbnail = await client.fetch_thumbnail("resdb:///abc.webp")
        finally:
            server.close()
            await server.wait_closed()

        # The user-facing ``uri`` arg must travel verbatim on the wire.
        assert len(fake.fetch_thumbnail_requests) == 1
        assert fake.fetch_thumbnail_requests[0].uri == "resdb:///abc.webp"

        assert thumbnail == Thumbnail(
            data=webp_bytes,
            content_type="image/webp",
        )

    async def test_allows_empty_content_type_with_returned_bytes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        # The server may not know the MIME type; an empty content_type is a
        # valid response and must surface verbatim (not coerced to a default).
        raw_bytes = b"\x89PNG\r\n\x1a\n"
        fake = _FakeWorld(
            thumbnail_response=FetchThumbnailResponse(
                data=raw_bytes,
                content_type="",
            )
        )
        server, _ = await _serve(tmp_path, monkeypatch, fake)
        try:
            async with WorldClient() as client:
                thumbnail = await client.fetch_thumbnail("resdb:///no-type")
        finally:
            server.close()
            await server.wait_closed()

        assert fake.fetch_thumbnail_requests[0].uri == "resdb:///no-type"
        assert thumbnail == Thumbnail(data=raw_bytes, content_type="")

    async def test_raises_when_not_connected(self):
        client = WorldClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.fetch_thumbnail("resdb:///abc.webp")
