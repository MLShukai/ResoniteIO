"""Tests for the ``resoio inventory`` REPL.

These exercise :class:`InventoryShell` (command dispatch + completion)
directly against an in-process grpclib server, bypassing the prompt_toolkit
terminal layer (which is a thin adapter over the shell).
"""

import io
from pathlib import Path

import pytest
from grpclib.const import Status
from grpclib.exceptions import GRPCError
from grpclib.server import Server

from resoio._generated.resonite_io.v1 import (
    InventoryBase,
    InventoryCopyRequest,
    InventoryEntry as PbInventoryEntry,
    InventoryEntryKind as PbKind,
    InventoryListing as PbInventoryListing,
    InventoryListRequest,
    InventoryMakeDirRequest,
    InventoryMoveRequest,
    InventoryMutationResult as PbInventoryMutationResult,
    InventoryRemoveRequest,
    InventorySpawnRequest,
    InventorySpawnResult as PbInventorySpawnResult,
    InventoryThumbnailRequest,
    InventoryThumbnailResponse as PbInventoryThumbnailResponse,
)
from resoio.cli.inventory import InventoryShell
from resoio.inventory import InventoryClient


def _parent(path: str) -> str:
    idx = path.rfind("/")
    return "/" if idx <= 0 else path[:idx]


def _name(path: str) -> str:
    return path.rsplit("/", 1)[-1]


class _FakeInventory(InventoryBase):
    """In-process inventory backed by a path -> kind dict."""

    def __init__(self) -> None:
        self.tree: dict[str, str] = {
            "/Inventory": "dir",
            "/Inventory/Avatars": "dir",
            "/Inventory/MyAvatar": "object",
            "/Inventory/Avatars/Robot": "object",
        }
        self.thumb_requests: list[str] = []
        self.thumb_data: bytes = b"RIFF\x00\x00\x00\x00WEBPVP8 fake-bytes"
        self.thumb_content_type: str = "image/webp"

    async def list(self, message: InventoryListRequest) -> PbInventoryListing:
        path = message.path
        if self.tree.get(path) != "dir":
            raise GRPCError(Status.NOT_FOUND, f"not found: {path}")
        entries = [
            PbInventoryEntry(
                name=_name(p),
                path=p,
                kind=PbKind.DIRECTORY if kind == "dir" else PbKind.OBJECT,
            )
            for p, kind in self.tree.items()
            if _parent(p) == path
        ]
        return PbInventoryListing(path=path, entries=entries)

    async def make_dir(
        self, message: InventoryMakeDirRequest
    ) -> PbInventoryMutationResult:
        self.tree[message.path] = "dir"
        return PbInventoryMutationResult(path=message.path, record_id="R-new")

    async def copy(self, message: InventoryCopyRequest) -> PbInventoryMutationResult:
        src = message.source_path
        if self.tree.get(src) == "dir":
            if not message.recursive:
                raise GRPCError(
                    Status.FAILED_PRECONDITION, "is a directory (use cp -r)"
                )
            for p in [k for k in self.tree if k == src or k.startswith(src + "/")]:
                self.tree[message.destination_path + p[len(src) :]] = self.tree[p]
        else:
            self.tree[message.destination_path] = self.tree.get(src, "object")
        return PbInventoryMutationResult(
            path=message.destination_path, record_id="R-copy"
        )

    async def move(self, message: InventoryMoveRequest) -> PbInventoryMutationResult:
        src = message.source_path
        for p in [k for k in list(self.tree) if k == src or k.startswith(src + "/")]:
            self.tree[message.destination_path + p[len(src) :]] = self.tree.pop(p)
        return PbInventoryMutationResult(
            path=message.destination_path, record_id="R-moved"
        )

    async def remove(
        self, message: InventoryRemoveRequest
    ) -> PbInventoryMutationResult:
        path = message.path
        if self.tree.get(path) == "dir" and not message.recursive:
            raise GRPCError(Status.FAILED_PRECONDITION, "is a directory (use rm -r)")
        for p in [k for k in list(self.tree) if k == path or k.startswith(path + "/")]:
            del self.tree[p]
        return PbInventoryMutationResult(path=path, record_id="R-removed")

    async def spawn(self, message: InventorySpawnRequest) -> PbInventorySpawnResult:
        return PbInventorySpawnResult(
            source_path=message.path,
            spawned_slot_id="ID-x",
            spawned_slot_name=_name(message.path),
        )

    async def fetch_thumbnail(
        self, message: InventoryThumbnailRequest
    ) -> PbInventoryThumbnailResponse:
        self.thumb_requests.append(message.path)
        return PbInventoryThumbnailResponse(
            data=self.thumb_data, content_type=self.thumb_content_type
        )


