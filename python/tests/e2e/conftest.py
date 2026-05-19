"""Fixtures owning the live Resonite + host-agent lifecycle for e2e tests."""

from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

REPO_ROOT: Path = Path(__file__).resolve().parents[2]
SOCKET_DIR: Path = Path.home() / ".resonite-io"
SOCKET_GLOB = "resonite-*.sock"
SOCKET_APPEAR_TIMEOUT_S = 120.0
SOCKET_APPEAR_POLL_S = 1.0
DEBUG_SOCKET: Path = Path.home() / ".resonite-io-debug" / "host-agent.sock"


def _wait_for_socket(directory: Path, timeout_s: float) -> Path:
    # Returns only when exactly one socket is present: leftover sockets from
    # a prior run plus the live one would silently pick the wrong target.
    deadline = time.monotonic() + timeout_s
    last_candidates: list[Path] = []
    while time.monotonic() < deadline:
        if directory.is_dir():
            candidates = sorted(directory.glob(SOCKET_GLOB))
            if len(candidates) == 1:
                return candidates[0]
            last_candidates = candidates
        time.sleep(SOCKET_APPEAR_POLL_S)
    raise AssertionError(
        f"Timed out waiting for Resonite IO socket under {directory} "
        f"after {timeout_s:.0f}s. Last seen: {last_candidates}"
    )


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
def require_host_agent() -> None:
    if not DEBUG_SOCKET.exists():
        pytest.skip(
            "host-agent is not running on host (expected socket at "
            f"{DEBUG_SOCKET}). Start it with `just host-agent` on the host."
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
    _run_just("resonite-start")
    try:
        socket_path = _wait_for_socket(SOCKET_DIR, SOCKET_APPEAR_TIMEOUT_S)
        os.environ["RESONITE_IO_SOCKET"] = str(socket_path)
        yield socket_path
    finally:
        # stop is best-effort (process may already be dead); the purge below
        # covers SIGKILL paths where the mod's ProcessExit cleanup didn't run.
        _run_just("resonite-stop", check=False, timeout=30.0)
        os.environ.pop("RESONITE_IO_SOCKET", None)
        _purge_stale_sockets(SOCKET_DIR)
