"""E2E: graceful terminate against a live Resonite + Info host-PID cross-check.

Validates the Lifecycle/terminate feature against a real Resonite started via the
host-agent:

1. ``Info.GetServerInfo`` reports the engine's host PID (`resonite_pid`) and the
   renderer's (`renderer_pid`). We cross-check `renderer_pid` against the host's
   actual ``Renderite.Renderer.exe`` PID (from the host-agent ``status``) to
   confirm the engine reports real host kernel PIDs (the engine runs natively on
   Linux, ``is_wine=false``). NOTE: the engine's own `resonite_pid` is observed
   only — it does NOT appear in ``pgrep -f Resonite.exe`` because that name
   matches the Steam/Proton launch wrappers, not the native engine process.
2. ``terminate()`` reads the engine PID from Info and sends ``Lifecycle.Shutdown``;
   the engine quits itself and Steam/Proton reaps the renderer + wrappers. We poll
   the host until the whole Resonite process group is gone.

``terminate`` is a pure gRPC call (no OS signals), so this drives the real public
function from inside the container against the host Resonite.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import time
from datetime import datetime
from pathlib import Path

from resoio.info import get_server_info
from resoio.lifecycle import terminate
from tests.helpers import mark_e2e

REPO_ROOT: Path = Path(__file__).resolve().parents[3]
ARTIFACT_ROOT = Path(__file__).parent / "e2e_artifacts"

# Shutdown needs time to run FrooxEngine's shutdown tasks and let Steam reap the
# whole process group.
_SHUTDOWN_TIMEOUT_S = 90.0
_SHUTDOWN_POLL_S = 1.0


def _screenshot(out_dir: Path, name: str) -> None:
    """Grab the host desktop into ``out_dir/name`` via the host-agent
    bridge."""
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


def _host_status() -> tuple[list[int], list[int], bool]:
    """Return ``(resonite_pids, renderite_pids, running)`` from the host-agent.

    These are the host's *actual* Linux PIDs (the host-agent runs ``pgrep`` on the
    host). ``resonite_pids`` are the Steam/Proton launch wrappers (their command
    line contains ``Resonite.exe``), not the native engine process — used here
    only to confirm the process group is gone after shutdown. ``renderite_pids``
    is the real renderer, cross-checked against the Info ``renderer_pid``.
    """
    proc = subprocess.run(
        ["python3", "scripts/resonite_cli.py", "status"],
        cwd=REPO_ROOT,
        check=True,
        text=True,
        capture_output=True,
        timeout=30.0,
    )
    data = json.loads(proc.stdout)["data"]
    resonite = [int(p["pid"]) for p in data["resonite"]]
    renderite = [int(p["pid"]) for p in data["renderite"]]
    return resonite, renderite, bool(data["running"])


class TestLifecycle:
    @mark_e2e
    def test_terminate_exits_engine_and_info_reports_host_pids(
        self, resonite_session: Path
    ) -> None:
        del resonite_session  # fixture only manages the Resonite lifecycle

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = ARTIFACT_ROOT / f"lifecycle_{timestamp}"
        out_dir.mkdir(parents=True, exist_ok=True)

        async def scenario() -> None:
            info = await get_server_info()
            print(
                f"info: resonite_pid={info.resonite_pid} "
                f"renderer_pid={info.renderer_pid} is_wine={info.is_wine}"
            )
            assert info.is_wine is False
            assert info.resonite_pid > 0
            assert info.renderer_pid > 0

            host_resonite, host_renderite, running = _host_status()
            print(
                f"host: resonite_wrappers={host_resonite} "
                f"renderite={host_renderite} running={running}"
            )
            assert running is True
            # Strong cross-check: the engine-reported renderer PID is the real
            # host renderer PID, proving Info carries real host kernel PIDs.
            assert info.renderer_pid in host_renderite, (
                f"Info renderer_pid {info.renderer_pid} not among host "
                f"Renderite.Renderer.exe PIDs {host_renderite}"
            )
            # The engine's own PID is intentionally absent from the by-name
            # Resonite.exe matches (those are the Proton wrappers) — observe only.
            print(
                "engine resonite_pid in by-name Resonite.exe matches: "
                f"{info.resonite_pid in host_resonite} (expected False — wrappers)"
            )

            _screenshot(out_dir, "before_terminate.png")

            pid = await terminate()
            print(f"terminate returned pid={pid}")
            assert pid == info.resonite_pid

            # The window vanishes on shutdown, so we confirm exit by the host
            # process group disappearing (not by a post-shutdown screenshot).
            deadline = time.monotonic() + _SHUTDOWN_TIMEOUT_S
            while time.monotonic() < deadline:
                _, _, still_running = _host_status()
                if not still_running:
                    print("engine exited after terminate")
                    return
                time.sleep(_SHUTDOWN_POLL_S)
            raise AssertionError(
                f"engine did not exit within {_SHUTDOWN_TIMEOUT_S:.0f}s of terminate"
            )

        asyncio.run(scenario())
