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

import contextlib
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
    _wait_for_new,
    launch,
    terminate,
    terminate_all,
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

    # Deploy the mod the way `just deploy-mod` / a Thunderstore install does:
    # the DLL nests one level deeper under the package dir.
    plugin = profile / "BepInEx" / "plugins" / "ResoniteIO" / "ResoniteIO"
    plugin.mkdir(parents=True)
    (plugin / "ResoniteIO.dll").write_text("")
    assert _resolve_mod_path(str(profile)) == str(profile)


def test_resolve_mod_path_reads_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    profile = tmp_path / "gale"
    plugin = profile / "BepInEx" / "plugins" / "ResoniteIO" / "ResoniteIO"
    plugin.mkdir(parents=True)
    (plugin / "ResoniteIO.dll").write_text("")
    monkeypatch.setenv("MOD_PATH", str(profile))
    assert _resolve_mod_path(None) == str(profile)


@pytest.mark.parametrize(
    "rel",
    [
        "BepInEx/plugins/ResoniteIO/ResoniteIO.dll",  # legacy flat dev copy
        "BepInEx/plugins/ResoniteIO/ResoniteIO/ResoniteIO.dll",  # Thunderstore/Gale
        "BepInEx/plugins/mlshukai-ResoniteIO/ResoniteIO/ResoniteIO.dll",  # namespaced
    ],
)
def test_resolve_mod_path_accepts_any_layout_under_plugins(tmp_path: Path, rel: str):
    # BepInEx discovers plugins by scanning plugins/ recursively, so launch must
    # accept ResoniteIO.dll wherever it lands — the flat dev copy, the nested
    # Thunderstore/Gale layout, or a namespaced package dir. Pins that the
    # resolver mirrors BepInEx's discovery rather than one hard-coded path.
    profile = tmp_path / "gale"
    dll = profile / rel
    dll.parent.mkdir(parents=True)
    dll.write_text("")
    assert _resolve_mod_path(str(profile)) == str(profile)


def test_resolve_mod_path_returns_absolute_for_relative_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # launch() spawns the subprocess with cwd=install_dir, so a relative profile
    # would make --bepinex-target relative and BepisLoader rejects it ("not an
    # absolute path"). The resolver must absolutise the profile regardless of how
    # it was passed. We chdir into tmp_path and pass a relative name so the only
    # way the assertion can pass is if the resolver does the abspath itself.
    profile = tmp_path / "gale"
    dll = (
        profile / "BepInEx" / "plugins" / "ResoniteIO" / "ResoniteIO" / "ResoniteIO.dll"
    )
    dll.parent.mkdir(parents=True)
    dll.write_text("")
    monkeypatch.chdir(tmp_path)

    resolved = _resolve_mod_path("gale")

    assert os.path.isabs(resolved)
    assert os.path.basename(resolved) == "gale"


def test_build_command_bepinex_target_is_absolute_for_relative_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_umu: Path
):
    # The same bug surfaced end-to-end: when launch is told a relative profile,
    # the --bepinex-target value handed to the launch chain must still be
    # absolute. Pin it on the assembled argv, not just the resolver.
    install = _make_install(tmp_path)
    profile = tmp_path / "gale"
    _deploy_mod(profile)
    monkeypatch.chdir(tmp_path)

    argv, _env, _log = _build_command(
        str(install / "Resonite.exe"),
        str(install),
        "gale",
        vanilla=False,
        extra_args=(),
    )

    bepinex_target = argv[argv.index("--bepinex-target") + 1]
    assert os.path.isabs(bepinex_target)


def _deploy_mod(profile: Path, *, with_preloader: bool = True) -> None:
    # Mirror `just deploy-mod`: the engine DLL nests under the package dir
    # (BepInEx/plugins/ResoniteIO/ResoniteIO/ResoniteIO.dll) the way a real
    # Thunderstore / Gale install lays it out.
    plugin = profile / "BepInEx" / "plugins" / "ResoniteIO" / "ResoniteIO"
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


