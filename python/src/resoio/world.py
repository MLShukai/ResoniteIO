"""Client for the Resonite IO ``World`` unary RPCs (session / record browsing,
join / start, and local open-world management)."""

from __future__ import annotations

import enum
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import override

from grpclib.client import Channel

from resoio._client import _BaseClient
from resoio._generated.resonite_io.v1 import (
    FetchThumbnailRequest,
    FocusRequest,
    GetCurrentRequest,
    JoinRequest,
    LeaveRequest,
    ListOpenWorldsRequest,
    ListRecordsRequest,
    ListSessionsRequest,
    OpenWorld as _WireOpenWorld,
    RecordSort as _WireRecordSort,
    RecordSortDirection as _WireRecordSortDirection,
    RecordSource as _WireRecordSource,
    SessionFilter as _WireSessionFilter,
    StartWorldRequest,
    WorldRecord as _WireWorldRecord,
    WorldSession as _WireWorldSession,
    WorldStub,
)

__all__ = [
    "OpenWorld",
    "RecordPage",
    "RecordSort",
    "RecordSortDirection",
    "RecordSource",
    "SessionFilter",
    "SessionPage",
    "Thumbnail",
    "WorldClient",
    "WorldRecord",
    "WorldSession",
]

_logger = logging.getLogger("resoio.world")


class SessionFilter(enum.Enum):
    """Live-session filter (left-tab equivalent).

    ``ALL`` = no filter.
    """

    ALL = 0
    FRIENDS = 1
    HEADLESS = 2


class RecordSource(enum.Enum):
    """World-record source (left-tab equivalent)."""

    PUBLIC = 0
    FEATURED = 1
    OWN = 2
    GROUP = 3


class RecordSort(enum.Enum):
    """Record search ordering."""

    CREATION_DATE = 0
    LAST_UPDATE = 1
    FIRST_PUBLISH = 2
    TOTAL_VISITS = 3
    NAME = 4
    RANDOM = 5


class RecordSortDirection(enum.Enum):
    """Record search ordering direction."""

    DESCENDING = 0
    ASCENDING = 1


# ---------------------------------------------------------------------------
# Public <-> wire enum mapping
#
# The wire enums carry a ``UNSPECIFIED = 0`` slot the public enums omit, so
# they are offset and must be mapped by meaning (name), not numeric value.
# The documented defaults alias the public head to the corresponding
# non-UNSPECIFIED wire member: ALL -> UNSPECIFIED, PUBLIC -> PUBLIC, etc.
# ---------------------------------------------------------------------------

_SESSION_FILTER_TO_WIRE: dict[SessionFilter, _WireSessionFilter] = {
    SessionFilter.ALL: _WireSessionFilter.UNSPECIFIED,
    SessionFilter.FRIENDS: _WireSessionFilter.FRIENDS,
    SessionFilter.HEADLESS: _WireSessionFilter.HEADLESS,
}

_RECORD_SOURCE_TO_WIRE: dict[RecordSource, _WireRecordSource] = {
    RecordSource.PUBLIC: _WireRecordSource.PUBLIC,
    RecordSource.FEATURED: _WireRecordSource.FEATURED,
    RecordSource.OWN: _WireRecordSource.OWN,
    RecordSource.GROUP: _WireRecordSource.GROUP,
}

_RECORD_SORT_TO_WIRE: dict[RecordSort, _WireRecordSort] = {
    RecordSort.CREATION_DATE: _WireRecordSort.CREATION_DATE,
    RecordSort.LAST_UPDATE: _WireRecordSort.LAST_UPDATE,
    RecordSort.FIRST_PUBLISH: _WireRecordSort.FIRST_PUBLISH,
    RecordSort.TOTAL_VISITS: _WireRecordSort.TOTAL_VISITS,
    RecordSort.NAME: _WireRecordSort.NAME,
    RecordSort.RANDOM: _WireRecordSort.RANDOM,
}

_RECORD_SORT_DIRECTION_TO_WIRE: dict[RecordSortDirection, _WireRecordSortDirection] = {
    RecordSortDirection.DESCENDING: _WireRecordSortDirection.DESCENDING,
    RecordSortDirection.ASCENDING: _WireRecordSortDirection.ASCENDING,
}


