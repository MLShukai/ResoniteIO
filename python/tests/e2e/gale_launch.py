"""E2E: a Gale / Steam direct launch (no injected queue env) still gets frames.

Regression guard for the Camera IPC queue-agreement bug. When Resonite is
started **directly from Gale or Steam** — not through ``resoio.launch`` — the
ResoniteIO launcher never runs, so ``RESONITE_IO_CAMERA_QUEUE`` is **not**
injected into the environment. The fix under test makes both the engine mod and
the renderer plugin fall back to the *same fixed default queue name* in that
case, so they still agree on one queue and Camera frames flow.

The old, broken behaviour: with the env unset the engine self-generated a random
token at runtime, which the renderer (a Wine child started independently) never
inherited. The two then bound *different* /dev/shm IPC queues, the renderer
delivered frames onto a queue nobody read, and ``CameraClient.shot`` hung
forever (client freeze). So:

    * one delivered Camera frame == the engine actually rendered AND the frame
      travelled through the IPC queue to the renderer and back to us, which can
      only happen if both ends bound the *same* queue. A single non-empty frame
      is therefore proof of queue agreement.
    * if this test hangs / times out instead, the engine and renderer are on
      different queues again — either runtime self-generation crept back in or
      the fixed-default fallback is broken on one side.

To faithfully reproduce a Gale launch we cannot use ``resoio.launch`` (it now
*always* injects a queue token). Instead we drive the launcher's own
``_build_command`` with ``camera_queue=None`` — exactly the mod-loaded
(non-vanilla) umu/doorstop chain Gale uses, minus the queue env — and PID-diff
the engine + renderer into existence the same way ``launch`` does. We also pop
``RESONITE_IO_CAMERA_QUEUE`` out of the child env defensively, so a value
lingering in the container environment cannot mask a self-generation regression.

Like ``tests/e2e/launcher.py`` and ``tests/e2e/multi_instance.py`` this manages
Resonite's lifecycle itself (the no-env startup *is* the scenario), so it does
**not** use the ``resonite_session`` fixture. ``RESONITE_EXE`` / ``MOD_PATH``
come from the container environment (compose); the ``require_mod_deployed``
autouse fixture skips when the mod is not deployed.
"""

from __future__ import annotations

import asyncio
import glob
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import psutil
from PIL import Image

from resoio import CameraClient, ConnectionClient, terminate
from resoio._client import socket_path_for_pid
from resoio.launcher import (
    _CAMERA_QUEUE_ENV,
    _build_command,
    _find_engine_pids,
    _find_renderer_pids,
    _wait_for_new,
)
from tests.helpers import mark_e2e

ARTIFACT_ROOT = Path(__file__).parent / "e2e_artifacts"
SOCKET_DIR = Path.home() / ".resonite-io"

_LAUNCH_TIMEOUT_S = 120.0
_SOCKET_APPEAR_TIMEOUT_S = 120.0
_KILL_TIMEOUT_S = 30.0
_POLL_S = 1.0


def _resonite_exe() -> str:
    return os.environ.get("RESONITE_EXE", "/opt/resonite/Resonite.exe")


def _install_dir() -> str:
    return os.path.dirname(os.path.realpath(_resonite_exe()))


def _mod_path() -> str:
    return os.environ.get("MOD_PATH", "/workspace/gale")


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
    """Ping the instance on its socket, then capture one Camera frame from it.

    The ``shot`` is the load-bearing assertion: it only returns once a frame has
    made the engine -> IPC queue -> renderer -> client round trip, so it hangs
    (and the test times out) if the engine and renderer bound different queues.
    """
    async with ConnectionClient(socket_path=str(socket_path)) as conn:
        await conn.ping("gale-launch")
    async with CameraClient(socket_path=str(socket_path)) as cam:
        frame = await cam.shot()
    rgb = np.ascontiguousarray(frame.pixels[..., :3])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgb, mode="RGB").save(out_path)
    return rgb