# ---------------------------------------------------------------------------
# umu / Proton env defaults + precedence (PROTON_SET_GAME_DRIVE / GAMEID /
# PROTONPATH / WINEPREFIX). Spec: a host launch must behave like the dev
# container, with PROTON_SET_GAME_DRIVE forced to "0" (the $HOME-install hang
# fix), GAMEID/PROTONPATH/WINEPREFIX following an arg > env > default precedence.
#
# Every test clears the relevant env vars first (delenv ..., raising=False):
# the real CI container carries PROTONPATH/GAMEID/etc. in os.environ, so without
# clearing we could not tell a default-derived value apart from an inherited one.
# ---------------------------------------------------------------------------


def _clear_proton_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("PROTON_SET_GAME_DRIVE", "GAMEID", "PROTONPATH", "WINEPREFIX"):
        monkeypatch.delenv(name, raising=False)


def test_build_command_seeds_proton_env_defaults_when_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_umu: Path
):
    # With nothing in the environment, the launch defaults are applied: the
    # game-drive mapping is disabled, GAMEID/PROTONPATH fall back to umu defaults,
    # and WINEPREFIX is left to umu (no --prefix given).
    _clear_proton_env(monkeypatch)
    install = _make_install(tmp_path)

    _argv, env, _log = _build_command(
        str(install / "Resonite.exe"), str(install), None, vanilla=True, extra_args=()
    )

    assert env["PROTON_SET_GAME_DRIVE"] == "0"
    assert env["GAMEID"] == "umu-default"
    assert env["PROTONPATH"] == "GE-Proton"
    assert "WINEPREFIX" not in env


def test_build_command_respects_existing_gameid_and_protonpath(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_umu: Path
):
    # An operator who exported GAMEID / PROTONPATH should have those honoured
    # (setdefault), not stomped by the umu defaults.
    _clear_proton_env(monkeypatch)
    monkeypatch.setenv("PROTONPATH", "UMU-Proton")
    monkeypatch.setenv("GAMEID", "foo")
    install = _make_install(tmp_path)

    _argv, env, _log = _build_command(
        str(install / "Resonite.exe"), str(install), None, vanilla=True, extra_args=()
    )

    assert env["PROTONPATH"] == "UMU-Proton"
    assert env["GAMEID"] == "foo"


def test_build_command_proton_path_arg_overrides_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_umu: Path
):
    # proton_path is the highest-precedence source: an explicit --proton-path
    # wins over an inherited PROTONPATH.
    _clear_proton_env(monkeypatch)
    monkeypatch.setenv("PROTONPATH", "UMU-Proton")
    install = _make_install(tmp_path)

    _argv, env, _log = _build_command(
        str(install / "Resonite.exe"),
        str(install),
        None,
        vanilla=True,
        extra_args=(),
        proton_path="GE-Latest",
    )

    assert env["PROTONPATH"] == "GE-Latest"


def test_build_command_forces_game_drive_off_even_when_env_enables_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_umu: Path
):
    # Regression guard for the host renderer hang: even if the environment sets
    # PROTON_SET_GAME_DRIVE=1, the launch must force it back to "0" so umu does
    # not map $HOME onto a Wine drive letter and break the renderer's absolute
    # Unix paths. This is a bug fix, not a configurable default, so env must not
    # be able to re-enable it.
    _clear_proton_env(monkeypatch)
    monkeypatch.setenv("PROTON_SET_GAME_DRIVE", "1")
    install = _make_install(tmp_path)

    _argv, env, _log = _build_command(
        str(install / "Resonite.exe"), str(install), None, vanilla=True, extra_args=()
    )

    assert env["PROTON_SET_GAME_DRIVE"] == "0"


