"""E2E: drive the Inventory modality against a live Resonite.

Exercises the bash-like inventory ops (mkdir / ls / cp -r / mv / rm -r) end
to end against the user's real cloud inventory, scoped to a dedicated test
folder ``/Inventory/__resoio_e2e__`` that is recursively removed in
``finally`` so the real inventory is left untouched.

It also pins three behaviors that were just bug-fixed in the mod bridge:

* **Hang protection** — every inventory client call in the scenario is
  wrapped in :func:`asyncio.wait_for`, so a regressed server-side hang
  (the original symptom of the URL-encoding bug) fails the test fast
  instead of stalling the whole suite.
* **Spaced-name folder ops** — a folder whose name contains a space is
  created under the test dir and listed back; this used to hang forever at
  the server before the path was URL-encoded.
* **Spawn** — the real ``DragonFruit`` object at ``/Inventory/DragonFruit``
  is spawned (validating the ``ToWorld`` engine-thread fix) and the host
  desktop is screenshotted so the spawned item can be confirmed visually.
* **Link navigation** — a top-level inventory *link* (e.g.
  ``Resonite Essentials``) is listed into, validating the link-following
  fix returns a listing instead of hanging or erroring.

Spawn and link navigation are opportunistic: they use the named records if
present and are skipped (logged) otherwise, so the test is not brittle to
account state. Spawned objects land in the world (the local user's space),
which is expected and not cleaned by inventory ops.

Like every file under ``tests/e2e/`` this requires the host-side
``just host-agent`` daemon plus a live, signed-in Resonite client; the
``require_host_agent`` autouse fixture skips otherwise.
"""

from __future__ import annotations

import asyncio
import subprocess
import time
from collections.abc import Coroutine
from datetime import datetime
from pathlib import Path
from typing import TypeVar

import grpclib
from grpclib.const import Status

from resoio.inventory import InventoryClient, InventoryEntryKind, InventoryListing
from tests.helpers import mark_e2e

REPO_ROOT: Path = Path(__file__).resolve().parents[3]
ARTIFACT_ROOT = Path(__file__).parent / "e2e_artifacts"

_TEST_DIR = "/Inventory/__resoio_e2e__"
# A folder name containing a space: the URL-encoding fix must let this round
# trip without hanging at the server.
_SPACED_DIR_NAME = "with space"
_SPACED_DIR = f"{_TEST_DIR}/{_SPACED_DIR_NAME}"

# A real OBJECT record the test account is known to hold at the inventory
# root; spawning it validates the ToWorld engine-thread fix.
_SPAWN_SOURCE = "/Inventory/DragonFruit"
_SPAWN_SOURCE_NAME = "DragonFruit"

# Inventory bridge is FAILED_PRECONDITION until the engine has booted and the
# user is signed in. Mirror context_menu.py's readiness poll.
_READY_TIMEOUT_S = 120.0
_READY_RETRY_INTERVAL_S = 2.0
_HOME_LOAD_SETTLE_S = 20.0
_SETTLE_S = 0.5

# Every inventory RPC in the scenario must return within this budget. A
# regressed server-side hang (the original URL-encoding / link-following bug)
# trips this and fails the test fast instead of stalling the suite.
_OP_TIMEOUT_S = 20.0

_T = TypeVar("_T")