class _Harness:
    def __init__(self, shell: InventoryShell, out: io.StringIO, err: io.StringIO):
        self.shell = shell
        self.out = out
        self.err = err


async def _run(fake: _FakeInventory, socket_path: Path, lines: list[str]) -> _Harness:
    server = Server([fake])
    await server.start(path=str(socket_path))
    out, err = io.StringIO(), io.StringIO()
    try:
        async with InventoryClient(str(socket_path)) as client:
            shell = InventoryShell(client, out=out, err=err)
            for line in lines:
                await shell.execute(line)
            return _Harness(shell, out, err)
    finally:
        server.close()
        await server.wait_closed()


async def test_pwd_and_ls_lists_sorted_with_trailing_slash(tmp_path: Path):
    fake = _FakeInventory()
    h = await _run(fake, tmp_path / "s.sock", ["pwd", "ls"])
    lines = h.out.getvalue().splitlines()
    assert lines[0] == "/Inventory"
    # sorted: Avatars (dir, trailing /) then MyAvatar.
    assert lines[1:] == ["Avatars/", "MyAvatar"]


async def test_cd_relative_resolves_to_absolute(tmp_path: Path):
    fake = _FakeInventory()
    h = await _run(fake, tmp_path / "s.sock", ["cd Avatars", "pwd", "ls"])
    assert h.shell.cwd == "/Inventory/Avatars"
    assert h.out.getvalue().splitlines() == ["/Inventory/Avatars", "Robot"]


async def test_cd_to_missing_prints_error_and_keeps_cwd(tmp_path: Path):
    fake = _FakeInventory()
    h = await _run(fake, tmp_path / "s.sock", ["cd nope"])
    assert h.shell.cwd == "/Inventory"
    assert "NOT_FOUND" in h.err.getvalue()


async def test_rm_directory_without_r_errors_and_keeps_tree(tmp_path: Path):
    fake = _FakeInventory()
    h = await _run(fake, tmp_path / "s.sock", ["rm Avatars"])
    assert "FAILED_PRECONDITION" in h.err.getvalue()
    assert "/Inventory/Avatars" in fake.tree


async def test_rm_recursive_removes_subtree(tmp_path: Path):
    fake = _FakeInventory()
    await _run(fake, tmp_path / "s.sock", ["rm -r Avatars"])
    assert "/Inventory/Avatars" not in fake.tree
    assert "/Inventory/Avatars/Robot" not in fake.tree


async def test_cp_recursive_copies_subtree_with_resolved_paths(tmp_path: Path):
    fake = _FakeInventory()
    await _run(fake, tmp_path / "s.sock", ["cp -r Avatars Characters"])
    assert fake.tree.get("/Inventory/Characters") == "dir"
    assert fake.tree.get("/Inventory/Characters/Robot") == "object"


async def test_mv_directory_moves_subtree(tmp_path: Path):
    fake = _FakeInventory()
    await _run(fake, tmp_path / "s.sock", ["mv Avatars Characters"])
    assert "/Inventory/Avatars" not in fake.tree
    assert fake.tree.get("/Inventory/Characters/Robot") == "object"


async def test_mkdir_creates_resolved_path(tmp_path: Path):
    fake = _FakeInventory()
    await _run(fake, tmp_path / "s.sock", ["mkdir New"])
    assert fake.tree.get("/Inventory/New") == "dir"


async def test_spawn_prints_slot_info(tmp_path: Path):
    fake = _FakeInventory()
    h = await _run(fake, tmp_path / "s.sock", ["spawn MyAvatar"])
    out = h.out.getvalue()
    assert "MyAvatar" in out
    assert "ID-x" in out


# --- thumb --------------------------------------------------------------