def _spawn_gale_like(install_dir: str) -> subprocess.Popen[bytes]:
    """Start the mod-loaded umu/doorstop chain **without** a queue env token.

    Mirrors a Gale / Steam direct launch: the same non-vanilla command
    ``resoio.launch`` builds, except ``camera_queue=None`` so no
    ``RESONITE_IO_CAMERA_QUEUE`` is injected. The env var is also popped from the
    child environment defensively, so a value left over in the container cannot
    hide a self-generation regression. Spawned detached like ``launch`` does.
    """
    argv, env, log_path = _build_command(
        _resonite_exe(),
        install_dir,
        _mod_path(),
        vanilla=False,
        extra_args=(),
        camera_queue=None,
    )
    # Faithful Gale launch: the queue env must be genuinely absent so the mod has
    # to fall back to the fixed default queue name (the behaviour under test).
    env.pop(_CAMERA_QUEUE_ENV, None)
    assert _CAMERA_QUEUE_ENV not in env, (
        f"{_CAMERA_QUEUE_ENV} must be unset to simulate a Gale launch"
    )

    stdout: object = subprocess.DEVNULL
    if log_path is not None:
        stdout = open(log_path, "ab")
    try:
        return subprocess.Popen(  # noqa: S603 - argv built from validated paths
            argv,
            cwd=install_dir,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=stdout,  # pyright: ignore[reportArgumentType]
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    finally:
        if log_path is not None:
            stdout.close()  # pyright: ignore[reportAttributeAccessIssue]


class TestGaleLaunch:
    @mark_e2e
    def test_direct_gale_launch_without_queue_env_still_delivers_frames(self) -> None:
        install = _install_dir()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = ARTIFACT_ROOT / f"gale_launch_{timestamp}"

        # Clean slate: stop anything left over and drop stale sockets.
        terminate()
        for sock in glob.glob(str(SOCKET_DIR / "resonite-*.sock")):
            Path(sock).unlink(missing_ok=True)

        # Snapshot existing engine/renderer PIDs so _wait_for_new can pick out
        # the ones this Gale-like launch spawns by set difference.
        before_engines = set(_find_engine_pids(install))
        before_renderers = set(_find_renderer_pids(install))

        _spawn_gale_like(install)

        deadline = time.monotonic() + _LAUNCH_TIMEOUT_S
        resonite_pid = _wait_for_new(
            lambda: _find_engine_pids(install),
            before_engines,
            "engine",
            deadline,
            _POLL_S,
        )
        renderer_pid = _wait_for_new(
            lambda: _find_renderer_pids(install),
            before_renderers,
            "renderer",
            deadline,
            _POLL_S,
        )
        try:
            print(f"gale-like launch: engine={resonite_pid} renderer={renderer_pid}")
            assert resonite_pid > 0
            assert renderer_pid > 0
            assert resonite_pid != renderer_pid
            assert psutil.pid_exists(resonite_pid)
            assert psutil.pid_exists(renderer_pid)

            # The engine binds its pid-named UDS once GrpcHost is up.
            sock = _wait_for_pid_socket(resonite_pid, _SOCKET_APPEAR_TIMEOUT_S)
            assert sock is not None, "engine never bound its UDS after Gale launch"

            # The core assertion: a frame arrives even though no queue env was
            # injected. One non-empty RGB frame == engine and renderer agreed on
            # the (default) IPC queue; a hang here means they did not.
            frame = asyncio.run(_ping_and_shot(sock, out_dir / "gale_launch.png"))
            assert frame.shape[2] == 3
            assert frame.size > 0
        finally:
            terminate(resonite_pid, renderer_pid)

        # The host process table drains: both processes are gone.
        deadline = time.monotonic() + _KILL_TIMEOUT_S
        while time.monotonic() < deadline:
            if not psutil.pid_exists(resonite_pid) and not psutil.pid_exists(
                renderer_pid
            ):
                break
            time.sleep(_POLL_S)
        assert not psutil.pid_exists(resonite_pid)
        assert not psutil.pid_exists(renderer_pid)