def test_build_command_prefix_arg_is_absolutized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_umu: Path
):
    # --prefix sets WINEPREFIX, which must be an absolute path: the launch runs
    # the subprocess with cwd=install_dir, so a relative prefix would resolve
    # against the install dir rather than the caller's cwd. The basename is
    # preserved so the caller still points at the directory they named.
    _clear_proton_env(monkeypatch)
    install = _make_install(tmp_path)

    _argv, env, _log = _build_command(
        str(install / "Resonite.exe"),
        str(install),
        None,
        vanilla=True,
        extra_args=(),
        prefix="rel/path",
    )

    assert os.path.isabs(env["WINEPREFIX"])
    assert os.path.basename(env["WINEPREFIX"]) == "path"


def test_build_command_seeds_proton_env_defaults_in_mod_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_umu: Path
):
    # The env defaults live in the section shared by both launch paths, so a
    # mod-mode build gets them too (not just vanilla).
    _clear_proton_env(monkeypatch)
    install = _make_install(tmp_path)
    profile = tmp_path / "gale"
    _deploy_mod(profile)

    _argv, env, _log = _build_command(
        str(install / "Resonite.exe"),
        str(install),
        str(profile),
        vanilla=False,
        extra_args=(),
    )

    assert env["PROTON_SET_GAME_DRIVE"] == "0"
    assert env["GAMEID"] == "umu-default"
    assert env["PROTONPATH"] == "GE-Proton"


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


# ---------------------------------------------------------------------------
# Multi-instance: _wait_for_new (PID set-difference) + terminate_all
# ---------------------------------------------------------------------------
#
# launch() no longer refuses when an instance is already running (multi-instance
# support): it identifies the engine/renderer it spawned by the set difference
# against a `before` snapshot, so an existing instance is ignored rather than an
# error. _wait_for_new encodes that contract.


def test_wait_for_new_returns_pid_absent_from_before(
    tmp_path: Path, spawn: Callable[..., int]
):
    # An engine PID already present in `before` is ignored; only the PID spawned
    # afterwards (the one this launch created) is returned.
    install = _make_install(tmp_path)
    existing = spawn(install / "dotnet-runtime" / "dotnet", "60")
    _wait_pids(lambda: _find_engine_pids(str(install)), 1)
    before = {existing}

    fresh = spawn(install / "dotnet-runtime" / "dotnet", "60")
    _wait_pids(lambda: _find_engine_pids(str(install)), 2)

    deadline = time.monotonic() + 5.0
    new_pid = _wait_for_new(
        lambda: _find_engine_pids(str(install)),
        before,
        "engine",
        deadline,
        0.02,
    )

    assert new_pid == fresh


def test_wait_for_new_raises_when_multiple_new_appear(
    tmp_path: Path, spawn: Callable[..., int]
):
    # Two engines not in `before` means an unexpected concurrent launch; the
    # set-difference can no longer pick a single owner, so it errors.
    install = _make_install(tmp_path)
    spawn(install / "dotnet-runtime" / "dotnet", "60")
    spawn(install / "dotnet-runtime" / "dotnet", "60")
    _wait_pids(lambda: _find_engine_pids(str(install)), 2)

    deadline = time.monotonic() + 5.0
    with pytest.raises(LauncherError, match="multiple new"):
        _wait_for_new(
            lambda: _find_engine_pids(str(install)),
            set(),
            "engine",
            deadline,
            0.02,
        )


def test_wait_for_new_times_out_when_no_new_appears(tmp_path: Path):
    # No new engine ever appears; once the deadline passes the wait gives up with
    # a timeout error rather than blocking forever.
    install = _make_install(tmp_path)
    deadline = time.monotonic() - 1.0  # already expired

    with pytest.raises(LauncherError, match="timed out"):
        _wait_for_new(
            lambda: _find_engine_pids(str(install)),
            set(),
            "engine",
            deadline,
            0.02,
        )