async def _op(coro: Coroutine[object, object, _T]) -> _T:
    """Await an inventory RPC under a hard timeout (hang regression guard)."""
    return await asyncio.wait_for(coro, timeout=_OP_TIMEOUT_S)


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
                        return await _op(inv.list("/Inventory"))
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
                    await _op(inv.remove(_TEST_DIR, recursive=True))
                except grpclib.exceptions.GRPCError as e:
                    if e.status != Status.NOT_FOUND:
                        raise

                try:
                    # mkdir + ls(root): the test dir must appear at the root.
                    await _op(inv.mkdir(_TEST_DIR))
                    root_after = await _op(inv.list("/Inventory"))
                    assert any(
                        e.name == "__resoio_e2e__" for e in root_after.entries
                    ), "test dir not visible after mkdir"
                    record("mkdir + ls(root): OK")

                    # nested mkdir + ls(test dir).
                    await _op(inv.mkdir(f"{_TEST_DIR}/sub"))
                    await _op(inv.mkdir(f"{_TEST_DIR}/sub/leaf_dir"))
                    listing = await _op(inv.list(_TEST_DIR))
                    assert any(e.name == "sub" for e in listing.entries)
                    record("nested mkdir + ls: OK")

                    # Spaced-name folder (URL-encode fix): mkdir a folder whose
                    # name contains a space, then ls the parent and confirm it
                    # appears by name. This must NOT hang (a regressed encode
                    # would stall the server and trip the _op timeout). The
                    # spaced folder lives under _TEST_DIR so the recursive
                    # teardown below removes it.
                    await _op(inv.mkdir(_SPACED_DIR))
                    after_spaced = await _op(inv.list(_TEST_DIR))
                    assert any(
                        e.name == _SPACED_DIR_NAME for e in after_spaced.entries
                    ), (
                        "spaced-name folder not visible after mkdir (URL-encode regression?)"
                    )
                    record("mkdir + ls of spaced-name folder: OK")

                    # cp -r: copy the sub tree, verify the grandchild came along.
                    await _op(
                        inv.copy(
                            f"{_TEST_DIR}/sub",
                            f"{_TEST_DIR}/sub_copy",
                            recursive=True,
                        )
                    )
                    copied = await _op(inv.list(f"{_TEST_DIR}/sub_copy"))
                    assert any(e.name == "leaf_dir" for e in copied.entries), (
                        "cp -r did not copy the subtree"
                    )
                    record("cp -r (recursive folder copy): OK")

                    # mv: rename the copy; old name gone, new name present.
                    await _op(
                        inv.move(f"{_TEST_DIR}/sub_copy", f"{_TEST_DIR}/sub_moved")
                    )
                    after_mv = await _op(inv.list(_TEST_DIR))
                    names = {e.name for e in after_mv.entries}
                    assert "sub_moved" in names and "sub_copy" not in names
                    record("mv (folder move): OK")

                    # Spawn the real DragonFruit OBJECT (ToWorld engine-thread
                    # fix). Skip-with-log if the account no longer holds it so
                    # the test isn't brittle to account state.
                    dragon = next(
                        (
                            e
                            for e in root_after.entries
                            if e.name == _SPAWN_SOURCE_NAME
                            and e.kind is InventoryEntryKind.OBJECT
                        ),
                        None,
                    )
                    if dragon is None:
                        record(
                            f"no OBJECT named {_SPAWN_SOURCE_NAME!r} at inventory root; "
                            "skipping spawn"
                        )
                    else:
                        spawned = await _op(inv.spawn(_SPAWN_SOURCE))
                        assert spawned.spawned_slot_id != "", (
                            "spawn returned empty slot id (ToWorld regression?)"
                        )
                        assert spawned.spawned_slot_name != "", (
                            "spawn returned empty slot name (ToWorld regression?)"
                        )
                        record(
                            f"spawn {_SPAWN_SOURCE_NAME!r} -> slot {spawned.spawned_slot_id} "
                            f"({spawned.spawned_slot_name!r})"
                        )
                        await asyncio.sleep(_SETTLE_S)
                        _screenshot(out_dir, "spawned.png")

                    # Link navigation (link-following fix): list into a
                    # top-level LINK and confirm it returns a listing without
                    # hanging or erroring. Skip-with-log if no link exists.
                    link = next(
                        (
                            e
                            for e in root_after.entries
                            if e.kind is InventoryEntryKind.LINK
                        ),
                        None,
                    )
                    if link is None:
                        record(
                            "no LINK entry at inventory root; skipping link navigation"
                        )
                    else:
                        linked = await _op(inv.list(link.path))
                        record(
                            f"ls into link {link.name!r} ({link.path}): "
                            f"OK, {len(linked.entries)} entries"
                        )
                finally:
                    # rm -r: tear down the whole test dir (including the
                    # spaced-name folder); root must be clean again.
                    await _op(inv.remove(_TEST_DIR, recursive=True))
                    final_root = await _op(inv.list("/Inventory"))
                    assert not any(
                        e.name == "__resoio_e2e__" for e in final_root.entries
                    ), "rm -r left the test dir behind"
                    record("rm -r (cleanup): OK")

        try:
            asyncio.run(scenario())
        finally:
            (out_dir / "log.txt").write_text("\n".join(log_lines), encoding="utf-8")
            print(f"E2E artifacts: {out_dir}")
