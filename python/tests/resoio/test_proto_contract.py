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
    ContextMenuCloseRequest,
    ContextMenuGetStateRequest,
    ContextMenuHand,
    ContextMenuHighlightRequest,
    ContextMenuInvokeRequest,
    ContextMenuItem,
    ContextMenuOpenRequest,
    ContextMenuState,
    CursorGetPositionRequest,
    CursorReleaseRequest,
    CursorSetPositionRequest,
    CursorState,
    DashActionResult,
    DashElement,
    DashGetTreeRequest,
    DashHighlightRequest,
    DashInvokeRequest,
    DashListScreensRequest,
    DashRect,
    DashScreen,
    DashScreenList,
    DashScrollRequest,
    DashSetScreenRequest,
    DashState,
    DashTree,
    DisplayApplyResponse,
    DisplayConfig,
    DisplayGetRequest,
    DisplayState,
    FetchThumbnailRequest,
    FetchThumbnailResponse,
    FocusRequest,
    FocusResponse,
    GetCurrentRequest,
    GetCurrentResponse,
    GetServerInfoRequest,
    InventoryCopyRequest,
    InventoryEntry,
    InventoryEntryKind,
    InventoryListing,
    InventoryListRequest,
    InventoryMakeDirRequest,
    InventoryMoveRequest,
    InventoryMutationResult,
    InventoryRemoveRequest,
    InventorySpawnRequest,
    InventorySpawnResult,
    JoinRequest,
    JoinResponse,
    LeaveRequest,
    LeaveResponse,
    ListOpenWorldsRequest,
    ListOpenWorldsResponse,
    ListRecordsRequest,
    ListRecordsResponse,
    ListSessionsRequest,
    ListSessionsResponse,
    LocomotionCommand,
    LocomotionDriveSummary,
    LocomotionResetRequest,
    LocomotionResetSummary,
    ManipulationGetStateRequest,
    ManipulationGrabRequest,
    ManipulationGrabResult,
    ManipulationGrabState,
    ManipulationHand,
    ManipulationReleaseRequest,
    MicrophoneAudioFrame,
    MicrophoneStreamSummary,
    OpenWorld,
    PingRequest,
    PingResponse,
    RecordSort,
    RecordSortDirection,
    RecordSource,
    ServerInfo,
    ServerPlatform,
    SessionFilter,
    SpeakerStreamRequest,
    StartWorldRequest,
    StartWorldResponse,
    WorldRecord,
    WorldSession,
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
    # ContextMenu
    ContextMenuItem: {
        "index": 1,
        "label": 2,
        "enabled": 3,
        "has_icon": 4,
        "color_r": 5,
        "color_g": 6,
        "color_b": 7,
        "color_a": 8,
    },
    ContextMenuState: {
        "is_open": 1,
        "items": 2,
        "highlighted_index": 3,
    },
    ContextMenuOpenRequest: {
        "hand": 1,
    },
    ContextMenuCloseRequest: {
        "hand": 1,
    },
    ContextMenuGetStateRequest: {
        "hand": 1,
    },
    ContextMenuHighlightRequest: {
        "hand": 1,
        "index": 2,
    },
    ContextMenuInvokeRequest: {
        "hand": 1,
        "index": 2,
    },
    # Cursor
    CursorState: {
        "x": 1,
        "y": 2,
        "window_width": 3,
        "window_height": 4,
        "held": 5,
    },
    CursorSetPositionRequest: {
        "x": 1,
        "y": 2,
    },
    CursorGetPositionRequest: {},
    CursorReleaseRequest: {},
    # Inventory
    InventoryEntry: {
        "name": 1,
        "path": 2,
        "kind": 3,
        "record_id": 4,
        "asset_uri": 5,
        "is_public": 6,
        "last_modified_unix_nanos": 7,
    },
    InventoryListing: {
        "path": 1,
        "entries": 2,
    },
    InventoryMutationResult: {
        "path": 1,
        "record_id": 2,
    },
    InventorySpawnResult: {
        "source_path": 1,
        "spawned_slot_id": 2,
        "spawned_slot_name": 3,
    },
    InventoryListRequest: {
        "path": 1,
    },
    InventoryMakeDirRequest: {
        "path": 1,
    },
    InventoryCopyRequest: {
        "source_path": 1,
        "destination_path": 2,
        "recursive": 3,
    },
    InventoryMoveRequest: {
        "source_path": 1,
        "destination_path": 2,
    },
    InventoryRemoveRequest: {
        "path": 1,
        "recursive": 2,
    },
    InventorySpawnRequest: {
        "path": 1,
    },
    # Dash
    DashState: {
        "is_open": 1,
        "open_lerp": 2,
    },
    DashRect: {
        "x": 1,
        "y": 2,
        "width": 3,
        "height": 4,
        "is_screen_space": 5,
    },
    DashElement: {
        "ref_id": 1,
        "type": 2,
        "slot_name": 3,
        "locale_key": 4,
        "label": 5,
        "enabled": 6,
        "interactable": 7,
        "rect": 8,
        "parent_ref_id": 9,
        "depth": 10,
    },
    DashTree: {
        "elements": 1,
        "screen_width": 2,
        "screen_height": 3,
    },
    DashActionResult: {
        "ok": 1,
        "found": 2,
        "ref_id": 3,
        "detail": 4,
    },
    DashGetTreeRequest: {
        "interactable_only": 1,
        "root_ref_id": 2,
    },
    DashInvokeRequest: {
        "ref_id": 1,
    },
    DashHighlightRequest: {
        "ref_id": 1,
    },
    DashScrollRequest: {
        "ref_id": 1,
        "delta_x": 2,
        "delta_y": 3,
    },
    DashScreen: {
        "ref_id": 1,
        "key": 2,
        "name": 3,
        "label": 4,
        "is_current": 5,
        "enabled": 6,
    },
    DashScreenList: {
        "screens": 1,
    },
    DashListScreensRequest: {},
    DashSetScreenRequest: {
        "ref_id": 1,
        "key": 2,
    },
    # Manipulation
    # Field 2 was the former `WorldPoint point` (explicit world-coordinate
    # proximity grab), removed when grab became cursor-ray based. The proto
    # reserves number 2 and name "point"; neither may ever be reused.
    ManipulationGrabRequest: {
        "hand": 1,
        "radius": 3,
    },
    ManipulationReleaseRequest: {
        "hand": 1,
    },
    ManipulationGetStateRequest: {
        "hand": 1,
    },
    ManipulationGrabState: {
        "hand": 1,
        "is_holding": 2,
        "object_names": 3,
        "unix_nanos": 4,
    },
    ManipulationGrabResult: {
        "grabbed": 1,
        "state": 2,
    },
    # Connection
    PingRequest: {
        "message": 1,
    },
    PingResponse: {
        "message": 1,
        "server_unix_nanos": 2,
    },
    # Info
    GetServerInfoRequest: {},
    ServerInfo: {
        "mod_version": 1,
        "engine_version": 2,
        "platform": 3,
        "is_wine": 4,
    },
    # World
    WorldSession: {
        "session_id": 1,
        "name": 2,
        "description": 3,
        "host_user_id": 4,
        "host_username": 5,
        "session_urls": 6,
        "thumbnail_url": 7,
        "joined_users": 8,
        "active_users": 9,
        "maximum_users": 10,
        "tags": 11,
        "access_level": 12,
        "headless_host": 13,
        "mobile_friendly": 14,
        "corresponding_world_id": 15,
        "universe_id": 16,
        "session_begin_unix_nanos": 17,
        "last_update_unix_nanos": 18,
    },
    WorldRecord: {
        "record_id": 1,
        "owner_id": 2,
        "name": 3,
        "description": 4,
        "thumbnail_url": 5,
        "tags": 6,
        "record_url": 7,
        "last_modification_unix_nanos": 8,
    },
    OpenWorld: {
        "handle": 1,
        "session_id": 2,
        "name": 3,
        "focused": 4,
        "user_count": 5,
        "access_level": 6,
    },
    ListSessionsRequest: {
        "search": 1,
        "filter": 2,
        "min_active_users": 3,
        "page": 4,
        "page_size": 5,
    },
    ListSessionsResponse: {
        "sessions": 1,
        "total_count": 2,
        "page": 3,
        "page_size": 4,
    },
    ListRecordsRequest: {
        "source": 1,
        "required_tags": 2,
        "owner_id": 3,
        "offset": 4,
        "count": 5,
        "sort": 6,
        "sort_direction": 7,
        "search": 8,
    },
    ListRecordsResponse: {
        "records": 1,
        "has_more": 2,
        "offset": 3,
    },
    JoinRequest: {
        "session_id": 1,
        "session_url": 2,
        "focus": 3,
    },
    JoinResponse: {
        "world": 1,
    },
    StartWorldRequest: {
        "record_id": 1,
        "owner_id": 2,
        "focus": 3,
    },
    StartWorldResponse: {
        "world": 1,
    },
    ListOpenWorldsRequest: {},
    ListOpenWorldsResponse: {
        "worlds": 1,
    },
    FocusRequest: {
        "handle": 1,
    },
    FocusResponse: {
        "world": 1,
    },
    LeaveRequest: {
        "handle": 1,
    },
    LeaveResponse: {},
    GetCurrentRequest: {},
    GetCurrentResponse: {
        "world": 1,
        "has_world": 2,
    },
    FetchThumbnailRequest: {
        "uri": 1,
    },
    FetchThumbnailResponse: {
        "data": 1,
        "content_type": 2,
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
    ContextMenuHand: {
        "UNSPECIFIED": 0,
        "PRIMARY": 1,
        "LEFT": 2,
        "RIGHT": 3,
    },
    InventoryEntryKind: {
        "UNSPECIFIED": 0,
        "DIRECTORY": 1,
        "OBJECT": 2,
        "WORLD": 3,
        "LINK": 4,
        "UNKNOWN": 5,
    },
    ManipulationHand: {
        "UNSPECIFIED": 0,
        "PRIMARY": 1,
        "LEFT": 2,
        "RIGHT": 3,
    },
    # Info. The C# peer maps FrooxEngine.Platform onto these wire values;
    # renumbering silently misreports the server platform to old clients.
    ServerPlatform: {
        "UNSPECIFIED": 0,
        "WINDOWS": 1,
        "OSX": 2,
        "LINUX": 3,
        "ANDROID": 4,
        "OTHER": 5,
    },
    # World wire enums. NOTE: these carry an extra UNSPECIFIED=0 slot that
    # the public resoio enums fold into a default head (see the offset
    # mapping pinned in test_api_contract.py). Renumbering here silently
    # reinterprets historical wire data on the C# peer.
    SessionFilter: {
        "UNSPECIFIED": 0,
        "FRIENDS": 1,
        "HEADLESS": 2,
    },
    RecordSource: {
        "UNSPECIFIED": 0,
        "PUBLIC": 1,
        "FEATURED": 2,
        "OWN": 3,
        "GROUP": 4,
    },
    RecordSort: {
        "UNSPECIFIED": 0,
        "CREATION_DATE": 1,
        "LAST_UPDATE": 2,
        "FIRST_PUBLISH": 3,
        "TOTAL_VISITS": 4,
        "NAME": 5,
        "RANDOM": 6,
    },
    RecordSortDirection: {
        "UNSPECIFIED": 0,
        "DESCENDING": 1,
        "ASCENDING": 2,
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
