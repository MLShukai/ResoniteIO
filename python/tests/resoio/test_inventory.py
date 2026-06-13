from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

import pytest

from resoio._generated.resonite_io.v1 import (
    InventoryBase,
    InventoryCopyRequest,
    InventoryEntry as PbInventoryEntry,
    InventoryEntryKind as PbInventoryEntryKind,
    InventoryListing as PbInventoryListing,
    InventoryListRequest,
    InventoryMakeDirRequest,
    InventoryMoveRequest,
    InventoryMutationResult as PbInventoryMutationResult,
    InventoryRemoveRequest,
    InventorySpawnRequest,
    InventorySpawnResult as PbInventorySpawnResult,
    InventoryThumbnailRequest,
    InventoryThumbnailResponse,
)
from resoio.inventory import (
    InventoryClient,
    InventoryEntry,
    InventoryEntryKind,
    InventoryThumbnail,
)

if TYPE_CHECKING:
    from grpclib._typing import IServable

UdsServer = Callable[["IServable"], Awaitable[str]]


class _FakeInventory(InventoryBase):
    """In-process fake recording requests and serving a tiny seed tree."""

    def __init__(
        self,
        *,
        thumbnail_response: InventoryThumbnailResponse | None = None,
    ) -> None:
        self.last_copy: InventoryCopyRequest | None = None
        self.last_move: InventoryMoveRequest | None = None
        self.last_remove: InventoryRemoveRequest | None = None
        self.last_make_dir: InventoryMakeDirRequest | None = None
        self.last_spawn: InventorySpawnRequest | None = None
        self.fetch_thumbnail_requests: list[InventoryThumbnailRequest] = []
        self._thumbnail_response = thumbnail_response or InventoryThumbnailResponse()

    async def list(self, message: InventoryListRequest) -> PbInventoryListing:
        return PbInventoryListing(
            path=message.path,
            entries=[
                PbInventoryEntry(
                    name="Avatars",
                    path=f"{message.path}/Avatars",
                    kind=PbInventoryEntryKind.DIRECTORY,
                    record_id="",
                    asset_uri="",
                    is_public=False,
                    last_modified_unix_nanos=0,
                ),
                PbInventoryEntry(
                    name="MyAvatar",
                    path=f"{message.path}/MyAvatar",
                    kind=PbInventoryEntryKind.OBJECT,
                    record_id="R-myavatar",
                    asset_uri="resrec:///U-test/R-myavatar",
                    is_public=True,
                    last_modified_unix_nanos=1_700_000_000_000_000_000,
                ),
            ],
        )

    async def make_dir(
        self, message: InventoryMakeDirRequest
    ) -> PbInventoryMutationResult:
        self.last_make_dir = message
        return PbInventoryMutationResult(path=message.path, record_id="R-new")

    async def copy(self, message: InventoryCopyRequest) -> PbInventoryMutationResult:
        self.last_copy = message
        return PbInventoryMutationResult(
            path=message.destination_path, record_id="R-copy"
        )

    async def move(self, message: InventoryMoveRequest) -> PbInventoryMutationResult:
        self.last_move = message
        return PbInventoryMutationResult(
            path=message.destination_path, record_id="R-moved"
        )

    async def remove(
        self, message: InventoryRemoveRequest
    ) -> PbInventoryMutationResult:
        self.last_remove = message
        return PbInventoryMutationResult(path=message.path, record_id="R-removed")

    async def spawn(self, message: InventorySpawnRequest) -> PbInventorySpawnResult:
        self.last_spawn = message
        return PbInventorySpawnResult(
            source_path=message.path,
            spawned_slot_id="ID-123",
            spawned_slot_name="MyAvatar",
        )

    async def fetch_thumbnail(
        self, message: InventoryThumbnailRequest
    ) -> InventoryThumbnailResponse:
        self.fetch_thumbnail_requests.append(message)
        return self._thumbnail_response


