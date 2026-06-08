"""World client tests — real grpclib round-trip over a tmp_path UDS.

A real ``grpclib.server.Server`` is started on a real Unix Domain Socket with
an in-process fake ``WorldBase`` servicer; ``WorldClient`` is pointed at it via
``RESONITE_IO_SOCKET``. These tests assert two contracts of ``WorldClient``:

  1. the methods return the GENERATED proto types directly (the hand-written
     output mirror dataclasses were removed), so repeated fields surface as
     ``list`` and ``join`` / ``start_world`` / ``focus`` unwrap the response's
     single ``OpenWorld`` payload (raising when the server omits it), and
  2. public request args -> wire request mapping, especially the public-enum to
     wire-enum translation (e.g. public ``SessionFilter.ALL`` is sent as wire
     ``SessionFilter.UNSPECIFIED``), asserted on the request the fake captures.

Per testing-strategy: no mocking of grpclib / asyncio / betterproto internals —
the only fake is the self-owned ``WorldBase`` servicer surface. The output
types (``WorldSession`` / ``WorldRecord`` / ``OpenWorld`` and the response
messages) are the generated proto types, re-exported from ``resoio.world``;
field values are asserted via their generated field names.
"""

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

import pytest

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
    RecordSort as WireRecordSort,
    RecordSortDirection as WireRecordSortDirection,
    RecordSource as WireRecordSource,
    SessionFilter as WireSessionFilter,
    StartWorldRequest,
    StartWorldResponse,
    WorldBase,
)
from resoio.world import (
    OpenWorld,
    RecordSort,
    RecordSortDirection,
    RecordSource,
    SessionFilter,
    WorldClient,
    WorldRecord,
    WorldSession,
)

if TYPE_CHECKING:
    from grpclib._typing import IServable

UdsServer = Callable[["IServable"], Awaitable[str]]


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
        join_world: OpenWorld | None = None,
        start_world_world: OpenWorld | None = None,
        open_worlds: list[OpenWorld] | None = None,
        focus_world: OpenWorld | None = None,
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