async def test_thumb_with_output_writes_file_and_reports(tmp_path: Path):
    fake = _FakeInventory()
    out_file = tmp_path / "avatar.webp"
    h = await _run(fake, tmp_path / "s.sock", [f"thumb MyAvatar -o {out_file}"])
    # The resolved absolute path travels to the server verbatim.
    assert fake.thumb_requests == ["/Inventory/MyAvatar"]
    # Bytes are written verbatim (no re-encoding).
    assert out_file.read_bytes() == fake.thumb_data
    report = h.out.getvalue()
    assert "saved" in report
    assert "image/webp" in report
    assert str(out_file) in report


async def test_thumb_default_filename_uses_content_type_extension(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    fake = _FakeInventory()
    monkeypatch.chdir(tmp_path)
    await _run(fake, tmp_path / "s.sock", ["thumb MyAvatar"])
    # Default name is "<item>.<ext>" in the process cwd; webp -> .webp.
    assert (tmp_path / "MyAvatar.webp").read_bytes() == fake.thumb_data


async def test_thumb_default_filename_unknown_content_type_uses_bin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    fake = _FakeInventory()
    fake.thumb_content_type = ""
    monkeypatch.chdir(tmp_path)
    await _run(fake, tmp_path / "s.sock", ["thumb MyAvatar"])
    assert (tmp_path / "MyAvatar.bin").read_bytes() == fake.thumb_data


async def test_thumb_missing_operand_errors_without_calling_server(tmp_path: Path):
    fake = _FakeInventory()
    h = await _run(fake, tmp_path / "s.sock", ["thumb"])
    assert fake.thumb_requests == []
    assert "missing operand" in h.err.getvalue()


async def test_thumb_output_flag_without_value_errors(tmp_path: Path):
    fake = _FakeInventory()
    h = await _run(fake, tmp_path / "s.sock", ["thumb MyAvatar -o"])
    assert fake.thumb_requests == []
    assert "-o" in h.err.getvalue()


async def test_exit_signals_stop(tmp_path: Path):
    fake = _FakeInventory()
    server = Server([fake])
    socket_path = tmp_path / "s.sock"
    await server.start(path=str(socket_path))
    try:
        async with InventoryClient(str(socket_path)) as client:
            shell = InventoryShell(client, out=io.StringIO(), err=io.StringIO())
            assert await shell.execute("exit") is False
            assert await shell.execute("ls") is True
    finally:
        server.close()
        await server.wait_closed()


# --- completion ---------------------------------------------------------


async def _complete(fake: _FakeInventory, socket_path: Path, text: str) -> list[str]:
    server = Server([fake])
    await server.start(path=str(socket_path))
    try:
        async with InventoryClient(str(socket_path)) as client:
            shell = InventoryShell(client, out=io.StringIO(), err=io.StringIO())
            return [t for t, _ in await shell.complete(text)]
    finally:
        server.close()
        await server.wait_closed()


async def test_complete_command_names(tmp_path: Path):
    fake = _FakeInventory()
    candidates = await _complete(fake, tmp_path / "s.sock", "c")
    assert set(candidates) == {"cd", "cp"}


async def test_complete_paths_for_ls(tmp_path: Path):
    fake = _FakeInventory()
    candidates = await _complete(fake, tmp_path / "s.sock", "ls ")
    assert set(candidates) == {"Avatars/", "MyAvatar"}


async def test_complete_cd_offers_directories_only(tmp_path: Path):
    fake = _FakeInventory()
    candidates = await _complete(fake, tmp_path / "s.sock", "cd ")
    assert candidates == ["Avatars/"]


async def test_complete_paths_for_cp_and_rm(tmp_path: Path):
    fake = _FakeInventory()
    assert await _complete(fake, tmp_path / "s.sock", "cp Av") == ["Avatars/"]
    assert await _complete(fake, tmp_path / "s.sock", "rm My") == ["MyAvatar"]
    # cp completes the destination operand too.
    assert "Avatars/" in await _complete(fake, tmp_path / "s.sock", "cp MyAvatar Av")


async def test_complete_recursive_flag(tmp_path: Path):
    fake = _FakeInventory()
    assert await _complete(fake, tmp_path / "s.sock", "rm -") == ["-r"]
    assert await _complete(fake, tmp_path / "s.sock", "cp -") == ["-r"]


async def test_complete_paths_for_thumb_offers_items(tmp_path: Path):
    fake = _FakeInventory()
    # thumb completes any entry (items have thumbnails), not directories only.
    assert set(await _complete(fake, tmp_path / "s.sock", "thumb ")) == {
        "Avatars/",
        "MyAvatar",
    }
