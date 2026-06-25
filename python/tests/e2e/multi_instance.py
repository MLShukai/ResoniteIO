"""E2E: run two real Resonite instances side by side without interference.

The multi-instance contract end-to-end. Launches two labelled instances
(``--name a`` / ``--name b``), each getting its own WINEPREFIX + DataPath and a
private Camera IPC queue token, then proves they are independent:

* both engines come up as distinct host processes with distinct UDS sockets;
* a ``Connection.Ping`` reaches each instance on its own socket;
* both instances deliver a Camera frame — if the renderer IPC queues had
  collided (the old fixed queue name), one engine would starve or receive the
  other's frames, so two successful independent shots is the cross-talk guard;
* ``terminate_all`` then stops every instance and the host process table drains.

Like ``tests/e2e/launcher.py`` this manages Resonite's lifecycle itself (the
feature under test), so it does **not** use the ``resonite_session`` fixture.
Each labelled instance bootstraps a *fresh* WINEPREFIX (first-run Proton setup),
so the two launches are serialised and given a generous timeout; this scenario is
opt-in (``@mark_e2e``) and intentionally heavy.
"""

from __future__ import annotations

import asyncio
import glob
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import psutil
from PIL import Image

from resoio import launch, terminate_all
from resoio._client import socket_path_for_pid
from tests.helpers import mark_e2e

ARTIFACT_ROOT = Path(__file__).parent / "e2e_artifacts"
SOCKET_DIR = Path.home() / ".resonite-io"

_LAUNCH_TIMEOUT_S = 240.0
_SOCKET_APPEAR_TIMEOUT_S = 120.0
_KILL_TIMEOUT_S = 30.0
_POLL_S = 1.0


def _wait_for_pid_socket(pid: int, timeout_s: float) -> Path | None:
    """Wait for the engine ``pid``'s conventional ``resonite-{pid}.sock``."""
    target = Path(socket_path_for_pid(pid))
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if target.exists():
            return target
        time.sleep(_POLL_S)
    return None


async def _ping_and_shot(socket_path: Path, out_path: Path) -> np.ndarray:
    """Ping an instance on its own socket and capture one Camera frame from
    it."""
    from resoio import CameraClient, ConnectionClient

    async with ConnectionClient(socket_path=str(socket_path)) as conn:
        await conn.ping("multi-instance")
    async with CameraClient(socket_path=str(socket_path)) as cam:
        frame = await cam.shot()
    rgb = np.ascontiguousarray(frame.pixels[..., :3])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgb, mode="RGB").save(out_path)
    return rgb


class TestMultiInstance:
    @mark_e2e
    def test_two_named_instances_run_isolated_then_terminate_all(self) -> None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = ARTIFACT_ROOT / f"multi_{timestamp}"

        # Clean slate: stop anything left over and drop stale sockets.
        terminate_all()
        for sock in glob.glob(str(SOCKET_DIR / "resonite-*.sock")):
            Path(sock).unlink(missing_ok=True)

        # Serialise the two launches: each label bootstraps its own fresh
        # WINEPREFIX, and concurrent first-run Proton setup can race.
        a = launch(name="a", wait_timeout=_LAUNCH_TIMEOUT_S)
        try:
            b = launch(name="b", wait_timeout=_LAUNCH_TIMEOUT_S)
        except Exception:
            terminate_all()
            raise

        try:
            print(f"a: engine={a.resonite_pid} renderer={a.renderer_pid}")
            print(f"b: engine={b.resonite_pid} renderer={b.renderer_pid}")

            # Four distinct host processes (no PID shared between the instances).
            pids = {a.resonite_pid, a.renderer_pid, b.resonite_pid, b.renderer_pid}
            assert len(pids) == 4, f"expected 4 distinct PIDs, got {pids}"
            assert all(psutil.pid_exists(p) for p in pids)

            # Each engine bound its own pid-named UDS.
            sock_a = _wait_for_pid_socket(a.resonite_pid, _SOCKET_APPEAR_TIMEOUT_S)
            sock_b = _wait_for_pid_socket(b.resonite_pid, _SOCKET_APPEAR_TIMEOUT_S)
            assert sock_a is not None, "instance a never bound its UDS"
            assert sock_b is not None, "instance b never bound its UDS"
            assert sock_a != sock_b

            # Both instances independently answer a ping and deliver a Camera
            # frame on their own socket. Two successful shots = the renderer
            # queues did not collide (the core multi-instance guarantee).
            frame_a = asyncio.run(_ping_and_shot(sock_a, out_dir / "instance_a.png"))
            frame_b = asyncio.run(_ping_and_shot(sock_b, out_dir / "instance_b.png"))
            assert frame_a.shape[2] == 3
            assert frame_b.shape[2] == 3
            assert frame_a.size > 0 and frame_b.size > 0
        finally:
            results = terminate_all()
            print(f"terminate_all killed {len(results)} instance(s)")

        # The host process table drains: every instance is gone.
        deadline = time.monotonic() + _KILL_TIMEOUT_S
        while time.monotonic() < deadline:
            if not any(psutil.pid_exists(p) for p in pids):
                break
            time.sleep(_POLL_S)
        assert not any(psutil.pid_exists(p) for p in pids)

        # Idempotent: a second sweep finds nothing.
        assert terminate_all() == []
