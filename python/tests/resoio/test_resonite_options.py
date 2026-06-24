"""Tests for :mod:`resoio.resonite_options` (typed Resonite launch options).

``ResoniteOptions.to_args`` is a pure function (no I/O, no env), so these are
plain unit tests with no fakes: they pin the rendered argv fragment for every
value kind — bare flags, value pairs, enums, the repeated ``-LoadAssembly``, the
irregular Resonite casings (``-NoUI`` / ``-ForceLANOnly`` / ``-Forceintrotutorial``),
declaration-order determinism, and the ``skip_intro_tutorial`` default.
"""

from __future__ import annotations

import dataclasses

import pytest

from resoio.resonite_options import CloudProfile, Device, ResoniteOptions


def test_default_emits_only_skip_intro_tutorial():
    # The single non-False default; preserves launch()'s historical behaviour.
    assert ResoniteOptions().to_args() == ["-SkipIntroTutorial"]


def test_skip_intro_tutorial_can_be_disabled():
    assert ResoniteOptions(skip_intro_tutorial=False).to_args() == []


def test_force_intro_tutorial_uses_resonite_irregular_casing():
    opts = ResoniteOptions(skip_intro_tutorial=False, force_intro_tutorial=True)
    assert opts.to_args() == ["-Forceintrotutorial"]


@pytest.mark.parametrize(
    ("field", "flag"),
    [
        ("screen", "-Screen"),
        ("verbose", "-Verbose"),
        ("kiosk", "-Kiosk"),
        ("no_ui", "-NoUI"),
        ("force_lan_only", "-ForceLANOnly"),
        ("force_sranipal", "-ForceSRAnipal"),
        ("invisible", "-Invisible"),
        ("legacy_steamvr_input", "-LegacySteamVRInput"),
        ("announce_home_on_lan", "-AnnounceHomeOnLAN"),
        ("use_resonite_camera", "-UseResoniteCamera"),
        ("delete_unsynced_cloud_records", "-DeleteUnsyncedCloudRecords"),
    ],
)
def test_bool_flag_renders_as_bare_flag(field: str, flag: str):
    opts = ResoniteOptions(skip_intro_tutorial=False, **{field: True})
    assert opts.to_args() == [flag]


@pytest.mark.parametrize(
    ("field", "arg"),
    [
        ("data_path", "-DataPath"),
        ("cache_path", "-CachePath"),
        ("logs_path", "-LogsPath"),
        ("engine_config", "-EngineConfig"),
        ("watchdog", "-Watchdog"),
        ("join", "-Join"),
        ("open", "-Open"),
        ("bootstrap", "-Bootstrap"),
        ("export_database_all", "-ExportDatabaseAll"),
        ("export_database_machine", "-ExportDatabaseMachine"),
    ],
)
def test_string_value_renders_as_arg_value_pair(field: str, arg: str):
    opts = ResoniteOptions(skip_intro_tutorial=False, **{field: "/some/path"})
    assert opts.to_args() == [arg, "/some/path"]


@pytest.mark.parametrize(
    ("field", "arg"),
    [
        ("cubemap_resolution", "-CubemapResolution"),
        ("scratchspace", "-Scratchspace"),
        ("background_workers", "-BackgroundWorkers"),
        ("priority_workers", "-PriorityWorkers"),
    ],
)
def test_int_value_renders_as_stringified_pair(field: str, arg: str):
    opts = ResoniteOptions(skip_intro_tutorial=False, **{field: 7})
    assert opts.to_args() == [arg, "7"]


@pytest.mark.parametrize(
    ("device", "expected"),
    [
        (Device.OCULUS, "Oculus"),
        (Device.STEAM_VR, "SteamVR"),
        (Device.STATIC_CAMERA_360, "StaticCamera360"),
    ],
)
def test_device_enum_renders_wire_value(device: Device, expected: str):
    opts = ResoniteOptions(skip_intro_tutorial=False, device=device)
    assert opts.to_args() == ["-Device", expected]


def test_cloud_profile_enum_renders_wire_value():
    opts = ResoniteOptions(
        skip_intro_tutorial=False, cloud_profile=CloudProfile.STAGING
    )
    assert opts.to_args() == ["-CloudProfile", "Staging"]


def test_load_assembly_repeats_the_flag_per_path():
    opts = ResoniteOptions(skip_intro_tutorial=False, load_assembly=("a.dll", "b.dll"))
    assert opts.to_args() == ["-LoadAssembly", "a.dll", "-LoadAssembly", "b.dll"]


def test_empty_load_assembly_is_omitted():
    assert ResoniteOptions(skip_intro_tutorial=False, load_assembly=()).to_args() == []


def test_false_flags_and_none_values_are_omitted():
    opts = ResoniteOptions(
        skip_intro_tutorial=False,
        screen=False,
        data_path=None,
        device=None,
        cubemap_resolution=None,
    )
    assert opts.to_args() == []


def test_fields_render_in_declaration_order():
    # skip_intro_tutorial (first) -> screen (early) -> verbose (late): the output
    # order is deterministic regardless of kwarg order at construction.
    opts = ResoniteOptions(verbose=True, screen=True)
    assert opts.to_args() == ["-SkipIntroTutorial", "-Screen", "-Verbose"]


def test_value_and_flag_combination():
    opts = ResoniteOptions(
        skip_intro_tutorial=False,
        data_path="/data",
        cache_path="/cache",
        verbose=True,
    )
    assert opts.to_args() == [
        "-DataPath",
        "/data",
        "-CachePath",
        "/cache",
        "-Verbose",
    ]


def test_options_are_frozen():
    opts = ResoniteOptions()
    with pytest.raises(dataclasses.FrozenInstanceError):
        opts.verbose = True  # type: ignore[misc]