class TestInventoryClient:
    async def test_list_decodes_entries_kinds_and_fields(self, uds_server: UdsServer):
        fake = _FakeInventory()
        await uds_server(fake)
        async with InventoryClient() as client:
            listing = await client.list("/Inventory")
        assert listing.path == "/Inventory"
        by_name = {e.name: e for e in listing.entries}
        assert by_name["Avatars"] == InventoryEntry(
            name="Avatars",
            path="/Inventory/Avatars",
            kind=InventoryEntryKind.DIRECTORY,
            record_id="",
            asset_uri="",
            is_public=False,
            last_modified_unix_nanos=0,
        )
        my = by_name["MyAvatar"]
        assert my.kind is InventoryEntryKind.OBJECT
        assert my.record_id == "R-myavatar"
        assert my.asset_uri == "resrec:///U-test/R-myavatar"
        assert my.is_public is True
        assert my.last_modified_unix_nanos == 1_700_000_000_000_000_000

    async def test_mkdir_returns_mutation_result(self, uds_server: UdsServer):
        fake = _FakeInventory()
        await uds_server(fake)
        async with InventoryClient() as client:
            result = await client.mkdir("/Inventory/NewFolder")
        assert result.path == "/Inventory/NewFolder"
        assert result.record_id == "R-new"
        assert fake.last_make_dir is not None
        assert fake.last_make_dir.path == "/Inventory/NewFolder"

    async def test_copy_forwards_recursive_flag(self, uds_server: UdsServer):
        fake = _FakeInventory()
        await uds_server(fake)
        async with InventoryClient() as client:
            await client.copy("/Inventory/A", "/Inventory/B", recursive=True)
        assert fake.last_copy is not None
        assert fake.last_copy.source_path == "/Inventory/A"
        assert fake.last_copy.destination_path == "/Inventory/B"
        assert fake.last_copy.recursive is True

    async def test_copy_defaults_recursive_false(self, uds_server: UdsServer):
        fake = _FakeInventory()
        await uds_server(fake)
        async with InventoryClient() as client:
            await client.copy("/Inventory/A", "/Inventory/B")
        assert fake.last_copy is not None
        assert fake.last_copy.recursive is False

    async def test_move_forwards_paths(self, uds_server: UdsServer):
        fake = _FakeInventory()
        await uds_server(fake)
        async with InventoryClient() as client:
            result = await client.move("/Inventory/A", "/Inventory/C")
        assert result.path == "/Inventory/C"
        assert fake.last_move is not None
        assert fake.last_move.source_path == "/Inventory/A"
        assert fake.last_move.destination_path == "/Inventory/C"

    async def test_remove_forwards_recursive_flag(self, uds_server: UdsServer):
        fake = _FakeInventory()
        await uds_server(fake)
        async with InventoryClient() as client:
            await client.remove("/Inventory/Folder", recursive=True)
        assert fake.last_remove is not None
        assert fake.last_remove.path == "/Inventory/Folder"
        assert fake.last_remove.recursive is True

    async def test_spawn_returns_slot_info(self, uds_server: UdsServer):
        fake = _FakeInventory()
        await uds_server(fake)
        async with InventoryClient() as client:
            result = await client.spawn("/Inventory/MyAvatar")
        assert result.source_path == "/Inventory/MyAvatar"
        assert result.spawned_slot_id == "ID-123"
        assert result.spawned_slot_name == "MyAvatar"

    async def test_raises_when_used_outside_context(self):
        client = InventoryClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.list("/Inventory")


class TestFetchThumbnail:
    async def test_returns_thumbnail_with_bytes_content_type_and_forwards_path(
        self, uds_server: UdsServer
    ):
        webp_bytes = b"RIFF\x00\x00\x00\x00WEBPVP8 "
        fake = _FakeInventory(
            thumbnail_response=InventoryThumbnailResponse(
                data=webp_bytes,
                content_type="image/webp",
            )
        )
        await uds_server(fake)
        async with InventoryClient() as client:
            thumbnail = await client.fetch_thumbnail("/Inventory/MyAvatar")

        # The user-facing ``path`` arg must travel verbatim on the wire.
        assert len(fake.fetch_thumbnail_requests) == 1
        assert fake.fetch_thumbnail_requests[0].path == "/Inventory/MyAvatar"

        # The method converts the response into the public InventoryThumbnail
        # dataclass, carrying the exact bytes and content_type.
        assert thumbnail == InventoryThumbnail(
            data=webp_bytes,
            content_type="image/webp",
        )

    async def test_allows_empty_content_type_with_returned_bytes(
        self, uds_server: UdsServer
    ):
        # The server may not know the MIME type; an empty content_type is a
        # valid response and must surface verbatim (not coerced to a default).
        raw_bytes = b"\x89PNG\r\n\x1a\n"
        fake = _FakeInventory(
            thumbnail_response=InventoryThumbnailResponse(
                data=raw_bytes,
                content_type="",
            )
        )
        await uds_server(fake)
        async with InventoryClient() as client:
            thumbnail = await client.fetch_thumbnail("/Inventory/NoType")

        assert fake.fetch_thumbnail_requests[0].path == "/Inventory/NoType"
        assert thumbnail.data == raw_bytes
        assert thumbnail.content_type == ""

    async def test_raises_when_not_connected(self):
        client = InventoryClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.fetch_thumbnail("/Inventory/MyAvatar")
