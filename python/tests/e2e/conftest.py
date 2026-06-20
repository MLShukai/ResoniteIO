"""Fixtures owning the in-container live Resonite lifecycle for e2e tests."""

from __future__ import annotations

import asyncio
import os
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from resoio.connection import wait_for_ready

REPO_ROOT: Path = Path(__file__).resolve().parents[2]
SOCKET_DIR: Path = Path.home() / ".resonite-io"
SOCKET_GLOB = "resonite-*.sock"
SOCKET_APPEAR_TIMEOUT_S = 120.0
SOCKET_APPEAR_POLL_S = 1.0
POST_SOCKET_STARTUP_SETTLE_S = 30.0
# The Gale profile e2e starts Resonite from. `just resonite-launch` reads the mod
# (BepInEx + ResoniteIO plugin) from here; without a deployed mod no UDS is bound
# and every scenario would hard-fail on the socket-wait timeout instead of
# skipping cleanly.
GALE_DIR: Path = Path(os.environ.get("GalePath", "/workspace/gale"))


def _run_just(
    *args: str, check: bool = True, timeout: float = 60.0
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["just", *args],
        cwd=REPO_ROOT,
        check=check,
        text=True,
        capture_output=True,
        timeout=timeout,
    )


def _purge_stale_sockets(directory: Path) -> None:
    # Mod's AppDomain.ProcessExit cleanup is skipped when `just resonite-stop`
    # SIGKILLs the process, so stale sockets can outlive the previous run and
    # cause ConnectionRefusedError on the next connect attempt.
    if not directory.is_dir():
        return
    for sock in directory.glob(SOCKET_GLOB):
        sock.unlink(missing_ok=True)


@pytest.fixture(autouse=True)
def require_mod_deployed() -> None:
    # `just resonite-launch` boots Resonite from the ./gale profile; without the
    # mod deployed there the GrpcHost never binds the UDS, so skip rather than
    # let resonite_session hard-fail on the socket-wait timeout.
    if not (GALE_DIR / "BepInEx").is_dir():
        pytest.skip(
            f"mod not deployed to {GALE_DIR} (no BepInEx dir); run `just deploy-mod`"
        )


@pytest.fixture
def resonite_session() -> Iterator[Path]:
    """Yield the bound UDS path with ``RESONITE_IO_SOCKET`` pointing at it.

    Each test starts from a clean slate: any leftover Resonite from a
    crashed prior run or external launch is force-stopped before the
    fixture starts its own instance.
    """
    # Pre-stop: ensure no stray Resonite is running from a prior crash or
    # an out-of-band launch. ``resonite-stop`` is a no-op when nothing is
    # running, so this is safe to always invoke.
    _run_just("resonite-stop", check=False, timeout=30.0)
    _purge_stale_sockets(SOCKET_DIR)
    # Clear any explicit override (e.g. leaked from a crashed prior test) so the
    # wait resolves by globbing SOCKET_DIR rather than honouring a stale path.
    os.environ.pop("RESONITE_IO_SOCKET", None)
    # resonite-launch (resoio launch) blocks until the engine + renderer
    # processes appear, so allow more time than the background start it replaced.
    _run_just("resonite-launch", "--timeout", "120", timeout=140.0)
    try:
        # wait_for_ready polls Connection.Ping — a stronger readiness signal
        # than the socket file merely appearing — and resolves through
        # resolve_socket_path, which skips sockets whose engine PID is gone, so
        # a stale leftover can no longer be picked as the (wrong) target.
        socket_path = Path(
            asyncio.run(
                wait_for_ready(
                    timeout=SOCKET_APPEAR_TIMEOUT_S,
                    interval=SOCKET_APPEAR_POLL_S,
                )
            )
        )
        os.environ["RESONITE_IO_SOCKET"] = str(socket_path)
        # The mod binds the UDS before the focused home world is fully loaded.
        # Give the whole e2e suite one shared startup settle window so modality
        # tests do not race against the loading screen or partially initialized
        # world state.
        time.sleep(POST_SOCKET_STARTUP_SETTLE_S)
        yield socket_path
    finally:
        # stop is best-effort (process may already be dead); the purge below
        # covers SIGKILL paths where the mod's ProcessExit cleanup didn't run.
        _run_just("resonite-stop", check=False, timeout=30.0)
        os.environ.pop("RESONITE_IO_SOCKET", None)
        _purge_stale_sockets(SOCKET_DIR)
