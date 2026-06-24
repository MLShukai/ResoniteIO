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

import enum
import logging
import os
import shutil
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, fields
from pathlib import Path
from typing import cast

import psutil

__all__ = [
    "CloudProfile",
    "Device",
    "LaunchOptions",
    "LaunchResult",
    "LauncherError",
    "launch",
    "terminate",
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
    ``umu-run`` on PATH, an instance already running, more than one instance
    detected (the single-instance assumption is violated), or the engine /
    renderer not appearing before the timeout.
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
# Launch options
# ---------------------------------------------------------------------------


class Device(enum.Enum):
    """Headset / display device to force (``-Device <value>``)."""

    STEAM_VR = "SteamVR"
    WINDOWS_MR = "WindowsMR"
    OCULUS = "Oculus"
    OCULUS_QUEST = "OculusQuest"
    SCREEN_360 = "Screen360"
    STATIC_CAMERA = "StaticCamera"
    STATIC_CAMERA_360 = "StaticCamera360"


class CloudProfile(enum.Enum):
    """Cloud API server set to target (``-CloudProfile <value>``)."""

    PRODUCTION = "Production"
    STAGING = "Staging"
    LOCAL = "Local"


@dataclass(frozen=True, slots=True)
class LaunchOptions:
    """Typed Resonite command-line launch options for :func:`launch`.

    Resonite's client accepts a large set of command-line launch arguments
    (documented at https://wiki.resonite.com/Command_line_arguments). Each field
    maps to one of them, so callers get autocomplete and type checking instead of
    hand-assembling raw ``-Flag`` strings into ``extra_args``. :meth:`to_args`
    renders the argv fragment that :func:`launch` weaves in just ahead of
    ``extra_args`` (so a raw ``extra_args`` entry can still override an option).

    Booleans render as a bare flag when ``True`` and are omitted when ``False``;
    value-bearing fields are omitted when ``None`` (or empty), and fields render
    in declaration order. All fields default to Resonite's own default behaviour
    except ``skip_intro_tutorial``, which defaults to ``True`` to preserve
    :func:`launch`'s historical behaviour of always skipping the intro tutorial.

    The renderer-overriding arguments ``-Renderer`` and ``-AttachRenderer`` are
    intentionally **not** modelled: they break :func:`launch`'s renderer-PID
    detection (which pins ``<install>/Renderer/Renderite.Renderer.exe``) and the
    doorstop preloader lookup, so the launch would time out waiting for the
    renderer. Pass them through ``launch(extra_args=...)`` only if you accept that
    PID detection will not work.

    Path-valued options are passed through verbatim; :meth:`to_args` does not
    absolutise them. :func:`launch` starts the process with ``cwd`` at the
    Resonite install dir, so a relative path resolves against that directory.
    """

    # --- intro / home --------------------------------------------------------
    skip_intro_tutorial: bool = True
    """Skip the intro tutorial world (``-SkipIntroTutorial``).

    Defaults to
    ``True`` to preserve :func:`launch`'s historical behaviour.
    """
    force_intro_tutorial: bool = False
    """Force the intro tutorial to run (``-Forceintrotutorial``; note
    Resonite's irregular casing)."""
    do_not_auto_load_home: bool = False
    """Do not auto-load the cloud Home on start (``-DoNotAutoLoadHome``)."""

    # --- device / display ----------------------------------------------------
    screen: bool = False
    """Force desktop screen mode instead of VR (``-Screen``)."""
    device: Device | None = None
    """Force a specific headset / display device (``-Device``)."""
    legacy_steamvr_input: bool = False
    """Use legacy SteamVR input handling (``-LegacySteamVRInput``)."""
    force_sranipal: bool = False
    """Force SRAnipal init for HTC eye/lip tracking (``-ForceSRAnipal``)."""
    force_babble: bool = False
    """Force the Project Babble face-tracking driver (``-ForceBabble``)."""
    force_reticle_above_horizon: bool = False
    """Disallow looking below the horizon in desktop first-person view
    (``-ForceReticleAboveHorizon``)."""
    cubemap_resolution: int | None = None
    """Cubemap resolution for 360° equirectangular rendering
    (``-CubemapResolution``)."""

    # --- session / start -----------------------------------------------------
    join: str | None = None
    """Join a session on start: ``Auto`` for active LAN sessions, or a session
    URI (``-Join``)."""
    open: str | None = None
    """Open a world at the given ``resrec`` URL on start (``-Open``)."""
    bootstrap: str | None = None
    """Run a custom bootstrap function in the named class (``-Bootstrap``)."""
    scratchspace: int | None = None
    """Start a scratchspace world on the given port (``-Scratchspace``;
    legacy)."""
    announce_home_on_lan: bool = False
    """Make Home and userspace accessible from LAN (``-AnnounceHomeOnLAN``)."""

    # --- static camera presets ----------------------------------------------
    camera_biggest_group: bool = False
    """Init the static camera with the biggest-group preset
    (``-CameraBiggestGroup``)."""
    camera_timelapse: bool = False
    """Init the static camera with the timelapse preset
    (``-CameraTimelapse``)."""
    camera_stay_behind: bool = False
    """Init the static camera with the stay-behind preset
    (``-CameraStayBehind``)."""
    camera_stay_in_front: bool = False
    """Init the static camera with the stay-in-front preset
    (``-CameraStayInFront``)."""
    use_resonite_camera: bool = False
    """Spawn the static camera as a Resonite Camera with zoom controls
    (``-UseResoniteCamera``)."""

    # --- data / cache / logs paths ------------------------------------------
    data_path: str | None = None
    """Database directory location (``-DataPath``)."""
    cache_path: str | None = None
    """Cache directory location (``-CachePath``)."""
    logs_path: str | None = None
    """Log files directory location (``-LogsPath``)."""

    # --- database maintenance -----------------------------------------------
    repair_database: bool = False
    """Repair the local database on start (``-RepairDatabase``)."""
    generate_precache: bool = False
    """Cache cloud records to ``RuntimeData/PreCache``
    (``-GeneratePrecache``)."""
    export_database_all: str | None = None
    """Export all local database records to a directory
    (``-ExportDatabaseAll``)."""
    export_database_machine: str | None = None
    """Export records owned by this machine to a directory
    (``-ExportDatabaseMachine``)."""

    # --- settings / dash -----------------------------------------------------
    reset_dash: bool = False
    """Reset the dashboard layout to default (``-ResetDash``)."""
    never_save_settings: bool = False
    """Do not save/sync settings — testing only (``-NeverSaveSettings``)."""
    never_save_dash: bool = False
    """Do not save/sync dashboard changes — testing only
    (``-NeverSaveDash``)."""

    # --- UI / privacy / networking ------------------------------------------
    kiosk: bool = False
    """Run in Kiosk mode: hide userspace UI, disable guest teleport
    (``-Kiosk``)."""
    no_ui: bool = False
    """Hide the userspace UI (``-NoUI``)."""
    force_lan_only: bool = False
    """Announce sessions on LAN only, not the internet (``-ForceLANOnly``)."""
    invisible: bool = False
    """Force online status to invisible on login (``-Invisible``)."""
    disable_platform_interfaces: bool = False
    """Disable all platform interfaces — Discord/Steam/clipboard
    (``-DisablePlatformInterfaces``)."""
    force_no_voice: bool = False
    """Do not set up avatars with voice (``-ForceNoVoice``)."""
    force_april_fools: bool = False
    """Activate April Fools mode regardless of date (``-ForceAprilFools``)."""

    # --- modding -------------------------------------------------------------
    load_assembly: tuple[str, ...] = ()
    """Extra CLR assemblies / DLLs to load into the process (``-LoadAssembly``,
    one occurrence per path)."""

    # --- debugging -----------------------------------------------------------
    verbose: bool = False
    """Produce detailed engine-initialisation logs (``-Verbose``)."""
    validate_types: bool = False
    """Check and log DataModel type validation (``-ValidateTypes``)."""
    watchdog: str | None = None
    """Periodically write the current time to this file for restart detection
    (``-Watchdog``)."""
    engine_config: str | None = None
    """Use a custom engine config file (``-EngineConfig``)."""
    cloud_profile: CloudProfile | None = None
    """Cloud API server set to use, for debugging (``-CloudProfile``)."""

    # --- dangerous (data loss / worker tuning) ------------------------------
    delete_unsynced_cloud_records: bool = False
    """WARNING: irreversibly deletes local unsynced cloud records and
    re-downloads cloud copies (``-DeleteUnsyncedCloudRecords``)."""
    force_sync_conflicting_cloud_records: bool = False
    """WARNING: forces conflicting local records to overwrite their cloud copies
    (``-ForceSyncConflictingCloudRecords``)."""
    background_workers: int | None = None
    """WARNING: overrides the background worker process count; wrong values can
    destabilise the engine (``-BackgroundWorkers``)."""
    priority_workers: int | None = None
    """WARNING: overrides the priority worker process count; wrong values can
    destabilise the engine (``-PriorityWorkers``)."""

    def to_args(self) -> list[str]:
        """Render the Resonite argv fragment for these options.

        Walks the fields in declaration order so the output is deterministic.
        Booleans emit a bare flag when ``True``; ``None`` / empty values are
        omitted; enums emit their wire ``value``; ``load_assembly`` emits one
        ``-LoadAssembly <path>`` pair per entry.
        """
        args: list[str] = []
        for field in fields(self):
            arg = _ARG_NAMES[field.name]
            value = getattr(self, field.name)
            # bool before int: bool is a subclass of int.
            if isinstance(value, bool):
                if value:
                    args.append(arg)
            elif isinstance(value, tuple):
                for item in cast("tuple[str, ...]", value):
                    args.extend((arg, item))
            elif isinstance(value, enum.Enum):
                args.extend((arg, value.value))
            elif value is not None:
                args.extend((arg, str(value)))
        return args


# Field name -> Resonite launch argument. Kept explicit (rather than deriving
# from the field name) so the irregular casings Resonite uses — ``-NoUI``,
# ``-ForceSRAnipal``, ``-ForceLANOnly``, ``-Forceintrotutorial`` — read plainly.
_ARG_NAMES: dict[str, str] = {
    "skip_intro_tutorial": "-SkipIntroTutorial",
    "force_intro_tutorial": "-Forceintrotutorial",
    "do_not_auto_load_home": "-DoNotAutoLoadHome",
    "screen": "-Screen",
    "device": "-Device",
    "legacy_steamvr_input": "-LegacySteamVRInput",
    "force_sranipal": "-ForceSRAnipal",
    "force_babble": "-ForceBabble",
    "force_reticle_above_horizon": "-ForceReticleAboveHorizon",
    "cubemap_resolution": "-CubemapResolution",
    "join": "-Join",
    "open": "-Open",
    "bootstrap": "-Bootstrap",
    "scratchspace": "-Scratchspace",
    "announce_home_on_lan": "-AnnounceHomeOnLAN",
    "camera_biggest_group": "-CameraBiggestGroup",
    "camera_timelapse": "-CameraTimelapse",
    "camera_stay_behind": "-CameraStayBehind",
    "camera_stay_in_front": "-CameraStayInFront",
    "use_resonite_camera": "-UseResoniteCamera",
    "data_path": "-DataPath",
    "cache_path": "-CachePath",
    "logs_path": "-LogsPath",
    "repair_database": "-RepairDatabase",
    "generate_precache": "-GeneratePrecache",
    "export_database_all": "-ExportDatabaseAll",
    "export_database_machine": "-ExportDatabaseMachine",
    "reset_dash": "-ResetDash",
    "never_save_settings": "-NeverSaveSettings",
    "never_save_dash": "-NeverSaveDash",
    "kiosk": "-Kiosk",
    "no_ui": "-NoUI",
    "force_lan_only": "-ForceLANOnly",
    "invisible": "-Invisible",
    "disable_platform_interfaces": "-DisablePlatformInterfaces",
    "force_no_voice": "-ForceNoVoice",
    "force_april_fools": "-ForceAprilFools",
    "load_assembly": "-LoadAssembly",
    "verbose": "-Verbose",
    "validate_types": "-ValidateTypes",
    "watchdog": "-Watchdog",
    "engine_config": "-EngineConfig",
    "cloud_profile": "-CloudProfile",
    "delete_unsynced_cloud_records": "-DeleteUnsyncedCloudRecords",
    "force_sync_conflicting_cloud_records": "-ForceSyncConflictingCloudRecords",
    "background_workers": "-BackgroundWorkers",
    "priority_workers": "-PriorityWorkers",
}

# Guard against the hand-maintained mapping drifting from the dataclass fields.
_FIELD_NAMES = {field.name for field in fields(LaunchOptions)}
if _ARG_NAMES.keys() != _FIELD_NAMES:
    raise RuntimeError(
        "_ARG_NAMES is out of sync with LaunchOptions fields: "
        f"{_ARG_NAMES.keys() ^ _FIELD_NAMES}"
    )


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
    options: LaunchOptions | None = None,
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

    argv = ["umu-run", exe]
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

    # Resonite launch options (incl. -SkipIntroTutorial via its default) go after
    # the umu-run flags and before extra_args, so a raw extra_args entry can still
    # override an option (Resonite takes the last occurrence).
    argv += (options or LaunchOptions()).to_args()
    argv += list(extra_args)
    return argv, env, log_path


# ---------------------------------------------------------------------------
# launch
# ---------------------------------------------------------------------------


def _wait_for_single(
    finder: Callable[[], list[int]], label: str, deadline: float, poll_interval: float
) -> int:
    """Poll ``finder`` until it returns exactly one PID; return it.

    Raises :class:`LauncherError` if more than one is ever seen (the
    single-instance assumption is violated) or if none appears by ``deadline``.
    """
    while True:
        pids = finder()
        if len(pids) > 1:
            raise LauncherError(
                f"multiple {label} processes detected ({pids}); expected exactly "
                "one. Stop the extra Resonite instances and retry."
            )
        if len(pids) == 1:
            return pids[0]
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
    options: LaunchOptions | None = None,
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
        options: Typed Resonite launch options (``-DataPath``, ``-Screen``, …).
            ``None`` uses the defaults, which still skip the intro tutorial.
            See :class:`LaunchOptions`.
        extra_args: Extra arguments forwarded to ``Resonite.exe`` after
            ``options``. The raw escape hatch for anything ``options`` does not
            model; reconciling overlaps with ``options`` is the caller's job.
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
        LauncherError: Resonite.exe / the mod / ``umu-run`` is missing, an
            instance is already running, more than one engine/renderer is
            detected, or a process did not appear before ``wait_timeout``.
    """
    exe = _resolve_resonite_exe(resonite_exe)
    install_dir = os.path.dirname(os.path.realpath(exe))

    already = _find_engine_pids(install_dir)
    if already:
        raise LauncherError(
            f"Resonite is already running (engine pid(s) {already}). Stop it first "
            "with `resoio terminate` before launching a new instance."
        )

    argv, env, log_path = _build_command(
        exe,
        install_dir,
        mod_path,
        vanilla,
        extra_args,
        options=options,
        prefix=prefix,
        proton_path=proton_path,
    )
    _logger.info("launching Resonite: %s (cwd=%s)", " ".join(argv), install_dir)

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
    resonite_pid = _wait_for_single(
        lambda: _find_engine_pids(install_dir), "engine", deadline, poll_interval
    )
    renderer_pid = _wait_for_single(
        lambda: _find_renderer_pids(install_dir), "renderer", deadline, poll_interval
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
