"""Fixtures owning the in-container live Resonite lifecycle for e2e tests."""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from resoio.connection import wait_for_ready
from resoio.launcher import LauncherError, LaunchResult, launch, terminate

SOCKET_DIR: Path = Path.home() / ".resonite-io"
SOCKET_GLOB = "resonite-*.sock"
SOCKET_APPEAR_TIMEOUT_S = 120.0
SOCKET_APPEAR_POLL_S = 1.0
POST_SOCKET_STARTUP_SETTLE_S = 30.0
LAUNCH_TIMEOUT_S = 120.0
# The Gale profile e2e launches Resonite from. ``resoio.launch`` reads the mod
# (BepInEx + ResoniteIO plugin) from here; without a deployed mod no UDS is bound
# and every scenario would hard-fail on the socket-wait timeout instead of
# skipping cleanly.
GALE_DIR: Path = Path(os.environ.get("GalePath", "/workspace/gale"))


def _purge_stale_sockets(directory: Path) -> None:
    # The mod's AppDomain.ProcessExit cleanup is skipped when ``terminate``
    # SIGKILLs the engine, so stale sockets can outlive the previous run and
    # cause ConnectionRefusedError on the next connect attempt.
    if not directory.is_dir():
        return
    for sock in directory.glob(SOCKET_GLOB):
        sock.unlink(missing_ok=True)


def _launch_session() -> LaunchResult:
    # Start Resonite (engine + renderer) from the gated Gale profile via the
    # launcher Python API and return both host PIDs. Blocks until both appear.
    # Pinning ``mod_path`` to the same GALE_DIR the skip gate checks keeps the
    # fixture self-consistent and independent of the MOD_PATH env var.
    return launch(mod_path=str(GALE_DIR), wait_timeout=LAUNCH_TIMEOUT_S)


def _terminate_quietly(
    resonite_pid: int | None = None, renderer_pid: int | None = None
) -> None:
    # Best-effort stop for teardown / pre-clean. With no PIDs ``terminate``
    # auto-detects the single running instance and raises LauncherError if it
    # finds more than one (or a given PID no longer matches the expected
    # process); we never want that to mask a test result, so swallow it. The
    # SIGKILL fallback may skip the mod's ProcessExit cleanup, so callers still
    # purge stale sockets afterwards.
    try:
        terminate(resonite_pid, renderer_pid)
    except LauncherError:
        pass


@pytest.fixture(autouse=True)
def require_mod_deployed() -> None:
    # ``resoio.launch`` boots Resonite from the ./gale profile; without the mod
    # deployed there the GrpcHost never binds the UDS, so skip rather than let
    # resonite_session hard-fail on the socket-wait timeout.
    if not (GALE_DIR / "BepInEx").is_dir():
        pytest.skip(
            f"mod not deployed to {GALE_DIR} (no BepInEx dir); run `just deploy-mod`"
        )


@pytest.fixture
def resonite_session() -> Iterator[Path]:
    """Yield the bound UDS path with ``RESONITE_IO_SOCKET`` pointing at it.

    Each test starts from a clean slate: any leftover Resonite from a
    crashed prior run or external launch is force-stopped before the
    fixture starts its own instance. Start/stop go through the
    :mod:`resoio.launcher` Python API (``launch`` / ``terminate``) rather
    than the ``just`` recipes, so the fixture owns the engine/renderer PIDs
    directly and tears down exactly the instance it started.
    """
    # Pre-stop: ensure no stray Resonite is running from a prior crash or an
    # out-of-band launch. The no-arg terminate is a no-op when nothing is
    # running, so this is safe to always invoke.
    _terminate_quietly()
    _purge_stale_sockets(SOCKET_DIR)
    # Clear any explicit override (e.g. leaked from a crashed prior test) so the
    # wait resolves by globbing SOCKET_DIR rather than honouring a stale path.
    os.environ.pop("RESONITE_IO_SOCKET", None)
    # launch (resoio.launch) blocks until the engine + renderer processes appear
    # and returns both host PIDs, so teardown can signal them precisely.
    result = _launch_session()
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
        # Stop the exact engine/renderer this fixture launched (best-effort: the
        # process may already be dead); the purge below covers SIGKILL paths
        # where the mod's ProcessExit cleanup didn't run.
        _terminate_quietly(result.resonite_pid, result.renderer_pid)
        os.environ.pop("RESONITE_IO_SOCKET", None)
        _purge_stale_sockets(SOCKET_DIR)
