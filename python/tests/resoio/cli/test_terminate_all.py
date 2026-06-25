"""Tests for the ``resoio terminate-all`` CLI command (multi-instance kill).

``terminate-all`` force-stops every running Resonite instance. Per
testing-strategy we drive the real CLI dispatch (``_build_parser`` -> ``_amain``)
against **real dummy processes** (copies of ``sleep`` at the install-relative
argv[0] paths the launcher matches), not mocks. The kill logic itself is covered
in ``test_launcher.py``; here we pin the CLI contract: the human summary, the
``--format json`` document shape, and the empty-state message.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from resoio.cli import _amain, _build_parser
from resoio.launcher import _find_engine_pids, _find_renderer_pids

_SLEEP = shutil.which("sleep") or "/bin/sleep"


def _make_install(tmp_path: Path) -> Path:
    install = tmp_path / "resonite"
    (install / "dotnet-runtime").mkdir(parents=True)
    shutil.copy(_SLEEP, install / "dotnet-runtime" / "dotnet")
    (install / "dotnet-runtime" / "dotnet").chmod(0o755)
    (install / "Renderer").mkdir(parents=True)
    shutil.copy(_SLEEP, install / "Renderer" / "Renderite.Renderer.exe")
    (install / "Renderer" / "Renderite.Renderer.exe").chmod(0o755)
    (install / "Resonite.exe").write_text("")
    return install


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


def _wait_count(finder: Callable[[], list[int]], count: int, timeout: float = 5.0):
    deadline = time.monotonic() + timeout
    while len(finder()) != count and time.monotonic() < deadline:
        time.sleep(0.02)


async def test_terminate_all_human_summarises_killed_instances(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spawn: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
):
    install = _make_install(tmp_path)
    monkeypatch.setenv("RESONITE_EXE", str(install / "Resonite.exe"))
    spawn(install / "dotnet-runtime" / "dotnet", "60")
    spawn(install / "dotnet-runtime" / "dotnet", "60")
    spawn(install / "Renderer" / "Renderite.Renderer.exe", "60")
    spawn(install / "Renderer" / "Renderite.Renderer.exe", "60")
    _wait_count(lambda: _find_engine_pids(str(install)), 2)
    _wait_count(lambda: _find_renderer_pids(str(install)), 2)

    rc = await _amain(_build_parser().parse_args(["terminate-all"]))

    assert rc == 0
    out = capsys.readouterr().out
    assert "terminated" in out
    assert "instance" in out
    _wait_count(lambda: _find_engine_pids(str(install)), 0)
    assert _find_engine_pids(str(install)) == []
    assert _find_renderer_pids(str(install)) == []


async def test_terminate_all_json_emits_pair_list(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spawn: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
):
    install = _make_install(tmp_path)
    monkeypatch.setenv("RESONITE_EXE", str(install / "Resonite.exe"))
    spawn(install / "dotnet-runtime" / "dotnet", "60")
    spawn(install / "Renderer" / "Renderite.Renderer.exe", "60")
    _wait_count(lambda: _find_engine_pids(str(install)), 1)
    _wait_count(lambda: _find_renderer_pids(str(install)), 1)

    rc = await _amain(_build_parser().parse_args(["terminate-all", "--format", "json"]))

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert isinstance(payload, list)
    # Every entry has the engine/renderer pair keys, and across the list every
    # signalled PID is a positive int.
    signalled: set[int] = set()
    for entry in payload:
        assert set(entry) == {"resonite_pid", "renderer_pid"}
        signalled |= {entry["resonite_pid"], entry["renderer_pid"]}
    signalled.discard(0)
    assert all(pid > 0 for pid in signalled)
    assert signalled  # at least one process was reported


async def test_terminate_all_reports_nothing_when_absent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    install = _make_install(tmp_path)
    monkeypatch.setenv("RESONITE_EXE", str(install / "Resonite.exe"))

    rc = await _amain(_build_parser().parse_args(["terminate-all"]))

    assert rc == 0
    assert "no running Resonite instances found" in capsys.readouterr().out


async def test_terminate_all_empty_json_is_empty_list(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    install = _make_install(tmp_path)
    monkeypatch.setenv("RESONITE_EXE", str(install / "Resonite.exe"))

    rc = await _amain(_build_parser().parse_args(["terminate-all", "--format", "json"]))

    assert rc == 0
    assert json.loads(capsys.readouterr().out) == []
