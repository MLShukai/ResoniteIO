"""E2E: graceful shutdown + forced terminate against a live Resonite.

Validates the real stop flow against a Resonite started in the dev container via
``resoio.launch``:

1. ``Info.GetServerInfo`` reports the engine's host PID (`resonite_pid`) and the
   renderer's (`renderer_pid`). We cross-check `renderer_pid` against the
   container's actual ``Renderite.Renderer.exe`` PID (from ``pgrep``) to
   confirm the engine reports real host kernel PIDs (the engine runs natively on
   Linux, ``is_wine=false``). NOTE: the engine's own `resonite_pid` is observed
   only — it does NOT appear in ``pgrep -f Resonite.exe`` because that name
   matches the Steam/Proton launch wrappers, not the native engine process.
2. ``shutdown()`` reads the engine PID from Info and sends ``Lifecycle.Shutdown``;
   the engine ACKs and is *asked* to quit. Graceful shutdown is best-effort: on
   Linux / in the dev container FrooxEngine frequently hangs during teardown and
   the engine never exits on its own (issue #49). So we give it a bounded grace
   window (a graceful exit is allowed but not required), then force the kill with
   :func:`resoio.terminate`. Either way the engine PID must be gone at the end.

This exercises the real operational pattern — ``resoio shutdown`` to ask the
engine nicely, ``resoio terminate`` to guarantee the process is gone — driving
both public functions from inside the container against the host Resonite.
"""

from __future__ import annotations

import asyncio
import subprocess
import time
from datetime import datetime
from pathlib import Path

import psutil

from resoio.info import get_server_info
from resoio.launcher import terminate
from resoio.lifecycle import shutdown
from tests.helpers import mark_e2e, save_camera_shot

ARTIFACT_ROOT = Path(__file__).parent / "e2e_artifacts"

# Best-effort window for the engine to quit on its own after a graceful
# Lifecycle.Shutdown. On Linux it usually hangs and never exits, so this is
# intentionally short — we fall back to a forced terminate when it elapses.
_GRACE_TIMEOUT_S = 30.0
# After SIGTERM → SIGKILL the engine should disappear quickly; this is the final
# settle window for the kernel to reap it.
_FORCE_TIMEOUT_S = 15.0
_POLL_S = 1.0


def _pgrep(pattern: str) -> list[int]:
    """Return the PIDs whose command line matches ``pattern`` (``pgrep -af``).

    ``pgrep`` exits 1 when nothing matches; that is the "no process" case, not
    an error, so it is mapped to an empty list. Any other non-zero exit is a
    real failure and is surfaced.
    """
    proc = subprocess.run(
        ["pgrep", "-af", pattern],
        check=False,
        text=True,
        capture_output=True,
        timeout=30.0,
    )
    if proc.returncode == 1:
        return []
    if proc.returncode != 0:
        raise AssertionError(
            f"pgrep -af {pattern!r} failed (rc={proc.returncode}): {proc.stderr!r}"
        )
    pids: list[int] = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if line:
            pids.append(int(line.split(None, 1)[0]))
    return pids


def _engine_alive(pid: int) -> bool:
    """Return whether ``pid`` is a live, non-zombie process.

    This is the direct ``kill -0``-style liveness check the issue uses to decide
    whether the engine actually exited (a zombie that has died but not yet been
    reaped is treated as gone).
    """
    try:
        return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


def _wait_until_dead(pid: int, timeout: float) -> bool:
    """Poll until ``pid`` is gone; return True if it died within
    ``timeout``."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _engine_alive(pid):
            return True
        time.sleep(_POLL_S)
    return not _engine_alive(pid)


class TestLifecycle:
    @mark_e2e
    def test_shutdown_acks_then_terminate_stops_engine(
        self, resonite_session: Path
    ) -> None:
        del resonite_session  # fixture only manages the Resonite lifecycle

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = ARTIFACT_ROOT / f"lifecycle_{timestamp}"

        async def scenario() -> None:
            info = await get_server_info()
            print(
                f"info: resonite_pid={info.resonite_pid} "
                f"renderer_pid={info.renderer_pid} is_wine={info.is_wine}"
            )
            assert info.is_wine is False
            assert info.resonite_pid > 0
            assert info.renderer_pid > 0

            host_resonite = _pgrep("Resonite.exe")
            host_renderite = _pgrep("Renderite.Renderer.exe")
            print(f"host: resonite_wrappers={host_resonite} renderite={host_renderite}")
            assert _engine_alive(info.resonite_pid), "engine not running pre-shutdown"
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

            # Reference-only artifact: grab the live view via the in-engine
            # Camera before shutdown (best-effort; never fails the test).
            await save_camera_shot(out_dir / "before_shutdown.png")

            pid = await shutdown()
            print(f"shutdown returned pid={pid}")
            assert pid == info.resonite_pid

            # Graceful shutdown only *asks* the engine to quit. On Linux / in the
            # container it frequently hangs and never exits on its own (issue
            # #49), so give it a bounded grace window (graceful exit allowed but
            # not required), then force the kill with terminate(). This is the
            # real operational flow: shutdown to ask nicely, terminate to ensure.
            if _wait_until_dead(info.resonite_pid, _GRACE_TIMEOUT_S):
                print("engine exited gracefully after shutdown")
            else:
                print(
                    f"engine still alive {_GRACE_TIMEOUT_S:.0f}s after shutdown "
                    "(graceful quit hung — known Linux behavior); forcing terminate"
                )
                killed = terminate(info.resonite_pid, info.renderer_pid)
                print(
                    f"terminate killed resonite_pid={killed.resonite_pid} "
                    f"renderer_pid={killed.renderer_pid}"
                )

            # Whichever path ran, the engine process must be gone now.
            assert _wait_until_dead(info.resonite_pid, _FORCE_TIMEOUT_S), (
                f"engine pid {info.resonite_pid} still alive after shutdown + terminate"
            )

        asyncio.run(scenario())