@dataclass(frozen=True, slots=True)
class WorldSession:
    """One live session (a tile in the world browser)."""

    session_id: str
    name: str
    description: str
    host_user_id: str
    host_username: str
    session_urls: tuple[str, ...]
    thumbnail_url: str
    joined_users: int
    active_users: int
    maximum_users: int
    tags: tuple[str, ...]
    access_level: str
    headless_host: bool
    mobile_friendly: bool
    corresponding_world_id: str
    universe_id: str
    session_begin_unix_nanos: int
    last_update_unix_nanos: int


@dataclass(frozen=True, slots=True)
class WorldRecord:
    """One world record (a saved world / template)."""

    record_id: str
    owner_id: str
    name: str
    description: str
    thumbnail_url: str
    tags: tuple[str, ...]
    record_url: str
    last_modification_unix_nanos: int


@dataclass(frozen=True, slots=True)
class OpenWorld:
    """One locally-open world."""

    handle: int
    session_id: str
    name: str
    focused: bool
    user_count: int
    access_level: str


@dataclass(frozen=True, slots=True)
class SessionPage:
    """A page of :class:`WorldSession` results."""

    sessions: tuple[WorldSession, ...]
    total_count: int
    page: int
    page_size: int


@dataclass(frozen=True, slots=True)
class RecordPage:
    """A page of :class:`WorldRecord` results."""

    records: tuple[WorldRecord, ...]
    has_more: bool
    offset: int


@dataclass(frozen=True, slots=True)
class Thumbnail:
    """A fetched thumbnail image and its MIME type."""

    data: bytes
    content_type: str


def _session_from_wire(wire: _WireWorldSession) -> WorldSession:
    return WorldSession(
        session_id=wire.session_id,
        name=wire.name,
        description=wire.description,
        host_user_id=wire.host_user_id,
        host_username=wire.host_username,
        session_urls=tuple(wire.session_urls),
        thumbnail_url=wire.thumbnail_url,
        joined_users=wire.joined_users,
        active_users=wire.active_users,
        maximum_users=wire.maximum_users,
        tags=tuple(wire.tags),
        access_level=wire.access_level,
        headless_host=wire.headless_host,
        mobile_friendly=wire.mobile_friendly,
        corresponding_world_id=wire.corresponding_world_id,
        universe_id=wire.universe_id,
        session_begin_unix_nanos=wire.session_begin_unix_nanos,
        last_update_unix_nanos=wire.last_update_unix_nanos,
    )


def _record_from_wire(wire: _WireWorldRecord) -> WorldRecord:
    return WorldRecord(
        record_id=wire.record_id,
        owner_id=wire.owner_id,
        name=wire.name,
        description=wire.description,
        thumbnail_url=wire.thumbnail_url,
        tags=tuple(wire.tags),
        record_url=wire.record_url,
        last_modification_unix_nanos=wire.last_modification_unix_nanos,
    )


def _open_world_from_wire(wire: _WireOpenWorld) -> OpenWorld:
    return OpenWorld(
        handle=wire.handle,
        session_id=wire.session_id,
        name=wire.name,
        focused=wire.focused,
        user_count=wire.user_count,
        access_level=wire.access_level,
    )


def _open_world_from_response(wire: _WireOpenWorld | None) -> OpenWorld:
    """Convert the optional ``OpenWorld`` a single-world response promised to
    populate, raising if the server left it unset."""
    if wire is None:
        raise RuntimeError("World response did not include an OpenWorld.")
    return _open_world_from_wire(wire)


