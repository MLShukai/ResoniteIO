"""Tests for :mod:`resoio.launcher` (umu-launcher start/stop of Resonite).

Per testing-strategy these use **real OS processes** rather than mocking
``psutil`` / ``subprocess``: the engine/renderer matchers and the staged
``SIGTERM`` -> ``SIGKILL`` kill are exercised against real long-running
processes (copies of ``sleep`` placed at the install-relative argv[0] paths the
matchers key off — ``<install>/dotnet-runtime/dotnet`` for the engine and
``<install>/Renderer/Renderite.Renderer.exe`` for the renderer). The full
``launch`` happy path (spawning umu-run) needs a real Resonite and lives in the
e2e suite (``tests/e2e/launcher.py``); here we cover argument/path resolution,
command construction, the already-running guard, and the kill/detection logic.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import psutil
import pytest

from resoio.launcher import (
    LauncherError,
    LaunchResult,
    _append_env,
    _build_command,
    _find_engine_pids,
    _find_renderer_pids,
    _resolve_mod_path,
    _resolve_resonite_exe,
    launch,
    terminate,
)

_SLEEP = shutil.which("sleep") or "/bin/sleep"


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_install(tmp_path: Path, *, with_renderer: bool = True) -> Path:
    """Create a fake Resonite install whose argv[0] paths match the matchers.

    The engine/renderer "binaries" are copies of ``sleep`` so they can be
    spawned as real long-running processes whose ``cmdline()[0]`` is the
    install-relative path :func:`_find_engine_pids` / :func:`_find_renderer_pids`
    key off.
    """
    install = tmp_path / "resonite"
    (install / "dotnet-runtime").mkdir(parents=True)
    engine = install / "dotnet-runtime" / "dotnet"
    shutil.copy(_SLEEP, engine)
    engine.chmod(0o755)
    if with_renderer:
        (install / "Renderer").mkdir(parents=True)
        renderer = install / "Renderer" / "Renderite.Renderer.exe"
        shutil.copy(_SLEEP, renderer)
        renderer.chmod(0o755)
    # _resolve_resonite_exe asserts Resonite.exe exists.
    (install / "Resonite.exe").write_text("")
    return install


@pytest.fixture
def spawn() -> Iterator[Callable[..., int]]:
    """Spawn tracked child processes and reap them at teardown."""
    procs: list[subprocess.Popen[bytes]] = []

    def _spawn(path: Path | str, *args: str) -> int:
        proc = subprocess.Popen(
            [str(path), *args],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
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


def _wait_pids(
    finder: Callable[[], list[int]], count: int, timeout: float = 5.0
) -> list[int]:
    """Poll ``finder`` until it returns ``count`` PIDs (real spawn settle)."""
    deadline = time.monotonic() + timeout
    pids = finder()
    while len(pids) != count and time.monotonic() < deadline:
        time.sleep(0.02)
        pids = finder()
    return pids


@pytest.fixture
def fake_umu(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Put a no-op ``umu-run`` first on PATH so ``_build_command`` resolves
    it."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    umu = bindir / "umu-run"
    umu.write_text("#!/bin/sh\nexit 0\n")
    umu.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}")
    return umu


# ---------------------------------------------------------------------------
# Unit: dataclass / env / path resolution / command building
# ---------------------------------------------------------------------------


def test_launch_result_holds_both_pids():
    result = LaunchResult(resonite_pid=10, renderer_pid=20)
    assert result.resonite_pid == 10
    assert result.renderer_pid == 20


def test_append_env_joins_only_when_existing_present():
    assert _append_env(None, "winhttp=n,b", ";") == "winhttp=n,b"
    assert _append_env("", "winhttp=n,b", ";") == "winhttp=n,b"
    assert _append_env("foo=b", "winhttp=n,b", ";") == "foo=b;winhttp=n,b"
    assert _append_env("/a", "/b", ":") == "/a:/b"


def test_resolve_resonite_exe_prefers_explicit_then_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    exe = tmp_path / "Resonite.exe"
    exe.write_text("")
    assert _resolve_resonite_exe(str(exe)) == str(exe)

    monkeypatch.setenv("RESONITE_EXE", str(exe))
    assert _resolve_resonite_exe(None) == str(exe)


def test_resolve_resonite_exe_missing_raises(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RESONITE_EXE", "/nonexistent/Resonite.exe")
    with pytest.raises(LauncherError, match="not found"):
        _resolve_resonite_exe(None)


def test_resolve_mod_path_requires_deployed_mod(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("MOD_PATH", raising=False)
    with pytest.raises(LauncherError, match="required"):
        _resolve_mod_path(None)

    profile = tmp_path / "gale"
    profile.mkdir()
    # No ResoniteIO.dll yet -> install guidance.
    with pytest.raises(LauncherError, match="Install the ResoniteIO mod"):
        _resolve_mod_path(str(profile))

    plugin = profile / "BepInEx" / "plugins" / "ResoniteIO"
    plugin.mkdir(parents=True)
    (plugin / "ResoniteIO.dll").write_text("")
    assert _resolve_mod_path(str(profile)) == str(profile)


def test_resolve_mod_path_reads_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    profile = tmp_path / "gale"
    plugin = profile / "BepInEx" / "plugins" / "ResoniteIO"
    plugin.mkdir(parents=True)
    (plugin / "ResoniteIO.dll").write_text("")
    monkeypatch.setenv("MOD_PATH", str(profile))
    assert _resolve_mod_path(None) == str(profile)


def _deploy_mod(profile: Path, *, with_preloader: bool = True) -> None:
    plugin = profile / "BepInEx" / "plugins" / "ResoniteIO"
    plugin.mkdir(parents=True)
    (plugin / "ResoniteIO.dll").write_text("")
    if with_preloader:
        core = profile / "Renderer" / "BepInEx" / "core"
        core.mkdir(parents=True)
        (core / "BepInEx.Preloader.dll").write_text("")


def test_build_command_mod_mode_includes_hookfxr_doorstop_and_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_umu: Path
):
    monkeypatch.delenv("PRESSURE_VESSEL_FILESYSTEMS_RW", raising=False)
    monkeypatch.setenv("WINEDLLOVERRIDES", "foo=b")
    install = _make_install(tmp_path)
    profile = tmp_path / "gale"
    _deploy_mod(profile)

    argv, env, log_path = _build_command(
        str(install / "Resonite.exe"),
        str(install),
        str(profile),
        vanilla=False,
        extra_args=["-LoadAssembly", "x"],
    )

    assert argv[0] == "umu-run"
    assert argv[1] == str(install / "Resonite.exe")
    assert "-SkipIntroTutorial" in argv
    assert "--hookfxr-enable" in argv
    bepinex = str(profile / "BepInEx")
    assert argv[argv.index("--bepinex-target") + 1] == bepinex
    preloader = str(profile / "Renderer" / "BepInEx" / "core" / "BepInEx.Preloader.dll")
    assert argv[argv.index("--doorstop-target-assembly") + 1] == preloader
    # extra args forwarded at the end, in order.
    assert argv[-2:] == ["-LoadAssembly", "x"]
    # pressure-vessel bind + winhttp override appended (winhttp onto existing).
    assert env["PRESSURE_VESSEL_FILESYSTEMS_RW"] == str(profile)
    assert env["WINEDLLOVERRIDES"] == "foo=b;winhttp=n,b"
    assert log_path == str(profile / "BepInEx" / "umu-launch.log")


def test_build_command_without_preloader_skips_doorstop(tmp_path: Path, fake_umu: Path):
    install = _make_install(tmp_path)
    profile = tmp_path / "gale"
    _deploy_mod(profile, with_preloader=False)

    argv, _env, _log = _build_command(
        str(install / "Resonite.exe"), str(install), str(profile), False, ()
    )
    assert "--doorstop-target-assembly" not in argv


def test_build_command_vanilla_skips_mod_args(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_umu: Path
):
    monkeypatch.delenv("WINEDLLOVERRIDES", raising=False)
    install = _make_install(tmp_path)

    argv, env, log_path = _build_command(
        str(install / "Resonite.exe"), str(install), None, vanilla=True, extra_args=()
    )
    assert "--hookfxr-enable" not in argv
    assert "--bepinex-target" not in argv
    assert "WINEDLLOVERRIDES" not in env
    assert log_path is None


def test_build_command_without_umu_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    empty = tmp_path / "emptybin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    install = _make_install(tmp_path)
    with pytest.raises(LauncherError, match="umu-run"):
        _build_command(
            str(install / "Resonite.exe"),
            str(install),
            None,
            vanilla=True,
            extra_args=(),
        )


# ---------------------------------------------------------------------------
# Integration-real: process discovery + staged kill against real processes
# ---------------------------------------------------------------------------


def test_find_pids_match_engine_and_renderer_by_argv0(
    tmp_path: Path, spawn: Callable[..., int]
):
    install = _make_install(tmp_path)
    engine_pid = spawn(install / "dotnet-runtime" / "dotnet", "60")
    renderer_pid = spawn(install / "Renderer" / "Renderite.Renderer.exe", "60")

    assert _wait_pids(lambda: _find_engine_pids(str(install)), 1) == [engine_pid]
    assert _wait_pids(lambda: _find_renderer_pids(str(install)), 1) == [renderer_pid]
    # A plain sleep elsewhere is not matched (argv0 not under the install dir).
    other = spawn(_SLEEP, "60")
    assert other not in _find_engine_pids(str(install))


def test_terminate_explicit_kills_both(tmp_path: Path, spawn: Callable[..., int]):
    install = _make_install(tmp_path)
    engine_pid = spawn(install / "dotnet-runtime" / "dotnet", "60")
    renderer_pid = spawn(install / "Renderer" / "Renderite.Renderer.exe", "60")
    _wait_pids(lambda: _find_engine_pids(str(install)), 1)
    _wait_pids(lambda: _find_renderer_pids(str(install)), 1)

    result = terminate(engine_pid, renderer_pid, timeout=3.0)

    assert result == LaunchResult(resonite_pid=engine_pid, renderer_pid=renderer_pid)
    assert _wait_pids(lambda: _find_engine_pids(str(install)), 0) == []
    assert _wait_pids(lambda: _find_renderer_pids(str(install)), 0) == []


def test_terminate_is_idempotent_for_dead_pid(
    tmp_path: Path, spawn: Callable[..., int]
):
    install = _make_install(tmp_path)
    engine_pid = spawn(install / "dotnet-runtime" / "dotnet", "60")
    _wait_pids(lambda: _find_engine_pids(str(install)), 1)
    terminate(engine_pid, None, timeout=3.0)
    _wait_pids(lambda: _find_engine_pids(str(install)), 0)

    # Second call on the now-dead PID is a no-op (0), not an error.
    again = terminate(engine_pid, None, timeout=3.0)
    assert again.resonite_pid == 0


def test_terminate_refuses_unrelated_pid(spawn: Callable[..., int]):
    stray = spawn(_SLEEP, "60")  # a live PID that is not a Resonite engine
    with pytest.raises(LauncherError, match="not a Resonite engine"):
        terminate(stray, None, timeout=3.0)
    # the stray is left alive (validation happens before any signal).
    assert psutil.pid_exists(stray)


def test_terminate_no_args_detects_single_instance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, spawn: Callable[..., int]
):
    install = _make_install(tmp_path)
    monkeypatch.setenv("RESONITE_EXE", str(install / "Resonite.exe"))
    engine_pid = spawn(install / "dotnet-runtime" / "dotnet", "60")
    renderer_pid = spawn(install / "Renderer" / "Renderite.Renderer.exe", "60")
    _wait_pids(lambda: _find_engine_pids(str(install)), 1)
    _wait_pids(lambda: _find_renderer_pids(str(install)), 1)

    result = terminate()

    assert result == LaunchResult(resonite_pid=engine_pid, renderer_pid=renderer_pid)
    assert _wait_pids(lambda: _find_engine_pids(str(install)), 0) == []


def test_terminate_no_args_reports_nothing_when_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    install = _make_install(tmp_path)
    monkeypatch.setenv("RESONITE_EXE", str(install / "Resonite.exe"))
    result = terminate()
    assert result == LaunchResult(resonite_pid=0, renderer_pid=0)


def test_terminate_no_args_errors_on_multiple_instances(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, spawn: Callable[..., int]
):
    install = _make_install(tmp_path)
    monkeypatch.setenv("RESONITE_EXE", str(install / "Resonite.exe"))
    spawn(install / "dotnet-runtime" / "dotnet", "60")
    spawn(install / "dotnet-runtime" / "dotnet", "60")
    _wait_pids(lambda: _find_engine_pids(str(install)), 2)

    with pytest.raises(LauncherError, match="multiple Resonite instances"):
        terminate()


def test_launch_refuses_when_already_running(tmp_path: Path, spawn: Callable[..., int]):
    install = _make_install(tmp_path)
    spawn(install / "dotnet-runtime" / "dotnet", "60")
    _wait_pids(lambda: _find_engine_pids(str(install)), 1)

    # The already-running guard fires before umu/mod resolution, so vanilla is fine.
    with pytest.raises(LauncherError, match="already running"):
        launch(resonite_exe=str(install / "Resonite.exe"), vanilla=True)