class TestListSessions:
    async def test_returns_generated_response_with_list_fields(
        self, uds_server: UdsServer
    ):
        wire_session = WorldSession(
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
        await uds_server(fake)
        async with WorldClient() as client:
            response = await client.list_sessions()

        # The method returns the generated ListSessionsResponse directly.
        assert isinstance(response, ListSessionsResponse)
        assert response.total_count == 42
        assert response.page == 2
        assert response.page_size == 10
        # Repeated fields surface as list (generated proto type), not tuple.
        assert isinstance(response.sessions, list)
        assert len(response.sessions) == 1

        got = response.sessions[0]
        assert isinstance(got, WorldSession)
        assert got.session_id == "S-MyriaPolyworld"
        assert got.name == "Myria"
        assert got.description == "a busy session"
        assert got.host_user_id == "U-host"
        assert got.host_username == "Host"
        assert got.session_urls == ["lnl-nat://abc/1", "lnl-nat://abc/2"]
        assert got.thumbnail_url == "https://thumb/1.webp"
        assert got.joined_users == 7
        assert got.active_users == 5
        assert got.maximum_users == 24
        assert got.tags == ["game", "social"]
        assert got.access_level == "Anyone"
        assert got.headless_host is True
        assert got.mobile_friendly is False
        assert got.corresponding_world_id == "R-world"
        assert got.universe_id == "universe-7"
        assert got.session_begin_unix_nanos == 1_700_000_000_000_000_000
        assert got.last_update_unix_nanos == 1_700_000_500_000_000_000

    async def test_request_carries_search_and_paging_with_all_filter_as_unspecified(
        self, uds_server: UdsServer
    ):
        fake = _FakeWorld()
        await uds_server(fake)
        async with WorldClient() as client:
            await client.list_sessions(
                search="hub",
                filter=SessionFilter.ALL,
                min_active_users=3,
                page=4,
                page_size=20,
            )

        assert len(fake.sessions_requests) == 1
        wire = fake.sessions_requests[0]
        assert wire.search == "hub"
        assert wire.min_active_users == 3
        assert wire.page == 4
        assert wire.page_size == 20
        # Public ALL is the "no filter" tab; it must travel as wire UNSPECIFIED,
        # NOT collide with FRIENDS/HEADLESS (which share numeric 1/2 publicly).
        assert wire.filter == WireSessionFilter.UNSPECIFIED

    async def test_request_maps_friends_filter(self, uds_server: UdsServer):
        fake = _FakeWorld()
        await uds_server(fake)
        async with WorldClient() as client:
            await client.list_sessions(filter=SessionFilter.FRIENDS)

        assert fake.sessions_requests[0].filter == WireSessionFilter.FRIENDS

    async def test_request_maps_headless_filter(self, uds_server: UdsServer):
        fake = _FakeWorld()
        await uds_server(fake)
        async with WorldClient() as client:
            await client.list_sessions(filter=SessionFilter.HEADLESS)

        assert fake.sessions_requests[0].filter == WireSessionFilter.HEADLESS

    async def test_raises_when_not_connected(self):
        client = WorldClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.list_sessions()


class TestListRecords:
    async def test_returns_generated_response_with_list_fields(
        self, uds_server: UdsServer
    ):
        wire_record = WorldRecord(
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
        await uds_server(fake)
        async with WorldClient() as client:
            response = await client.list_records()

        assert isinstance(response, ListRecordsResponse)
        assert response.has_more is True
        assert response.offset == 60
        # Repeated fields surface as list (generated proto type), not tuple.
        assert isinstance(response.records, list)
        assert len(response.records) == 1

        got = response.records[0]
        assert isinstance(got, WorldRecord)
        assert got.record_id == "R-template"
        assert got.owner_id == "U-owner"
        assert got.name == "Template World"
        assert got.description == "starter"
        assert got.thumbnail_url == "https://thumb/r.webp"
        assert got.tags == ["template", "starter"]
        assert got.record_url == "resrec:///U-owner/R-template"
        assert got.last_modification_unix_nanos == 1_699_000_000_000_000_000

    async def test_request_carries_source_tags_owner_offset_and_count(
        self, uds_server: UdsServer
    ):
        fake = _FakeWorld()
        await uds_server(fake)
        async with WorldClient() as client:
            await client.list_records(
                source=RecordSource.PUBLIC,
                required_tags=["game", "avatar"],
                owner_id="U-owner",
                offset=120,
                count=30,
            )

        assert len(fake.records_requests) == 1
        wire = fake.records_requests[0]
        # Public PUBLIC is offset from wire by the UNSPECIFIED=0 slot, so this
        # must NOT rely on numeric equality.
        assert wire.source == WireRecordSource.PUBLIC
        assert list(wire.required_tags) == ["game", "avatar"]
        assert wire.owner_id == "U-owner"
        assert wire.offset == 120
        assert wire.count == 30

    async def test_request_maps_default_sort_and_direction(self, uds_server: UdsServer):
        fake = _FakeWorld()
        await uds_server(fake)
        async with WorldClient() as client:
            # Defaults: CREATION_DATE / DESCENDING.
            await client.list_records()

        wire = fake.records_requests[0]
        assert wire.sort == WireRecordSort.CREATION_DATE
        assert wire.sort_direction == WireRecordSortDirection.DESCENDING

    async def test_request_maps_random_sort_and_ascending_direction(
        self, uds_server: UdsServer
    ):
        fake = _FakeWorld()
        await uds_server(fake)
        async with WorldClient() as client:
            await client.list_records(
                sort=RecordSort.RANDOM,
                sort_direction=RecordSortDirection.ASCENDING,
            )

        wire = fake.records_requests[0]
        # The "random" tab is sort=RANDOM on the wire.
        assert wire.sort == WireRecordSort.RANDOM
        assert wire.sort_direction == WireRecordSortDirection.ASCENDING

    async def test_request_maps_featured_source(self, uds_server: UdsServer):
        fake = _FakeWorld()
        await uds_server(fake)
        async with WorldClient() as client:
            await client.list_records(source=RecordSource.FEATURED)

        assert fake.records_requests[0].source == WireRecordSource.FEATURED

    async def test_request_carries_search_query_verbatim(self, uds_server: UdsServer):
        fake = _FakeWorld()
        await uds_server(fake)
        async with WorldClient() as client:
            await client.list_records(search="puzzle +red")

        assert len(fake.records_requests) == 1
        # The free-text World-tab query must travel to the proto ``search``
        # field unchanged (including the ``+term`` operator syntax).
        assert fake.records_requests[0].search == "puzzle +red"

    async def test_request_defaults_search_to_empty_string(self, uds_server: UdsServer):
        fake = _FakeWorld()
        await uds_server(fake)
        async with WorldClient() as client:
            # No search arg: an empty query means "no search" on the wire.
            await client.list_records()

        assert fake.records_requests[0].search == ""

    async def test_raises_when_not_connected(self):
        client = WorldClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.list_records()


def _open_world() -> OpenWorld:
    return OpenWorld(
        handle=3,
        session_id="S-joined",
        name="Joined World",
        focused=True,
        user_count=4,
        access_level="Anyone",
    )


def _assert_open_world(
    world: object,
    *,
    handle: int,
    session_id: str,
    name: str,
    focused: bool,
    user_count: int,
    access_level: str,
) -> None:
    assert isinstance(world, OpenWorld)
    assert world.handle == handle
    assert world.session_id == session_id
    assert world.name == name
    assert world.focused is focused
    assert world.user_count == user_count
    assert world.access_level == access_level


class TestJoin:
    async def test_join_by_session_id_returns_open_world(self, uds_server: UdsServer):
        fake = _FakeWorld(join_world=_open_world())
        await uds_server(fake)
        async with WorldClient() as client:
            world = await client.join(session_id="S-target")

        # join unwraps JoinResponse.world into the generated OpenWorld.
        _assert_open_world(
            world,
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

    async def test_join_by_url_lands_in_session_url_field(self, uds_server: UdsServer):
        fake = _FakeWorld(join_world=_open_world())
        await uds_server(fake)
        async with WorldClient() as client:
            await client.join(url="lnl-nat://abc/42", focus=False)

        wire = fake.join_requests[0]
        # The user-facing ``url`` arg must populate the proto ``session_url``
        # field, leaving ``session_id`` empty.
        assert wire.session_url == "lnl-nat://abc/42"
        assert wire.session_id == ""
        assert wire.focus is False

    async def test_join_raises_runtime_error_when_world_omitted(
        self, uds_server: UdsServer
    ):
        # The server returned a JoinResponse with no world payload; the
        # unwrapping client must raise rather than return None.
        fake = _FakeWorld(join_world=None)
        await uds_server(fake)
        async with WorldClient() as client:
            with pytest.raises(RuntimeError):
                await client.join(session_id="S-target")

    async def test_join_with_neither_raises_value_error(self, uds_server: UdsServer):
        fake = _FakeWorld(join_world=_open_world())
        await uds_server(fake)
        async with WorldClient() as client:
            with pytest.raises(ValueError):
                await client.join()
        # The invalid call must never reach the wire.
        assert fake.join_requests == []

    async def test_join_with_both_raises_value_error(self, uds_server: UdsServer):
        fake = _FakeWorld(join_world=_open_world())
        await uds_server(fake)
        async with WorldClient() as client:
            with pytest.raises(ValueError):
                await client.join(session_id="S-x", url="lnl-nat://abc/1")
        assert fake.join_requests == []

    async def test_raises_when_not_connected(self):
        client = WorldClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.join(session_id="S-x")


class TestStartWorld:
    async def test_start_world_returns_open_world_and_carries_request(
        self, uds_server: UdsServer
    ):
        started = OpenWorld(
            handle=9,
            session_id="S-new",
            name="Fresh Session",
            focused=False,
            user_count=1,
            access_level="ContactsPlus",
        )
        fake = _FakeWorld(start_world_world=started)
        await uds_server(fake)
        async with WorldClient() as client:
            world = await client.start_world(
                record_id="R-template", owner_id="U-owner", focus=False
            )

        _assert_open_world(
            world,
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

    async def test_start_world_defaults_focus_true(self, uds_server: UdsServer):
        fake = _FakeWorld(start_world_world=_open_world())
        await uds_server(fake)
        async with WorldClient() as client:
            await client.start_world(record_id="R-template")

        wire = fake.start_world_requests[0]
        assert wire.owner_id == ""
        assert wire.focus is True

    async def test_start_world_raises_runtime_error_when_world_omitted(
        self, uds_server: UdsServer
    ):
        fake = _FakeWorld(start_world_world=None)
        await uds_server(fake)
        async with WorldClient() as client:
            with pytest.raises(RuntimeError):
                await client.start_world(record_id="R-template")

    async def test_raises_when_not_connected(self):
        client = WorldClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.start_world(record_id="R-template")


class TestListOpenWorlds:
    async def test_returns_list_of_open_worlds(self, uds_server: UdsServer):
        worlds = [
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
        fake = _FakeWorld(open_worlds=worlds)
        await uds_server(fake)
        async with WorldClient() as client:
            result = await client.list_open_worlds()

        assert isinstance(result, list)
        assert len(result) == 2
        _assert_open_world(
            result[0],
            handle=1,
            session_id="S-a",
            name="A",
            focused=True,
            user_count=2,
            access_level="Anyone",
        )
        _assert_open_world(
            result[1],
            handle=2,
            session_id="S-b",
            name="B",
            focused=False,
            user_count=0,
            access_level="Private",
        )
        assert len(fake.list_open_worlds_requests) == 1

    async def test_returns_empty_list_when_no_worlds_open(self, uds_server: UdsServer):
        fake = _FakeWorld(open_worlds=[])
        await uds_server(fake)
        async with WorldClient() as client:
            result = await client.list_open_worlds()

        assert result == []

    async def test_raises_when_not_connected(self):
        client = WorldClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.list_open_worlds()


class TestFocus:
    async def test_focus_sends_handle_and_returns_open_world(
        self, uds_server: UdsServer
    ):
        focused = OpenWorld(
            handle=5,
            session_id="S-focused",
            name="Now Focused",
            focused=True,
            user_count=3,
            access_level="Anyone",
        )
        fake = _FakeWorld(focus_world=focused)
        await uds_server(fake)
        async with WorldClient() as client:
            world = await client.focus(5)

        _assert_open_world(
            world,
            handle=5,
            session_id="S-focused",
            name="Now Focused",
            focused=True,
            user_count=3,
            access_level="Anyone",
        )
        assert len(fake.focus_requests) == 1
        assert fake.focus_requests[0].handle == 5

    async def test_focus_raises_runtime_error_when_world_omitted(
        self, uds_server: UdsServer
    ):
        fake = _FakeWorld(focus_world=None)
        await uds_server(fake)
        async with WorldClient() as client:
            with pytest.raises(RuntimeError):
                await client.focus(5)

    async def test_raises_when_not_connected(self):
        client = WorldClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.focus(1)


class TestLeave:
    async def test_leave_sends_handle_and_returns_none(self, uds_server: UdsServer):
        fake = _FakeWorld()
        await uds_server(fake)
        async with WorldClient() as client:
            result = await client.leave(7)

        assert result is None
        assert len(fake.leave_requests) == 1
        assert fake.leave_requests[0].handle == 7

    async def test_raises_when_not_connected(self):
        client = WorldClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.leave(1)


class TestGetCurrent:
    async def test_returns_open_world_when_has_world_true(self, uds_server: UdsServer):
        current = OpenWorld(
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
        await uds_server(fake)
        async with WorldClient() as client:
            world = await client.get_current()

        _assert_open_world(
            world,
            handle=2,
            session_id="S-current",
            name="Current",
            focused=True,
            user_count=6,
            access_level="Anyone",
        )

    async def test_returns_none_when_has_world_false(self, uds_server: UdsServer):
        # Userspace-only: no joinable world is focused, so has_world is False
        # even though the response message technically carries a (default)
        # world. The client must return None, not an empty OpenWorld.
        fake = _FakeWorld(
            current_response=GetCurrentResponse(world=None, has_world=False)
        )
        await uds_server(fake)
        async with WorldClient() as client:
            world = await client.get_current()

        assert world is None

    async def test_raises_when_not_connected(self):
        client = WorldClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.get_current()


class TestFetchThumbnail:
    async def test_sends_uri_and_returns_response_with_bytes_and_content_type(
        self, uds_server: UdsServer
    ):
        webp_bytes = b"RIFF\x00\x00\x00\x00WEBPVP8 "
        fake = _FakeWorld(
            thumbnail_response=FetchThumbnailResponse(
                data=webp_bytes,
                content_type="image/webp",
            )
        )
        await uds_server(fake)
        async with WorldClient() as client:
            response = await client.fetch_thumbnail("resdb:///abc.webp")

        # The user-facing ``uri`` arg must travel verbatim on the wire.
        assert len(fake.fetch_thumbnail_requests) == 1
        assert fake.fetch_thumbnail_requests[0].uri == "resdb:///abc.webp"

        # The method returns the generated FetchThumbnailResponse directly.
        assert isinstance(response, FetchThumbnailResponse)
        assert response.data == webp_bytes
        assert response.content_type == "image/webp"

    async def test_allows_empty_content_type_with_returned_bytes(
        self, uds_server: UdsServer
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
        await uds_server(fake)
        async with WorldClient() as client:
            response = await client.fetch_thumbnail("resdb:///no-type")

        assert fake.fetch_thumbnail_requests[0].uri == "resdb:///no-type"
        assert response.data == raw_bytes
        assert response.content_type == ""

    async def test_raises_when_not_connected(self):
        client = WorldClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.fetch_thumbnail("resdb:///abc.webp")