class WorldClient(_BaseClient[WorldStub]):
    """Async client for the Resonite IO ``World`` service over a UDS.

    Use as an async context manager so the gRPC channel closes
    deterministically.
    """

    _logger = _logger
    _log_label = "World"

    @override
    def _make_stub(self, channel: Channel) -> WorldStub:
        return WorldStub(channel)

    async def list_sessions(
        self,
        *,
        search: str = "",
        filter: SessionFilter = SessionFilter.ALL,
        min_active_users: int = 0,
        page: int = 0,
        page_size: int = 0,
    ) -> SessionPage:
        """List live sessions (filter / search / paging applied mod-side)."""
        stub = self._require_stub()
        request = ListSessionsRequest(
            search=search,
            filter=_SESSION_FILTER_TO_WIRE[filter],
            min_active_users=min_active_users,
            page=page,
            page_size=page_size,
        )
        response = await stub.list_sessions(request)
        return SessionPage(
            sessions=tuple(_session_from_wire(s) for s in response.sessions),
            total_count=response.total_count,
            page=response.page,
            page_size=response.page_size,
        )

    async def list_records(
        self,
        *,
        source: RecordSource = RecordSource.PUBLIC,
        required_tags: Sequence[str] = (),
        owner_id: str = "",
        search: str = "",
        offset: int = 0,
        count: int = 0,
        sort: RecordSort = RecordSort.CREATION_DATE,
        sort_direction: RecordSortDirection = RecordSortDirection.DESCENDING,
    ) -> RecordPage:
        """List world records (use ``sort=RANDOM`` for the random tab).

        ``search`` is a free-text query mirroring the World tab (``+term``
        required / ``-term`` excluded / ``"phrase"``; empty = no search).
        """
        stub = self._require_stub()
        request = ListRecordsRequest(
            source=_RECORD_SOURCE_TO_WIRE[source],
            required_tags=list(required_tags),
            owner_id=owner_id,
            search=search,
            offset=offset,
            count=count,
            sort=_RECORD_SORT_TO_WIRE[sort],
            sort_direction=_RECORD_SORT_DIRECTION_TO_WIRE[sort_direction],
        )
        response = await stub.list_records(request)
        return RecordPage(
            records=tuple(_record_from_wire(r) for r in response.records),
            has_more=response.has_more,
            offset=response.offset,
        )

    async def join(
        self,
        *,
        session_id: str = "",
        url: str = "",
        focus: bool = True,
    ) -> OpenWorld:
        """Join an existing session by ``session_id`` or by ``url``.

        Exactly one of ``session_id`` / ``url`` must be supplied.
        """
        if bool(session_id) == bool(url):
            raise ValueError("join() requires exactly one of 'session_id' or 'url'.")
        stub = self._require_stub()
        request = JoinRequest(
            session_id=session_id,
            session_url=url,
            focus=focus,
        )
        response = await stub.join(request)
        return _open_world_from_response(response.world)

    async def start_world(
        self,
        *,
        record_id: str,
        owner_id: str = "",
        focus: bool = True,
    ) -> OpenWorld:
        """Start a new session from a world record."""
        stub = self._require_stub()
        request = StartWorldRequest(
            record_id=record_id,
            owner_id=owner_id,
            focus=focus,
        )
        response = await stub.start_world(request)
        return _open_world_from_response(response.world)

    async def list_open_worlds(self) -> list[OpenWorld]:
        """List the locally-open worlds."""
        stub = self._require_stub()
        response = await stub.list_open_worlds(ListOpenWorldsRequest())
        return [_open_world_from_wire(w) for w in response.worlds]

    async def focus(self, handle: int) -> OpenWorld:
        """Focus a locally-open world by handle."""
        stub = self._require_stub()
        response = await stub.focus(FocusRequest(handle=handle))
        return _open_world_from_response(response.world)

    async def leave(self, handle: int) -> None:
        """Leave a locally-open world by handle."""
        stub = self._require_stub()
        await stub.leave(LeaveRequest(handle=handle))

    async def get_current(self) -> OpenWorld | None:
        """Return the currently focused world, or ``None`` when in
        userspace."""
        stub = self._require_stub()
        response = await stub.get_current(GetCurrentRequest())
        if not response.has_world:
            return None
        return _open_world_from_response(response.world)

    async def fetch_thumbnail(self, uri: str) -> Thumbnail:
        """Fetch a thumbnail image by its ``resdb:///`` or ``https://`` URI."""
        stub = self._require_stub()
        response = await stub.fetch_thumbnail(FetchThumbnailRequest(uri=uri))
        return Thumbnail(data=response.data, content_type=response.content_type)
