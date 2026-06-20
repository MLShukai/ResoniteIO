"""Tests for the ``resoio launch`` CLI command.

The happy path (spawning umu-run and PID-diffing a real Resonite into
existence) needs a live Resonite and lives in the e2e suite
(``tests/e2e/launcher.py``). Here we pin the CLI's error contract — it renders
:class:`resoio.launcher.LauncherError` to stderr and exits 1 — which we trigger
with real conditions (a missing exe, and an already-running instance simulated
by a real dummy process), no mocks.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from resoio.cli import _amain, _build_parser
from resoio.launcher import _find_engine_pids

_SLEEP = shutil.which("sleep") or "/bin/sleep"


@pytest.fixture
def spawn() -> Iterator[Callable[..., int]]:
    procs: list[subprocess.Popen[bytes]] = []

    def _spawn(path: Path, *args: str) -> int:
        proc = subprocess.Popen(
            [str(path), *args], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        procs.append(proc)
        return proc.pid

    yield _spawn

    for proc in procs:
        if proc.poll() is None:
            proc.kill()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass


async def test_launch_missing_exe_errors(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    monkeypatch.setenv("RESONITE_EXE", "/nonexistent/Resonite.exe")
    rc = await _amain(_build_parser().parse_args(["launch"]))
    assert rc == 1
    assert "not found" in capsys.readouterr().err


async def test_launch_refuses_when_already_running(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spawn: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
):
    install = tmp_path / "resonite"
    (install / "dotnet-runtime").mkdir(parents=True)
    shutil.copy(_SLEEP, install / "dotnet-runtime" / "dotnet")
    (install / "dotnet-runtime" / "dotnet").chmod(0o755)
    (install / "Resonite.exe").write_text("")
    monkeypatch.setenv("RESONITE_EXE", str(install / "Resonite.exe"))

    spawn(install / "dotnet-runtime" / "dotnet", "60")
    deadline = time.monotonic() + 5.0
    while not _find_engine_pids(str(install)) and time.monotonic() < deadline:
        time.sleep(0.02)

    rc = await _amain(_build_parser().parse_args(["launch", "--vanilla"]))
    assert rc == 1
    assert "already running" in capsys.readouterr().err
