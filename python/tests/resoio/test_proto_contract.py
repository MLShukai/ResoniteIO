"""Proto wire contract pins for ``resoio._generated.resonite_io.v1``.

These tests pin the proto **wire format** — field numbers and enum
values — so that an accidental field renumber in a ``.proto`` is
detected before it ships. They are *contract pins*, not behaviour
tests; a failure means the wire has changed, which breaks any peer
(C# mod, older Python clients) talking to a different generated
version.

Why pin numbers, not names: protobuf's wire format is keyed on the
field number, not the field name. Renaming a field is a source-level
break only; renumbering one silently corrupts wire data.

A failure here is signal that:

- An intentional schema bump occurred — update the expected map below
  in the same commit.
- An accidental edit slipped through — revert it.

We introspect ``betterproto2`` metadata via ``dataclasses.fields`` /
``f.metadata['betterproto'].number`` because that mirrors how the
generated code itself declares the wire mapping
(``betterproto2.field(N, ...)``).
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from resoio._generated.resonite_io.v1 import (
    AudioFrame,
    CameraFrame,
    CameraFrameFormat,
    CameraStreamRequest,
    DisplayApplyResponse,
    DisplayConfig,
    DisplayGetRequest,
    DisplayState,
    LocomotionCommand,
    LocomotionDriveSummary,
    LocomotionResetRequest,
    LocomotionResetSummary,
    MicrophoneAudioFrame,
    MicrophoneStreamSummary,
    PingRequest,
    PingResponse,
    SpeakerStreamRequest,
)

pytestmark = pytest.mark.api_contract


def _field_numbers(message_cls: type) -> dict[str, int]:
    """Return ``{field_name: wire_number}`` for the message class.

    Uses the same ``betterproto2`` field metadata the generated code
    emits via ``betterproto2.field(N, ...)``. Empty messages (no
    declared fields, e.g. ``SpeakerStreamRequest``) yield ``{}``.
    """
    result: dict[str, int] = {}
    for f in dataclasses.fields(message_cls):
        meta: Any = f.metadata.get("betterproto")
        if meta is None:
            continue
        result[f.name] = meta.number
    return result


# ---------------------------------------------------------------------------
# Expected wire snapshots (alphabetised by message; field maps preserve
# the order the proto declares them).
# ---------------------------------------------------------------------------


_EXPECTED_FIELDS: dict[type, dict[str, int]] = {
    # Camera
    CameraFrame: {
        "width": 1,
        "height": 2,
        "format": 3,
        "unix_nanos": 4,
        "frame_id": 5,
        "pixels": 6,
    },
    CameraStreamRequest: {
        "width": 1,
        "height": 2,
        "fps_limit": 3,
    },
    # Speaker (shared AudioFrame message, empty request body)
    AudioFrame: {
        "frame_id": 1,
        "unix_nanos": 2,
        "sample_count": 3,
        "samples": 4,
    },
    SpeakerStreamRequest: {},
    # Microphone
    MicrophoneAudioFrame: {
        "frame_id": 1,
        "unix_nanos": 2,
        "sample_count": 3,
        "samples": 4,
    },
    MicrophoneStreamSummary: {
        "received_frames": 1,
        "received_samples": 2,
        "dropped_frames": 3,
        "unix_nanos": 4,
    },
    # Locomotion
    LocomotionCommand: {
        "move_forward": 1,
        "move_right": 2,
        "move_up": 3,
        "yaw_rate": 4,
        "pitch_rate": 5,
        "jump": 6,
        "velocity": 7,
        "crouch": 8,
        "unix_nanos": 9,
    },
    LocomotionDriveSummary: {
        "received_count": 1,
        "dropped_count": 2,
        "unix_nanos": 3,
    },
    LocomotionResetRequest: {
        "move": 1,
        "look": 2,
        "crouch": 3,
        "jump": 4,
        "unix_nanos": 5,
    },
    LocomotionResetSummary: {
        "move": 1,
        "look": 2,
        "crouch": 3,
        "jump": 4,
        "unix_nanos": 5,
    },
    # Display
    DisplayConfig: {
        "width": 1,
        "height": 2,
        "max_fps": 3,
    },
    DisplayState: {
        "width": 1,
        "height": 2,
        "max_fps": 3,
    },
    DisplayGetRequest: {},
    DisplayApplyResponse: {},
    # Session
    PingRequest: {
        "message": 1,
    },
    PingResponse: {
        "message": 1,
        "server_unix_nanos": 2,
    },
}


@pytest.mark.parametrize(
    ("message_cls", "expected"),
    list(_EXPECTED_FIELDS.items()),
    ids=lambda v: getattr(v, "__name__", repr(v)),
)
def test_message_field_numbers_match_snapshot(
    message_cls: type, expected: dict[str, int]
):
    """Pin field-name to wire-number for every public message in v1."""
    assert _field_numbers(message_cls) == expected


# ---------------------------------------------------------------------------
# Enum wire-value snapshots
# ---------------------------------------------------------------------------


_EXPECTED_ENUM_VALUES: dict[type, dict[str, int]] = {
    CameraFrameFormat: {
        "UNSPECIFIED": 0,
        "RGBA8": 1,
    },
}


@pytest.mark.parametrize(
    ("enum_cls", "expected"),
    list(_EXPECTED_ENUM_VALUES.items()),
    ids=lambda v: getattr(v, "__name__", repr(v)),
)
def test_enum_values_match_snapshot(enum_cls: type, expected: dict[str, int]):
    """Pin enum member-name to wire-value.

    Renumbering an enum silently reinterprets historical wire data on
    the consumer.
    """
    actual = {name: member.value for name, member in enum_cls.__members__.items()}
    assert actual == expected
