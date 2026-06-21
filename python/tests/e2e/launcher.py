"""E2E: launch + terminate a real Resonite via umu-launcher.

Drives the public :func:`resoio.launch` / :func:`resoio.terminate` against a
real in-container Resonite (no gRPC): launch spawns the umu-run chain and
PID-diffs the engine + renderer into existence, we confirm both are live host
processes (and grab a Camera screenshot once the mod binds its socket, proving
the engine actually rendered), then terminate kills both by PID and we poll the
host until they are gone. A second terminate confirms idempotence.

Unlike the other e2e scenarios this one manages Resonite's lifecycle itself
(launch/terminate are the feature under test), so it does **not** use the
``resonite_session`` fixture. ``RESONITE_EXE`` / ``MOD_PATH`` come from the
container environment (compose); the ``require_mod_deployed`` autouse fixture
skips when the mod is not deployed.
"""

from __future__ import annotations

import asyncio
import glob
import os
import time
from datetime import datetime
from pathlib import Path

import psutil

from resoio import launch, terminate
from resoio.launcher import _find_engine_pids, _find_renderer_pids
from tests.helpers import mark_e2e, save_camera_shot

ARTIFACT_ROOT = Path(__file__).parent / "e2e_artifacts"
SOCKET_DIR = Path.home() / ".resonite-io"

_SOCKET_APPEAR_TIMEOUT_S = 90.0
_KILL_TIMEOUT_S = 30.0
_POLL_S = 1.0


def _install_dir() -> str:
    exe = os.environ.get("RESONITE_EXE", "/opt/resonite/Resonite.exe")
    return os.path.dirname(os.path.realpath(exe))


def _wait_for_socket(timeout_s: float) -> Path | None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        socks = sorted(SOCKET_DIR.glob("resonite-*.sock"))
        if socks:
            return socks[0]
        time.sleep(_POLL_S)
    return None


class TestLauncher:
    @mark_e2e
    def test_launch_returns_both_pids_then_terminate_kills_them(self) -> None:
        install = _install_dir()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = ARTIFACT_ROOT / f"launcher_{timestamp}"

        # Clean slate: kill any instance left over from a prior run.
        terminate()
        for sock in glob.glob(str(SOCKET_DIR / "resonite-*.sock")):
            Path(sock).unlink(missing_ok=True)

        result = launch(wait_timeout=120.0)
        try:
            print(
                f"launched resonite_pid={result.resonite_pid} "
                f"renderer_pid={result.renderer_pid}"
            )
            assert result.resonite_pid > 0
            assert result.renderer_pid > 0
            assert result.resonite_pid != result.renderer_pid

            # Both are live host processes matching the engine/renderer matchers.
            assert psutil.pid_exists(result.resonite_pid)
            assert psutil.pid_exists(result.renderer_pid)
            assert _find_engine_pids(install) == [result.resonite_pid]
            assert _find_renderer_pids(install) == [result.renderer_pid]

            # Relaunching while running is refused (single-instance guard).
            try:
                launch(wait_timeout=5.0)
                raise AssertionError("expected launch to refuse a second instance")
            except Exception as exc:  # noqa: BLE001
                assert "already running" in str(exc)

            # Once the mod binds its UDS the engine is rendering; grab a shot.
            sock = _wait_for_socket(_SOCKET_APPEAR_TIMEOUT_S)
            assert sock is not None, "engine never bound its UDS after launch"
            assert sock.name == f"resonite-{result.resonite_pid}.sock"
            asyncio.run(save_camera_shot(out_dir / "after_launch.png"))
        finally:
            killed = terminate(result.resonite_pid, result.renderer_pid)
            print(f"terminated {killed}")

        # Poll the host until both processes are gone.
        deadline = time.monotonic() + _KILL_TIMEOUT_S
        while time.monotonic() < deadline:
            if not _find_engine_pids(install) and not _find_renderer_pids(install):
                break
            time.sleep(_POLL_S)
        assert _find_engine_pids(install) == []
        assert _find_renderer_pids(install) == []
        assert not psutil.pid_exists(result.resonite_pid)

        # Idempotent: terminating again finds nothing.
        again = terminate()
        assert again.resonite_pid == 0
        assert again.renderer_pid == 0
