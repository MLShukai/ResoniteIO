"""Client for the Resonite IO ``Inventory`` unary RPCs (bash-like file ops).

The Inventory service is stateless and path-based: every method takes a
resolved absolute path (e.g. ``/Inventory/MyFolder``). There is no
server-side cwd — relative-path resolution, ``cd`` and ``pwd`` live only
in the ``resoio inventory`` REPL.

Directory ``cp`` / ``rm`` require ``recursive=True`` (mirroring ``cp -r`` /
``rm -r``); the server returns ``FailedPrecondition`` otherwise. ``move``
handles directories without a flag.
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass
from types import TracebackType
from typing import Self

from grpclib.client import Channel

from resoio._generated.resonite_io.v1 import (
    InventoryCopyRequest,
    InventoryEntry as _PbInventoryEntry,
    InventoryEntryKind as _PbInventoryEntryKind,
    InventoryListing as _PbInventoryListing,
    InventoryListRequest,
    InventoryMakeDirRequest,
    InventoryMoveRequest,
    InventoryMutationResult as _PbInventoryMutationResult,
    InventoryRemoveRequest,
    InventorySpawnRequest,
    InventorySpawnResult as _PbInventorySpawnResult,
    InventoryStub,
)
from resoio._socket import resolve_socket_path

__all__ = [
    "InventoryClient",
    "InventoryEntry",
    "InventoryEntryKind",
    "InventoryListing",
    "InventoryMutationResult",
    "InventorySpawnResult",
]

_logger = logging.getLogger("resoio.inventory")


class InventoryEntryKind(enum.Enum):
    """Kind of an inventory entry (mirrors Resonite ``Record.RecordType``)."""

    UNKNOWN = "unknown"
    DIRECTORY = "directory"
    OBJECT = "object"
    WORLD = "world"
    LINK = "link"


@dataclass(frozen=True, slots=True)
class InventoryEntry:
    """One inventory entry (a folder or an item record)."""

    name: str
    path: str
    kind: InventoryEntryKind
    record_id: str
    asset_uri: str
    is_public: bool
    last_modified_unix_nanos: int


@dataclass(frozen=True, slots=True)
class InventoryListing:
    """Contents of a directory returned by :meth:`InventoryClient.list`."""

    path: str
    entries: tuple[InventoryEntry, ...]


@dataclass(frozen=True, slots=True)
class InventoryMutationResult:
    """Result of a mutation (mkdir / cp / mv / rm)."""

    path: str
    record_id: str


@dataclass(frozen=True, slots=True)
class InventorySpawnResult:
    """Result of spawning an item into the world."""

    source_path: str
    spawned_slot_id: str
    spawned_slot_name: str


_KIND_FROM_PROTO: dict[_PbInventoryEntryKind, InventoryEntryKind] = {
    _PbInventoryEntryKind.DIRECTORY: InventoryEntryKind.DIRECTORY,
    _PbInventoryEntryKind.OBJECT: InventoryEntryKind.OBJECT,
    _PbInventoryEntryKind.WORLD: InventoryEntryKind.WORLD,
    _PbInventoryEntryKind.LINK: InventoryEntryKind.LINK,
}


def _entry_from_proto(pb: _PbInventoryEntry) -> InventoryEntry:
    return InventoryEntry(
        name=pb.name,
        path=pb.path,
        kind=_KIND_FROM_PROTO.get(pb.kind, InventoryEntryKind.UNKNOWN),
        record_id=pb.record_id,
        asset_uri=pb.asset_uri,
        is_public=pb.is_public,
        last_modified_unix_nanos=pb.last_modified_unix_nanos,
    )


def _listing_from_proto(pb: _PbInventoryListing) -> InventoryListing:
    return InventoryListing(
        path=pb.path,
        entries=tuple(_entry_from_proto(e) for e in pb.entries),
    )


def _mutation_from_proto(pb: _PbInventoryMutationResult) -> InventoryMutationResult:
    return InventoryMutationResult(path=pb.path, record_id=pb.record_id)


def _spawn_from_proto(pb: _PbInventorySpawnResult) -> InventorySpawnResult:
    return InventorySpawnResult(
        source_path=pb.source_path,
        spawned_slot_id=pb.spawned_slot_id,
        spawned_slot_name=pb.spawned_slot_name,
    )


class InventoryClient:
    """Async, stateless client for the Resonite IO ``Inventory`` service.

    Use as an async context manager so the gRPC channel closes
    deterministically. Socket resolution mirrors :class:`resoio.SessionClient`.
    """

    def __init__(self, socket_path: str | None = None) -> None:
        self._explicit_path: str | None = socket_path
        self._channel: Channel | None = None
        self._stub: InventoryStub | None = None
        self._resolved_path: str | None = None

    @property
    def socket_path(self) -> str | None:
        """Resolved UDS path, or ``None`` before ``__aenter__``."""
        return self._resolved_path

    async def __aenter__(self) -> Self:
        path = self._explicit_path or resolve_socket_path()
        _logger.debug("Opening Inventory channel on UDS path: %s", path)
        channel = Channel(path=path)
        self._channel = channel
        self._stub = InventoryStub(channel)
        self._resolved_path = path
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        channel = self._channel
        self._channel = None
        self._stub = None
        self._resolved_path = None
        if channel is not None:
            channel.close()

    def _require_stub(self) -> InventoryStub:
        stub = self._stub
        if stub is None:
            raise RuntimeError(
                "InventoryClient is not connected. Use `async with InventoryClient(): ...`."
            )
        return stub

    async def list(self, path: str) -> InventoryListing:
        """List the entries directly under ``path`` (``ls``)."""
        stub = self._require_stub()
        return _listing_from_proto(await stub.list(InventoryListRequest(path=path)))

    async def mkdir(self, path: str) -> InventoryMutationResult:
        """Create a folder at ``path`` (``mkdir``)."""
        stub = self._require_stub()
        return _mutation_from_proto(
            await stub.make_dir(InventoryMakeDirRequest(path=path))
        )

    async def copy(
        self, src: str, dst: str, *, recursive: bool = False
    ) -> InventoryMutationResult:
        """Copy ``src`` to ``dst`` (``cp``); set ``recursive`` for folders
        (``cp -r``)."""
        stub = self._require_stub()
        return _mutation_from_proto(
            await stub.copy(
                InventoryCopyRequest(
                    source_path=src, destination_path=dst, recursive=recursive
                )
            )
        )

    async def move(self, src: str, dst: str) -> InventoryMutationResult:
        """Move ``src`` to ``dst`` (``mv``; folders move recursively)."""
        stub = self._require_stub()
        return _mutation_from_proto(
            await stub.move(InventoryMoveRequest(source_path=src, destination_path=dst))
        )

    async def remove(
        self, path: str, *, recursive: bool = False
    ) -> InventoryMutationResult:
        """Remove ``path`` (``rm``); set ``recursive`` for folders (``rm
        -r``)."""
        stub = self._require_stub()
        return _mutation_from_proto(
            await stub.remove(InventoryRemoveRequest(path=path, recursive=recursive))
        )

    async def spawn(self, path: str) -> InventorySpawnResult:
        """Spawn the item at ``path`` into the current world."""
        stub = self._require_stub()
        return _spawn_from_proto(await stub.spawn(InventorySpawnRequest(path=path)))
