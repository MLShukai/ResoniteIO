"""E2E: verify the Microphone Bridge auto-promotes the virtual mic to default.

The change under test makes ``FrooxEngineMicrophoneBridge`` set
``AudioSystem.OverrideAudioInputIndex`` to the freshly-registered virtual
mic's index right after ``RegisterAudioInput``. We assert this by reading
the BepInEx ``LogOutput.log`` for the auto-promote log line once the
session is live.

The symmetric Dispose-time revert (``cleared OverrideAudioInputIndex``)
is NOT asserted here: ``terminate`` runs a SIGTERM→SIGKILL race in which
BepInEx's file log writer is typically reaped before
AppDomain.ProcessExit-driven dispose lines reach disk. The dispose path
is exercised whenever Resonite shuts down cleanly (e.g. GrpcHost
bind failure shows the dispose lines in ``LogOutput.log.prev``), and is
visually inspected in manual verification — see
``mod/tests/manual/microphone-verification.md``.

The "another user actually hears voice" check is also still manual.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from resoio.connection import wait_for_ready
from tests.e2e.conftest import (
    SOCKET_APPEAR_POLL_S,
    SOCKET_APPEAR_TIMEOUT_S,
    SOCKET_DIR,
    _launch_session,
    _purge_stale_sockets,
    _terminate_quietly,
)
from tests.helpers import mark_e2e

# The real workspace root (this file lives at python/tests/e2e/), used to find
# the gale plugin log.
WORKSPACE_ROOT: Path = Path(__file__).resolve().parents[3]
BEPINEX_LOG_PATH: Path = WORKSPACE_ROOT / "gale" / "BepInEx" / "LogOutput.log"

_AUTO_PROMOTE_PATTERN = "Microphone Bridge: OverrideAudioInputIndex set to "


def _read_log() -> str:
    if not BEPINEX_LOG_PATH.is_file():
        pytest.fail(
            f"BepInEx log not found at {BEPINEX_LOG_PATH}; ResoniteIO mod did not load?"
        )
    return BEPINEX_LOG_PATH.read_text(encoding="utf-8", errors="replace")


class TestMicrophoneAutoDefault:
    @mark_e2e
    def test_override_set_after_engine_start(self) -> None:
        # Pre-clean: stop any straggler from a prior crashed run so the log
        # we read below reflects only this test's session. BepInEx rotates
        # ``LogOutput.log`` → ``LogOutput.log.prev`` on each startup, so a
        # successful start guarantees the current file is just this run.
        _terminate_quietly()
        _purge_stale_sockets(SOCKET_DIR)

        # launch (resoio.launch) blocks until the engine + renderer appear and
        # returns both host PIDs so teardown can signal them precisely.
        result = _launch_session()
        try:
            socket_path = asyncio.run(
                wait_for_ready(
                    timeout=SOCKET_APPEAR_TIMEOUT_S,
                    interval=SOCKET_APPEAR_POLL_S,
                )
            )
            os.environ["RESONITE_IO_SOCKET"] = socket_path

            # The UDS socket appears only after GrpcHost.Start, which runs
            # after the Microphone Bridge ctor — so the auto-promote log must
            # already be persisted on disk when we read here.
            log_after_start = _read_log()
            assert _AUTO_PROMOTE_PATTERN in log_after_start, (
                f"Expected log to contain {_AUTO_PROMOTE_PATTERN!r} after "
                f"Resonite startup. Last 1k chars of log:\n{log_after_start[-1000:]}"
            )
            print(
                "E2E auto-default: observed OverrideAudioInputIndex set log line "
                "after engine startup"
            )
        finally:
            os.environ.pop("RESONITE_IO_SOCKET", None)
            _terminate_quietly(result.resonite_pid, result.renderer_pid)
            _purge_stale_sockets(SOCKET_DIR)