def test_launch_starts_additional_instance_without_already_running_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, spawn: Callable[..., int]
):
    # End-to-end multi-instance contract: with one instance already running,
    # launch() must NOT raise "already running" and must return the PIDs of the
    # *new* engine/renderer (the ones absent from the before-snapshot). We stand
    # in for umu-run with a script that spawns fresh engine+renderer sleep copies
    # at the install-relative argv0 paths the finders key off, so the real
    # set-difference / wait path runs without a live Resonite.
    install = _make_install(tmp_path)
    monkeypatch.setenv("RESONITE_EXE", str(install / "Resonite.exe"))

    existing_engine = spawn(install / "dotnet-runtime" / "dotnet", "60")
    existing_renderer = spawn(install / "Renderer" / "Renderite.Renderer.exe", "60")
    _wait_pids(lambda: _find_engine_pids(str(install)), 1)
    _wait_pids(lambda: _find_renderer_pids(str(install)), 1)

    # Fake umu-run: detach two more long-lived copies at the engine/renderer
    # argv0 paths, then exit. start_new_session means they outlive this script,
    # so launch()'s PID-diff sees them as the new pair.
    engine_path = install / "dotnet-runtime" / "dotnet"
    renderer_path = install / "Renderer" / "Renderite.Renderer.exe"
    bindir = tmp_path / "bin"
    bindir.mkdir()
    umu = bindir / "umu-run"
    umu.write_text(
        "#!/bin/sh\n"
        f"setsid '{engine_path}' 60 </dev/null >/dev/null 2>&1 &\n"
        f"setsid '{renderer_path}' 60 </dev/null >/dev/null 2>&1 &\n"
        "exit 0\n"
    )
    umu.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}")

    try:
        result = launch(
            resonite_exe=str(install / "Resonite.exe"),
            vanilla=True,
            wait_timeout=10.0,
            poll_interval=0.05,
        )

        # The returned pair are the freshly spawned instances, not the ones that
        # were already running.
        assert result.resonite_pid != existing_engine
        assert result.renderer_pid != existing_renderer
        assert result.resonite_pid in _find_engine_pids(str(install))
        assert result.renderer_pid in _find_renderer_pids(str(install))
    finally:
        # Reap the detached fakes launch() spawned (the `spawn` fixture only
        # tracks the two it created directly).
        for pid in (
            set(_find_engine_pids(str(install)))
            | set(_find_renderer_pids(str(install)))
        ) - {existing_engine, existing_renderer}:
            with contextlib.suppress(psutil.NoSuchProcess):
                psutil.Process(pid).kill()


def test_terminate_all_kills_every_running_instance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, spawn: Callable[..., int]
):
    # terminate_all stops every running engine/renderer (not just a single
    # instance) and returns the PIDs it signalled. We spawn two engines and two
    # renderers and assert all four are killed and reported.
    install = _make_install(tmp_path)
    monkeypatch.setenv("RESONITE_EXE", str(install / "Resonite.exe"))
    engine_a = spawn(install / "dotnet-runtime" / "dotnet", "60")
    engine_b = spawn(install / "dotnet-runtime" / "dotnet", "60")
    renderer_a = spawn(install / "Renderer" / "Renderite.Renderer.exe", "60")
    renderer_b = spawn(install / "Renderer" / "Renderite.Renderer.exe", "60")
    _wait_pids(lambda: _find_engine_pids(str(install)), 2)
    _wait_pids(lambda: _find_renderer_pids(str(install)), 2)

    killed = terminate_all(timeout=3.0)

    assert set(killed) == {engine_a, engine_b, renderer_a, renderer_b}
    assert _wait_pids(lambda: _find_engine_pids(str(install)), 0) == []
    assert _wait_pids(lambda: _find_renderer_pids(str(install)), 0) == []


def test_terminate_all_returns_empty_when_nothing_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # With no instance running, terminate_all is a no-op that reports an empty
    # list rather than erroring.
    install = _make_install(tmp_path)
    monkeypatch.setenv("RESONITE_EXE", str(install / "Resonite.exe"))

    assert terminate_all(timeout=3.0) == []
