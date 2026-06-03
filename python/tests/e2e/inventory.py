"""E2E: drive the Inventory modality against a live Resonite.

Exercises the bash-like inventory ops (mkdir / ls / cp -r / mv / rm -r) end
to end against the user's real cloud inventory, scoped to a dedicated test
folder ``/Inventory/__resoio_e2e__`` that is recursively removed in
``finally`` so the real inventory is left untouched. Leaf ``cp`` and
``spawn`` are opportunistic: they use whatever OBJECT record already exists
at the inventory root and are skipped (logged) if none is present. After a
successful spawn the host desktop is screenshotted via the host-agent so the
spawned item can be confirmed visually.

Like every file under ``tests/e2e/`` this requires the host-side
``just host-agent`` daemon plus a live, signed-in Resonite client; the
``require_host_agent`` autouse fixture skips otherwise.
"""

from __future__ import annotations

import asyncio
import subprocess
import time
from datetime import datetime
from pathlib import Path

import grpclib
from grpclib.const import Status

from resoio.inventory import InventoryClient, InventoryEntryKind, InventoryListing
from tests.helpers import mark_e2e

REPO_ROOT: Path = Path(__file__).resolve().parents[3]
ARTIFACT_ROOT = Path(__file__).parent / "e2e_artifacts"

_TEST_DIR = "/Inventory/__resoio_e2e__"

# Inventory bridge is FAILED_PRECONDITION until the engine has booted and the
# user is signed in. Mirror context_menu.py's readiness poll.
_READY_TIMEOUT_S = 120.0
_READY_RETRY_INTERVAL_S = 2.0
_HOME_LOAD_SETTLE_S = 20.0
_SETTLE_S = 0.5


def _screenshot(out_dir: Path, name: str) -> None:
    subprocess.run(
        [
            "python3",
            "scripts/resonite_cli.py",
            "screenshot",
            "--output",
            str(out_dir / name),
        ],
        cwd=REPO_ROOT,
        check=True,
        text=True,
        capture_output=True,
        timeout=30.0,
    )


class TestInventory:
    @mark_e2e
    def test_folder_lifecycle_and_spawn(self, resonite_session: Path) -> None:
        del resonite_session  # fixture only manages Resonite lifecycle

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = ARTIFACT_ROOT / f"inventory_{timestamp}"
        out_dir.mkdir(parents=True, exist_ok=True)
        log_lines: list[str] = []

        def record(line: str) -> None:
            log_lines.append(line)
            print(line)

        async def wait_for_ready() -> InventoryListing:
            deadline = time.monotonic() + _READY_TIMEOUT_S
            while True:
                try:
                    async with InventoryClient() as inv:
                        return await inv.list("/Inventory")
                except grpclib.exceptions.GRPCError as e:
                    if e.status != Status.FAILED_PRECONDITION:
                        raise
                    if time.monotonic() >= deadline:
                        raise AssertionError(
                            f"Inventory bridge never became ready within {_READY_TIMEOUT_S:.0f}s "
                            "(is the client signed in?)"
                        ) from e
                    await asyncio.sleep(_READY_RETRY_INTERVAL_S)

        async def scenario() -> None:
            root = await wait_for_ready()
            await asyncio.sleep(_HOME_LOAD_SETTLE_S)
            root = await wait_for_ready()
            record(f"root has {len(root.entries)} entries")

            async with InventoryClient() as inv:
                # Clean any leftover from a previous crashed run.
                try:
                    await inv.remove(_TEST_DIR, recursive=True)
                except grpclib.exceptions.GRPCError as e:
                    if e.status != Status.NOT_FOUND:
                        raise

                try:
                    # mkdir + ls(root): the test dir must appear at the root.
                    await inv.mkdir(_TEST_DIR)
                    root_after = await inv.list("/Inventory")
                    assert any(
                        e.name == "__resoio_e2e__" for e in root_after.entries
                    ), "test dir not visible after mkdir"
                    record("mkdir + ls(root): OK")

                    # nested mkdir + ls(test dir).
                    await inv.mkdir(f"{_TEST_DIR}/sub")
                    await inv.mkdir(f"{_TEST_DIR}/sub/leaf_dir")
                    listing = await inv.list(_TEST_DIR)
                    assert any(e.name == "sub" for e in listing.entries)
                    record("nested mkdir + ls: OK")

                    # cp -r: copy the sub tree, verify the grandchild came along.
                    await inv.copy(
                        f"{_TEST_DIR}/sub", f"{_TEST_DIR}/sub_copy", recursive=True
                    )
                    copied = await inv.list(f"{_TEST_DIR}/sub_copy")
                    assert any(e.name == "leaf_dir" for e in copied.entries), (
                        "cp -r did not copy the subtree"
                    )
                    record("cp -r (recursive folder copy): OK")

                    # mv: rename the copy; old name gone, new name present.
                    await inv.move(f"{_TEST_DIR}/sub_copy", f"{_TEST_DIR}/sub_moved")
                    after_mv = await inv.list(_TEST_DIR)
                    names = {e.name for e in after_mv.entries}
                    assert "sub_moved" in names and "sub_copy" not in names
                    record("mv (folder move): OK")

                    # Opportunistic leaf cp + spawn using a real OBJECT at the root.
                    obj = next(
                        (
                            e
                            for e in root_after.entries
                            if e.kind is InventoryEntryKind.OBJECT
                        ),
                        None,
                    )
                    if obj is None:
                        record("no OBJECT at inventory root; skipping leaf cp + spawn")
                    else:
                        await inv.copy(obj.path, f"{_TEST_DIR}/{obj.name}_copy")
                        record(f"leaf cp of {obj.name!r}: OK")

                        spawned = await inv.spawn(obj.path)
                        assert spawned.spawned_slot_id != ""
                        record(
                            f"spawn {obj.name!r} -> slot {spawned.spawned_slot_id} "
                            f"({spawned.spawned_slot_name!r})"
                        )
                        await asyncio.sleep(_SETTLE_S)
                        _screenshot(out_dir, "spawned.png")
                finally:
                    # rm -r: tear down the whole test dir; root must be clean again.
                    await inv.remove(_TEST_DIR, recursive=True)
                    final_root = await inv.list("/Inventory")
                    assert not any(
                        e.name == "__resoio_e2e__" for e in final_root.entries
                    ), "rm -r left the test dir behind"
                    record("rm -r (cleanup): OK")

        try:
            asyncio.run(scenario())
        finally:
            (out_dir / "log.txt").write_text("\n".join(log_lines), encoding="utf-8")
            print(f"E2E artifacts: {out_dir}")
