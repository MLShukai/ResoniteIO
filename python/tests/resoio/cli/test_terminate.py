"""Tests for the ``resoio terminate`` CLI command (process kill).

``terminate`` force-stops Resonite by signalling its engine + renderer
processes. Per testing-strategy we drive the real CLI dispatch
(``_build_parser`` -> ``_amain``) against **real dummy processes** (copies of
``sleep`` at the install-relative argv[0] paths the launcher matches), not mocks.
The kill/detection logic itself is covered in ``test_launcher.py``; here we pin
the CLI contract: PID output on a kill, ``resonite not running`` when nothing is
found, and the argparse rejection of exactly one PID.
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


def _wait_engine(install: Path, count: int, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while len(_find_engine_pids(str(install))) != count and time.monotonic() < deadline:
        time.sleep(0.02)


async def test_terminate_explicit_prints_killed_pids(
    tmp_path: Path, spawn: Callable[..., int], capsys: pytest.CaptureFixture[str]
):
    install = _make_install(tmp_path)
    engine = spawn(install / "dotnet-runtime" / "dotnet", "60")
    renderer = spawn(install / "Renderer" / "Renderite.Renderer.exe", "60")
    _wait_engine(install, 1)

    args = _build_parser().parse_args(["terminate", str(engine), str(renderer)])
    rc = await _amain(args)

    assert rc == 0
    out = capsys.readouterr().out
    assert f"resonite_pid={engine}" in out
    assert f"renderer_pid={renderer}" in out


async def test_terminate_no_args_autodetects_and_kills(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spawn: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
):
    install = _make_install(tmp_path)
    monkeypatch.setenv("RESONITE_EXE", str(install / "Resonite.exe"))
    engine = spawn(install / "dotnet-runtime" / "dotnet", "60")
    spawn(install / "Renderer" / "Renderite.Renderer.exe", "60")
    _wait_engine(install, 1)

    rc = await _amain(_build_parser().parse_args(["terminate"]))

    assert rc == 0
    assert f"resonite_pid={engine}" in capsys.readouterr().out


async def test_terminate_reports_nothing_running(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    install = _make_install(tmp_path)
    monkeypatch.setenv("RESONITE_EXE", str(install / "Resonite.exe"))

    rc = await _amain(_build_parser().parse_args(["terminate"]))

    assert rc == 0
    assert capsys.readouterr().out.strip() == "resonite not running"


async def test_terminate_one_pid_only_is_usage_error(
    capsys: pytest.CaptureFixture[str],
):
    rc = await _amain(_build_parser().parse_args(["terminate", "123"]))
    assert rc == 2
    assert "both" in capsys.readouterr().err


async def test_terminate_all_kills_every_instance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spawn: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
):
    # --all routes through terminate_all, which kills every running instance (not
    # just the single auto-detected one). Two engines run; both must die and be
    # reported. Driven against real processes, no mocks.
    install = _make_install(tmp_path)
    monkeypatch.setenv("RESONITE_EXE", str(install / "Resonite.exe"))
    engine_a = spawn(install / "dotnet-runtime" / "dotnet", "60")
    engine_b = spawn(install / "dotnet-runtime" / "dotnet", "60")
    _wait_engine(install, 2)

    rc = await _amain(_build_parser().parse_args(["terminate", "--all"]))

    assert rc == 0
    out = capsys.readouterr().out
    assert str(engine_a) in out
    assert str(engine_b) in out
    _wait_engine(install, 0)
    assert _find_engine_pids(str(install)) == []


async def test_terminate_all_with_explicit_pid_is_usage_error(
    capsys: pytest.CaptureFixture[str],
):
    # --all (kill everything) and an explicit PID (kill exactly this one) are
    # contradictory; specifying both is rejected rather than guessing intent.
    rc = await _amain(_build_parser().parse_args(["terminate", "--all", "123", "456"]))
    assert rc == 1
