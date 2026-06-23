"""Start and stop the Resonite client through umu-launcher (no gRPC).

Resonite launches as **two** native Linux processes under umu-run / Proton:

* the **engine** — Resonite's bundled .NET runtime running the FrooxEngine
  client (``<install>/dotnet-runtime/dotnet``; with the ResoniteIO mod it is
  ``dotnet BepisLoader.dll``). This is the process the mod reports as
  ``ServerInfo.resonite_pid`` and names its UDS after (``resonite-<pid>.sock``).
* the **renderer** — ``<install>/Renderer/Renderite.Renderer.exe`` (also a real
  host process; ``ServerInfo.renderer_pid``).

Both are spawned under a tree of launch wrappers (``umu-run`` → ``srt-bwrap`` →
``pv-adverb`` → …) plus a Wine-side ``Resonite.exe`` bootstrap whose argv[0] is a
Windows path (``Z:\\...``). None of those wrappers is the engine, so we identify
the engine/renderer by their **argv[0] under the Resonite install directory**
rather than by process name (the wrappers' command lines also mention
``Resonite.exe``).

:func:`launch` spawns the umu-run chain detached, then PID-diffs the engine and
renderer processes into existence and returns both host PIDs. :func:`terminate`
stages ``SIGTERM`` → ``SIGKILL`` over the two PIDs (or auto-detects the single
running instance when called with no arguments). Everything here is pure process
control over the host process table — no gRPC, so it works before the engine has
bound its socket and regardless of whether the client is reachable.

This is a user-facing feature (``resoio launch`` / ``resoio terminate``): the
user installs Resonite via Steam, installs the ResoniteIO mod via Gale /
Thunderstore, then launches and stops the client from Python or the CLI.
``resoio shutdown`` (graceful gRPC quit) is the cooperative counterpart; these
are the forceful start/stop.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import psutil

__all__ = [
    "LaunchResult",
    "LauncherError",
    "launch",
    "terminate",
    "terminate_all",
]

_logger = logging.getLogger(__name__)

# Resonite.exe path used when neither an explicit argument nor ``RESONITE_EXE``
# is given — the default Linux Steam install location.
_DEFAULT_RESONITE_EXE: str = str(
    Path.home()
    / ".steam"
    / "steam"
    / "steamapps"
    / "common"
    / "Resonite"
    / "Resonite.exe"
)

# argv[0] suffixes (relative to the Resonite install dir) that identify the two
# native game processes. The engine runs via Resonite's *bundled* .NET runtime,
# which distinguishes it from a system / IDE ``dotnet`` (e.g. /usr/local/dotnet).
_ENGINE_ARGV0_SUFFIX: str = os.path.join("dotnet-runtime", "dotnet")
_RENDERER_ARGV0_SUFFIX: str = os.path.join("Renderer", "Renderite.Renderer.exe")


class LauncherError(RuntimeError):
    """A ``resoio launch`` / ``terminate`` operation could not be completed.

    Raised for actionable conditions: Resonite.exe / the mod not found, no
    ``umu-run`` on PATH, more than one new engine / renderer appearing from a
    single launch, more than one instance detected where exactly one is expected,
    or the engine / renderer not appearing before the timeout.
    """


@dataclass(frozen=True, slots=True)
class LaunchResult:
    """Host PIDs of the Resonite engine and renderer processes.

    Returned by :func:`launch` (the freshly started pair) and :func:`terminate`
    (the pair it actually signalled; ``0`` for a role that was not running).
    ``resonite_pid`` matches the engine PID the mod reports as
    ``ServerInfo.resonite_pid``; ``renderer_pid`` matches ``ServerInfo.renderer_pid``.
    """

    resonite_pid: int
    renderer_pid: int


# ---------------------------------------------------------------------------
# Process discovery (psutil)
# ---------------------------------------------------------------------------


def _argv0_realpath(proc: psutil.Process) -> str | None:
    """Return the resolved absolute path of ``proc``'s argv[0], or ``None``.

    Uses ``proc.cmdline()`` so it works for both a bare :class:`psutil.Process`
    (e.g. built from a PID in :func:`_kill_pid`) and one yielded by
    ``process_iter``. Wine-side processes carry a Windows-style argv[0]
    (``Z:\\...``) which ``realpath`` leaves alone — they simply never match a
    Unix install path, which is how the Wine ``Resonite.exe`` bootstrap is
    excluded.
    """
    try:
        cmdline = proc.cmdline()
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return None
    if not cmdline:
        return None
    return os.path.realpath(cmdline[0])


def _find_by_argv0(expected: str) -> list[int]:
    """PIDs whose resolved argv[0] equals ``expected`` (an absolute path)."""
    pids: list[int] = []
    for proc in psutil.process_iter():
        if _argv0_realpath(proc) == expected:
            pids.append(proc.pid)
    return pids


def _engine_argv0(install_dir: str) -> str:
    return os.path.realpath(os.path.join(install_dir, _ENGINE_ARGV0_SUFFIX))


def _renderer_argv0(install_dir: str) -> str:
    return os.path.realpath(os.path.join(install_dir, _RENDERER_ARGV0_SUFFIX))


def _find_engine_pids(install_dir: str) -> list[int]:
    """Host PIDs of the Resonite engine launched from ``install_dir``."""
    return _find_by_argv0(_engine_argv0(install_dir))


def _find_renderer_pids(install_dir: str) -> list[int]:
    """Host PIDs of the Resonite renderer launched from ``install_dir``."""
    return _find_by_argv0(_renderer_argv0(install_dir))


# ---------------------------------------------------------------------------
# Path / argument resolution
# ---------------------------------------------------------------------------


def _resolve_resonite_exe(explicit: str | None) -> str:
    """Resolve the Resonite.exe to launch and assert it exists.

    Order: explicit argument → ``RESONITE_EXE`` env → the default Steam path.
    """
    exe = explicit or os.environ.get("RESONITE_EXE") or _DEFAULT_RESONITE_EXE
    if not os.path.isfile(exe):
        raise LauncherError(
            f"Resonite.exe not found at {exe!r}. Set RESONITE_EXE or pass "
            "--exe/resonite_exe to point at your Resonite install "
            "(e.g. ~/.steam/steam/steamapps/common/Resonite/Resonite.exe)."
        )
    return exe


def _install_dir_for_detection() -> str:
    """Resonite install dir used to detect a running instance (no exe check).

    Detection (``terminate`` with no PIDs) only needs the install directory to
    pin the argv[0] matchers, so — unlike :func:`_resolve_resonite_exe` — it does
    not require the exe to exist.
    """
    exe = os.environ.get("RESONITE_EXE") or _DEFAULT_RESONITE_EXE
    return os.path.dirname(os.path.realpath(exe))


def _resolve_mod_path(explicit: str | None) -> str:
    """Resolve the mod-profile directory and assert the ResoniteIO mod is in
    it.

    Order: explicit ``--profile`` → ``MOD_PATH`` env. With neither set, or with
    no ``ResoniteIO.dll`` anywhere under ``BepInEx/plugins/``, raises with install
    guidance.

    BepInEx discovers plugins by scanning ``BepInEx/plugins/`` **recursively**, so
    ``ResoniteIO.dll`` lands at different depths depending on how the mod was
    installed. A Thunderstore / Gale install (and ``just deploy-mod``) nests it
    under the package directory
    (``BepInEx/plugins/<pkg>/ResoniteIO/ResoniteIO.dll`` — the same one-level-deep
    layout every other mod uses), while an older flat copy put it directly at
    ``BepInEx/plugins/ResoniteIO/ResoniteIO.dll``. We mirror BepInEx and accept the
    DLL wherever it is under ``plugins/`` rather than pinning one exact path.
    """
    profile = explicit or os.environ.get("MOD_PATH")
    if not profile:
        raise LauncherError(
            "mod profile path is required: set MOD_PATH or pass --profile/mod_path "
            "to the Gale profile holding the ResoniteIO mod (or use --vanilla to "
            "launch Resonite without any mod)."
        )
    plugins_root = Path(profile) / "BepInEx" / "plugins"
    found = plugins_root.is_dir() and next(plugins_root.rglob("ResoniteIO.dll"), None)
    if not found:
        raise LauncherError(
            f"ResoniteIO mod not found in {profile!r} (no ResoniteIO.dll under "
            f"{plugins_root}). Install the ResoniteIO mod into this profile first — "
            "via Gale or the Thunderstore package, or run `just deploy-mod`."
        )
    # launch() は cwd=install_dir で subprocess を起動するため、相対 profile だと
    # --bepinex-target が相対になり BepisLoader が "not an absolute path" で落ちる。
    # BepisLoader は絶対性のみ要求 (symlink 解決は不要) なので realpath でなく abspath。
    # profile は argv0 マッチには使わないので symlink 非解決でも齟齬は出ない。
    return os.path.abspath(profile)


def _find_renderer_preloader(profile: str) -> str | None:
    """Locate the renderer-side BepInEx preloader DLL for the doorstop hook.

    Returns the first match of
    ``<profile>/Renderer/BepInEx/core/BepInEx.*Preloader*.dll`` (or IL2CPP).
    ``None`` means Camera v2 (the renderer plugin) launches disabled.
    """
    core = Path(profile) / "Renderer" / "BepInEx" / "core"
    for pattern in ("BepInEx.*Preloader*.dll", "BepInEx.*IL2CPP*.dll"):
        for match in sorted(core.glob(pattern)):
            if match.is_file():
                return str(match)
    return None


def _append_env(existing: str | None, value: str, sep: str) -> str:
    """Append ``value`` to a ``sep``-delimited env var."""
    return f"{existing}{sep}{value}" if existing else value


def _build_command(
    exe: str,
    install_dir: str,
    mod_path: str | None,
    vanilla: bool,
    extra_args: Sequence[str],
    *,
    prefix: str | None = None,
    proton_path: str | None = None,
) -> tuple[list[str], dict[str, str], str | None]:
    """Build the umu-run argv, environment, and log path.

    Builds the umu-run launch chain: engine-side hookfxr
    (``--hookfxr-enable --bepinex-target``), renderer-side doorstop, the
    pressure-vessel profile bind, and the ``winhttp=n,b`` Wine override. Returns
    ``log_path=None`` (→ ``/dev/null``) for a vanilla launch.

    Also seeds umu/Proton env defaults so a host launch behaves like the dev
    container: ``PROTON_SET_GAME_DRIVE=0`` (forced — fixes the ``$HOME``-install
    hang where umu maps ``$HOME`` to a Wine drive letter and breaks the
    renderer's absolute Unix paths), plus ``GAMEID``, ``PROTONPATH`` (from
    ``proton_path`` arg, then env, then ``GE-Proton``), and ``WINEPREFIX`` (from
    the ``prefix`` arg only).
    """
    if shutil.which("umu-run") is None:
        raise LauncherError(
            "umu-run not found on PATH. Install umu-launcher (the dev container "
            "ships it) to launch Resonite."
        )

    argv = ["umu-run", exe, "-SkipIntroTutorial"]
    env = dict(os.environ)
    # umu/Proton env defaults — make a host launch behave like the dev container.
    # PROTON_SET_GAME_DRIVE は「設定」ではなく $HOME-install ハングのバグ修正なので
    # 直接代入する (env に 1 が残っていても踏み潰す。setdefault だと修正が無効化されうる)。
    env["PROTON_SET_GAME_DRIVE"] = "0"
    env.setdefault("GAMEID", "umu-default")  # umu-run は GAMEID 必須
    # PROTONPATH: arg > env > GE-Proton (arg は setdefault の前に処理。1 行 setdefault に混ぜない)
    if proton_path is not None:
        env["PROTONPATH"] = proton_path
    else:
        env.setdefault("PROTONPATH", "GE-Proton")
    # WINEPREFIX: --prefix 指定時のみ (絶対化)。未指定なら umu の既定 (~/Games/umu/$GAMEID) に委ねる。
    # PROTONPATH は GE-Proton のような論理名も取るので abspath しない (WINEPREFIX のみ abspath)。
    if prefix is not None:
        env["WINEPREFIX"] = os.path.abspath(prefix)
    log_path: str | None = None

    if not vanilla:
        profile = _resolve_mod_path(mod_path)
        argv += [
            "--hookfxr-enable",
            "--bepinex-target",
            os.path.join(profile, "BepInEx"),
        ]
        preloader = _find_renderer_preloader(profile)
        if preloader is not None:
            argv += [
                "--doorstop-enabled",
                "true",
                "--doorstop-target-assembly",
                preloader,
            ]
        else:
            _logger.warning(
                "renderer preloader not found under %s/Renderer/BepInEx/core; "
                "launching with Camera v2 (renderer plugin) disabled",
                profile,
            )
        # pressure-vessel must bind-share the profile so the sandboxed engine can
        # read the mod; WINEDLLOVERRIDES makes Wine load the hook winhttp.dll.
        env["PRESSURE_VESSEL_FILESYSTEMS_RW"] = _append_env(
            env.get("PRESSURE_VESSEL_FILESYSTEMS_RW"), profile, ":"
        )
        env["WINEDLLOVERRIDES"] = _append_env(
            env.get("WINEDLLOVERRIDES"), "winhttp=n,b", ";"
        )
        log_path = os.path.join(profile, "BepInEx", "umu-launch.log")

    argv += list(extra_args)
    return argv, env, log_path


# ---------------------------------------------------------------------------
# launch
# ---------------------------------------------------------------------------


def _wait_for_new(
    finder: Callable[[], list[int]],
    before: set[int],
    label: str,
    deadline: float,
    poll_interval: float,
) -> int:
    """Poll until a PID not in ``before`` appears; return it.

    before の集合差分で本 launch が spawn した個体を特定するので、他インスタンスが
    既に動いていても機能する。新規が複数 = 想定外の並行 launch でエラー。
    """
    while True:
        new = [pid for pid in finder() if pid not in before]
        if len(new) > 1:
            raise LauncherError(
                f"multiple new {label} processes appeared ({new}); "
                "expected exactly one from this launch."
            )
        if len(new) == 1:
            return new[0]
        if time.monotonic() >= deadline:
            raise LauncherError(
                f"timed out waiting for the Resonite {label} process to appear. "
                "Check the umu/Proton launch log (BepInEx/umu-launch.log) and the "
                "mod log (just log)."
            )
        time.sleep(poll_interval)


def launch(
    *,
    resonite_exe: str | None = None,
    mod_path: str | None = None,
    vanilla: bool = False,
    extra_args: Sequence[str] = (),
    prefix: str | None = None,
    proton_path: str | None = None,
    wait_timeout: float = 60.0,
    poll_interval: float = 0.5,
) -> LaunchResult:
    """Launch Resonite (engine + renderer) via umu-launcher and return both
    PIDs.

    Spawns the umu-run chain detached (the caller can exit without taking
    Resonite down), then PID-diffs the engine and renderer processes into
    existence and returns their host PIDs. Pure process control — no gRPC.

    Args:
        resonite_exe: Path to ``Resonite.exe``. ``None`` resolves it from the
            ``RESONITE_EXE`` env var, then the default Steam install path.
        mod_path: Gale profile directory holding the ResoniteIO mod. ``None``
            resolves it from ``MOD_PATH``; with neither set this raises (unless
            ``vanilla``). The profile must already have the mod deployed.
        vanilla: Launch without loading any mod (skips the mod-profile checks).
        extra_args: Extra arguments forwarded to ``Resonite.exe``.
        prefix: Wine prefix directory (``WINEPREFIX``). ``None`` lets umu use its
            default (``~/Games/umu/$GAMEID``).
        proton_path: Proton build (``PROTONPATH``) — a compat-tools name like
            ``GE-Proton`` or a path. ``None`` resolves it from ``PROTONPATH``,
            then ``GE-Proton``.
        wait_timeout: Seconds to wait for both processes to appear.
        poll_interval: Seconds between process-table polls.

    Returns:
        The :class:`LaunchResult` with the engine and renderer host PIDs.

    Raises:
        LauncherError: Resonite.exe / the mod / ``umu-run`` is missing, more than
            one new engine/renderer appears from this launch, or a process did
            not appear before ``wait_timeout``.
    """
    exe = _resolve_resonite_exe(resonite_exe)
    install_dir = os.path.dirname(os.path.realpath(exe))

    argv, env, log_path = _build_command(
        exe,
        install_dir,
        mod_path,
        vanilla,
        extra_args,
        prefix=prefix,
        proton_path=proton_path,
    )
    _logger.info("launching Resonite: %s (cwd=%s)", " ".join(argv), install_dir)

    # Snapshot the existing engine/renderer PIDs so we can identify the ones this
    # launch spawns by set difference (the argv0-based finders cannot tell two
    # instances of the same install apart).
    before_engines = set(_find_engine_pids(install_dir))
    before_renderers = set(_find_renderer_pids(install_dir))

    # Detach fully: new session + closed stdio so the parent (CLI / caller) can
    # exit without signalling Resonite. PROTON_SET_GAME_DRIVE=0 (set in
    # _build_command) suppresses umu's game-drive mapping of $HOME onto a Wine
    # drive letter, so even a $HOME-resident install resolves the renderer's
    # absolute Unix paths (renderer exe / /dev/shm IPC) correctly.
    stdout: object = subprocess.DEVNULL
    log_handle = None
    if log_path is not None:
        log_handle = open(log_path, "ab")
        stdout = log_handle
    try:
        subprocess.Popen(  # noqa: S603 - argv built from validated paths
            argv,
            cwd=install_dir,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=stdout,  # pyright: ignore[reportArgumentType]
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    finally:
        if log_handle is not None:
            log_handle.close()

    deadline = time.monotonic() + wait_timeout
    resonite_pid = _wait_for_new(
        lambda: _find_engine_pids(install_dir),
        before_engines,
        "engine",
        deadline,
        poll_interval,
    )
    renderer_pid = _wait_for_new(
        lambda: _find_renderer_pids(install_dir),
        before_renderers,
        "renderer",
        deadline,
        poll_interval,
    )
    _logger.info(
        "Resonite launched: resonite_pid=%d renderer_pid=%d", resonite_pid, renderer_pid
    )
    return LaunchResult(resonite_pid=resonite_pid, renderer_pid=renderer_pid)


# ---------------------------------------------------------------------------
# terminate
# ---------------------------------------------------------------------------


def _argv0_endswith(proc: psutil.Process, suffix: str) -> bool:
    argv0 = _argv0_realpath(proc)
    return argv0 is not None and argv0.endswith(os.sep + suffix)


def _kill_pid(pid: int, suffix: str, role: str, timeout: float) -> int:
    """Stage SIGTERM → SIGKILL on ``pid`` after validating it is ``role``.

    Returns ``pid`` if it was signalled, or ``0`` if it was already gone
    (idempotent). Raises :class:`LauncherError` if the PID is alive but is not a
    Resonite ``role`` process (guards against killing a reused PID).
    """
    try:
        proc = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return 0
    if not _argv0_endswith(proc, suffix):
        raise LauncherError(
            f"pid {pid} is not a Resonite {role} process "
            f"(argv0={_argv0_realpath(proc)!r}); refusing to kill it."
        )
    proc.terminate()  # SIGTERM
    _, alive = psutil.wait_procs([proc], timeout=timeout)
    for survivor in alive:
        survivor.kill()  # SIGKILL
    return pid


def terminate(
    resonite_pid: int | None = None,
    renderer_pid: int | None = None,
    *,
    timeout: float = 3.0,
) -> LaunchResult:
    """Stop Resonite by signalling its engine and renderer processes.

    Each target is sent ``SIGTERM``, given ``timeout`` seconds to exit, then
    ``SIGKILL`` if still alive. Idempotent: a PID that is already gone is
    skipped. With **no** arguments, the single running instance is auto-detected
    from the process table (``RESONITE_EXE``'s install dir); detecting more than
    one engine or renderer is an error (pass explicit PIDs to disambiguate).

    Args:
        resonite_pid: Engine host PID to kill (e.g. ``LaunchResult.resonite_pid``).
        renderer_pid: Renderer host PID to kill.
        timeout: Seconds to wait after ``SIGTERM`` before ``SIGKILL``.

    Returns:
        The :class:`LaunchResult` of PIDs actually signalled (``0`` for a role
        that was not running).

    Raises:
        LauncherError: more than one instance was detected in the no-argument
            path, or a given PID is alive but is not the expected Resonite process.
    """
    if resonite_pid is None and renderer_pid is None:
        install_dir = _install_dir_for_detection()
        engines = _find_engine_pids(install_dir)
        renderers = _find_renderer_pids(install_dir)
        if len(engines) > 1 or len(renderers) > 1:
            raise LauncherError(
                f"multiple Resonite instances detected (engine={engines} "
                f"renderer={renderers}); pass explicit PIDs to choose which to stop."
            )
        resonite_pid = engines[0] if engines else None
        renderer_pid = renderers[0] if renderers else None

    killed_engine = (
        _kill_pid(resonite_pid, _ENGINE_ARGV0_SUFFIX, "engine", timeout)
        if resonite_pid is not None
        else 0
    )
    killed_renderer = (
        _kill_pid(renderer_pid, _RENDERER_ARGV0_SUFFIX, "renderer", timeout)
        if renderer_pid is not None
        else 0
    )
    return LaunchResult(resonite_pid=killed_engine, renderer_pid=killed_renderer)


def terminate_all(*, timeout: float = 3.0) -> list[int]:
    """Stop every running Resonite instance and return the PIDs signalled.

    Detects all engine and renderer processes for the configured install
    (``RESONITE_EXE``'s install dir) and stages ``SIGTERM`` → ``SIGKILL`` on each,
    unlike :func:`terminate` which targets a single instance. Idempotent: a PID
    that is already gone is skipped (and excluded from the result).

    Args:
        timeout: Seconds to wait after ``SIGTERM`` before ``SIGKILL`` (per PID).

    Returns:
        The host PIDs actually signalled (engine and renderer), in detection
        order; an empty list means nothing was running.

    Raises:
        LauncherError: a detected PID is alive but is not the expected Resonite
            process (a reused PID).
    """
    install_dir = _install_dir_for_detection()
    killed: list[int] = []
    for pid in _find_engine_pids(install_dir):
        result = _kill_pid(pid, _ENGINE_ARGV0_SUFFIX, "engine", timeout)
        if result:
            killed.append(result)
    for pid in _find_renderer_pids(install_dir):
        result = _kill_pid(pid, _RENDERER_ARGV0_SUFFIX, "renderer", timeout)
        if result:
            killed.append(result)
    return killed
