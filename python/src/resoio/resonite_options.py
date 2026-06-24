"""Typed Resonite launch options for :func:`resoio.launcher.launch`.

Resonite's client accepts a large set of command-line launch arguments
(documented at https://wiki.resonite.com/Command_line_arguments).
:class:`ResoniteOptions` exposes them as a typed, immutable value object so
callers get autocomplete and type checking instead of hand-assembling raw
``-Flag`` strings. :meth:`ResoniteOptions.to_args` renders the argv fragment
that :func:`resoio.launcher.launch` weaves in just ahead of ``extra_args``.

Two renderer-overriding arguments — ``-Renderer`` and ``-AttachRenderer`` — are
intentionally **not** modelled here. They break ``launch``'s renderer-PID
detection (which pins ``<install>/Renderer/Renderite.Renderer.exe``) and the
doorstop preloader lookup, so ``launch`` would time out waiting for the renderer
to appear. If you really need them, pass them through ``launch(extra_args=...)``
with the understanding that PID detection will not work.

Path-valued options (``data_path`` / ``cache_path`` / …) are passed through
verbatim; :meth:`to_args` does not absolutise them. ``launch`` starts the
process with ``cwd`` at the Resonite install dir, so a relative path resolves
against that directory — absolutise on the caller side if you need otherwise.
"""

from __future__ import annotations

import dataclasses
import enum
from dataclasses import dataclass
from typing import cast

__all__ = [
    "CloudProfile",
    "Device",
    "ResoniteOptions",
]


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
class ResoniteOptions:
    """Typed Resonite command-line launch options.

    Each field maps to one Resonite launch argument. Booleans render as a bare
    flag when ``True`` and are omitted when ``False``; value-bearing fields are
    omitted when ``None`` (or empty). :meth:`to_args` renders them in field
    declaration order.

    All fields default to Resonite's own default behaviour except
    ``skip_intro_tutorial``, which defaults to ``True`` to preserve ``launch``'s
    historical behaviour of always skipping the intro tutorial world.
    """

    # --- intro / home --------------------------------------------------------
    skip_intro_tutorial: bool = True
    """Skip the intro tutorial world (``-SkipIntroTutorial``).

    Defaults to
    ``True`` to preserve ``launch``'s historical behaviour.
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
        for field in dataclasses.fields(self):
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
_FIELD_NAMES = {field.name for field in dataclasses.fields(ResoniteOptions)}
if _ARG_NAMES.keys() != _FIELD_NAMES:
    raise RuntimeError(
        "_ARG_NAMES is out of sync with ResoniteOptions fields: "
        f"{_ARG_NAMES.keys() ^ _FIELD_NAMES}"
    )
