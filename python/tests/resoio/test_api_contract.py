"""Public API contract pins for the ``resoio`` package.

These tests are *contract pins*, not behaviour tests. They exist solely to
freeze the public surface of ``resoio`` so that downstream consumers can
rely on the names they import staying stable (a Hyrum's-law mitigation:
even attributes we did not promise can grow load-bearing consumers).

A failure here means "the public API changed" — that may be intentional
(a deliberate breaking-change bump), in which case the snapshot below
should be updated as part of the same change. It is NOT a behavioural
regression and should not be treated as one.

Scope:

- ``resoio.__all__`` exact membership (alphabetised by the source file)
- ``resoio.__version__`` shape (``str``, non-empty, sourced from package
  metadata)
- Public exception inheritance (``SocketNotFoundError`` /
  ``AmbiguousSocketError`` derive from ``RuntimeError``)
- Each public client class is importable directly off the ``resoio``
  namespace
"""

from __future__ import annotations

import dataclasses
import inspect

import pytest

import resoio

pytestmark = pytest.mark.api_contract


# ---------------------------------------------------------------------------
# __all__ membership
# ---------------------------------------------------------------------------


# Hard-coded snapshot of the names the package promises to export. Keep
# this list sorted (matches what ``resoio.__init__`` does) so the diff
# stays minimal when a single name is added or removed.
_EXPECTED_PUBLIC_NAMES = (
    "AmbiguousSocketError",
    "CameraClient",
    "ConnectionClient",
    "ContextMenuClient",
    "ContextMenuItem",
    "ContextMenuState",
    "CursorClient",
    "CursorState",
    "DashActionResult",
    "DashAmbiguousMatchError",
    "DashClient",
    "DashControl",
    "DashNoMatchError",
    "DashState",
    "DashTab",
    "DisplayClient",
    "DisplayInfo",
    "DriveSummary",
    "FetchThumbnailResponse",
    "Frame",
    "GrabResult",
    "GrabState",
    "GrabberClient",
    "InventoryClient",
    "InventoryEntry",
    "InventoryEntryKind",
    "InventoryListing",
    "InventoryMutationResult",
    "InventorySpawnResult",
    "InventoryThumbnail",
    "KickKind",
    "LifecycleClient",
    "ListRecordsResponse",
    "ListSessionsResponse",
    "LocomotionClient",
    "MicrophoneClient",
    "MicrophoneStreamSummary",
    "OpenWorld",
    "RecordSort",
    "RecordSortDirection",
    "RecordSource",
    "ResetSummary",
    "ServerInfo",
    "ServerPlatform",
    "SessionAccessLevel",
    "SessionClient",
    "SessionFilter",
    "SessionRole",
    "SessionRoles",
    "SessionSettings",
    "SessionUser",
    "SocketNotFoundError",
    "SpeakerChunk",
    "SpeakerClient",
    "UserRoleOverride",
    "WorldClient",
    "WorldRecord",
    "WorldSession",
    "__version__",
    "get_server_info",
    "shutdown",
    "terminate",
)


def test_all_matches_expected_public_names_exactly():
    assert tuple(resoio.__all__) == _EXPECTED_PUBLIC_NAMES


def test_each_name_in_all_resolves_on_the_package():
    """Every name in ``__all__`` must actually be reachable as
    ``resoio.<name>`` — a name listed but not bound would silently break ``from
    resoio import *`` for downstream code."""
    for name in resoio.__all__:
        assert hasattr(resoio, name), (
            f"resoio.__all__ lists {name!r} but resoio has no such attribute"
        )


# ---------------------------------------------------------------------------
# __version__ shape
# ---------------------------------------------------------------------------


def test_version_is_a_nonempty_string():
    assert isinstance(resoio.__version__, str)
    assert resoio.__version__


# ---------------------------------------------------------------------------
# Public exception hierarchy
# ---------------------------------------------------------------------------


def test_socket_not_found_error_extends_runtime_error():
    """Downstream callers may `except RuntimeError:` as a fallback catch- all;
    if we silently swap the base class they lose that path."""
    assert issubclass(resoio.SocketNotFoundError, RuntimeError)


def test_ambiguous_socket_error_extends_runtime_error():
    assert issubclass(resoio.AmbiguousSocketError, RuntimeError)


# ---------------------------------------------------------------------------
# Public client classes are directly importable off the package
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "client_name",
    [
        "ConnectionClient",
        "CameraClient",
        "SpeakerClient",
        "MicrophoneClient",
        "LocomotionClient",
        "DisplayClient",
        "ContextMenuClient",
        "CursorClient",
        "DashClient",
        "GrabberClient",
        "WorldClient",
        "InventoryClient",
        "LifecycleClient",
    ],
)
def test_client_class_is_importable_from_resoio(client_name: str):
    """Each modality client must be reachable as ``resoio.<Name>`` — the
    package-level import is the documented entry point."""
    client_cls = getattr(resoio, client_name)
    # Sanity: it's a class, not e.g. a re-exported instance or module.
    assert isinstance(client_cls, type), (
        f"resoio.{client_name} is {type(client_cls).__name__}, expected a class"
    )


# ---------------------------------------------------------------------------
# Public World enum member values
#
# These are the *public* (resoio-namespace) enums, NOT the generated wire
# enums. They are deliberately offset from the wire (the wire carries an
# extra ``UNSPECIFIED = 0`` slot the public enums fold into a documented
# default head: ALL / PUBLIC / CREATION_DATE / DESCENDING). Pinning their
# member values here freezes the public surface a downstream caller writes
# against (e.g. ``RecordSort.RANDOM``); the wire-value mapping is pinned
# separately in ``test_proto_contract.py``. This is a contract pin, not a
# behaviour test — an intentional change updates this snapshot in the same
# commit.
# ---------------------------------------------------------------------------


_EXPECTED_WORLD_ENUM_VALUES: dict[str, dict[str, int]] = {
    "SessionFilter": {
        "ALL": 0,
        "FRIENDS": 1,
        "HEADLESS": 2,
    },
    "RecordSource": {
        "PUBLIC": 0,
        "FEATURED": 1,
        "OWN": 2,
        "GROUP": 3,
    },
    "RecordSort": {
        "CREATION_DATE": 0,
        "LAST_UPDATE": 1,
        "FIRST_PUBLISH": 2,
        "TOTAL_VISITS": 3,
        "NAME": 4,
        "RANDOM": 5,
    },
    "RecordSortDirection": {
        "DESCENDING": 0,
        "ASCENDING": 1,
    },
}


@pytest.mark.parametrize(
    ("enum_name", "expected"),
    list(_EXPECTED_WORLD_ENUM_VALUES.items()),
)
def test_public_world_enum_members_match_snapshot(
    enum_name: str, expected: dict[str, int]
):
    """Pin each public World enum's member-name -> value.

    Downstream code references these by name (``RecordSource.OWN``); the
    int values are the documented public contract (offset from the wire
    enums on purpose). A rename or renumber here is a breaking change.
    """
    enum_cls = getattr(resoio, enum_name)
    actual = {member.name: member.value for member in enum_cls}
    assert actual == expected


# ---------------------------------------------------------------------------
# Public FetchThumbnailResponse + WorldClient.fetch_thumbnail signature
#
# These pin the public shape of the World thumbnail-fetch API a downstream
# caller writes against: the generated ``FetchThumbnailResponse`` value object
# (the hand-written ``Thumbnail`` mirror was removed in the API refinement —
# the method now returns the generated proto type directly) and the
# ``fetch_thumbnail(uri)`` entry point. Contract pins, not behaviour tests —
# the round-trip behaviour lives in test_world.py. An intentional change
# updates these snapshots in the same commit.
# ---------------------------------------------------------------------------


def test_fetch_thumbnail_response_is_a_dataclass():
    """``FetchThumbnailResponse`` is re-exported as the public thumbnail value
    object; downstream code constructs / unpacks it as a dataclass."""
    assert dataclasses.is_dataclass(resoio.FetchThumbnailResponse)


def test_fetch_thumbnail_response_field_names_and_types_match_snapshot():
    """Pin the public thumbnail payload fields: ``data: bytes`` then
    ``content_type: str`` (the generated proto field names/types)."""
    fields = dataclasses.fields(resoio.FetchThumbnailResponse)
    actual = {f.name: f.type for f in fields}
    assert actual == {
        "data": "bytes",
        "content_type": "str",
    }


def test_fetch_thumbnail_signature_takes_one_positional_uri_str():
    """Pin ``WorldClient.fetch_thumbnail`` as a coroutine taking a single
    positional ``uri: str`` argument."""
    assert inspect.iscoroutinefunction(resoio.WorldClient.fetch_thumbnail)
    sig = inspect.signature(resoio.WorldClient.fetch_thumbnail)
    params = list(sig.parameters.values())
    # self + uri
    assert [p.name for p in params] == ["self", "uri"]
    uri_param = sig.parameters["uri"]
    assert uri_param.annotation == "str"
    assert uri_param.kind in (
        inspect.Parameter.POSITIONAL_ONLY,
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
    )


def test_fetch_thumbnail_returns_fetch_thumbnail_response():
    """Pin the documented return type as the generated
    ``FetchThumbnailResponse`` value object (the ``Thumbnail`` mirror was
    removed; the method now returns the proto type directly)."""
    sig = inspect.signature(resoio.WorldClient.fetch_thumbnail)
    assert sig.return_annotation == "FetchThumbnailResponse"


# ---------------------------------------------------------------------------
# Public Info surface: ServerInfo dataclass + get_server_info entry point
#
# These pin the public shape of the server-info API a downstream caller
# writes against: the frozen ``ServerInfo`` value object and the
# BaseClient-independent ``get_server_info(socket_path=None)`` module
# function. ``fetch_server_info`` (the channel-level helper the version
# probe shares) is deliberately NOT in ``__all__`` — the exact-membership
# pin above already enforces that. Contract pins, not behaviour tests —
# round-trip behaviour lives in test_info.py.
# ---------------------------------------------------------------------------


def test_server_info_is_a_frozen_dataclass():
    """``ServerInfo`` is promised immutable; downstream code may rely on it
    being hashable-by-value / safe to share across tasks."""
    assert dataclasses.is_dataclass(resoio.ServerInfo)
    info = resoio.ServerInfo(
        mod_version="1.0.0",
        engine_version="2025.1.1.1",
        platform=resoio.ServerPlatform.LINUX,
        is_wine=False,
        resonite_pid=0,
        renderer_pid=0,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        info.mod_version = "2.0.0"  # pyright: ignore[reportAttributeAccessIssue]


def test_server_info_field_names_match_snapshot():
    """Pin the public payload fields in declaration order."""
    names = tuple(f.name for f in dataclasses.fields(resoio.ServerInfo))
    assert names == (
        "mod_version",
        "engine_version",
        "platform",
        "is_wine",
        "resonite_pid",
        "renderer_pid",
    )


def test_get_server_info_is_a_coroutine_with_optional_socket_path():
    """Pin ``get_server_info`` as an async module function whose sole parameter
    is ``socket_path`` defaulting to ``None`` (env resolution)."""
    assert inspect.iscoroutinefunction(resoio.get_server_info)
    sig = inspect.signature(resoio.get_server_info)
    params = list(sig.parameters.values())
    assert [p.name for p in params] == ["socket_path"]
    assert params[0].default is None


# ---------------------------------------------------------------------------
# WorldClient.list_records signature
#
# Pins the keyword-only public surface a downstream caller writes against
# (``client.list_records(search=..., source=..., ...)``). Contract pin, not a
# behaviour test — the request->wire round-trip lives in test_world.py. An
# intentional signature change updates this snapshot in the same commit.
# ---------------------------------------------------------------------------


# {param_name: (annotation, default)} for every keyword-only param, in
# declaration order. ``self`` is excluded; all params are keyword-only.
_EXPECTED_LIST_RECORDS_PARAMS: dict[str, tuple[str, object]] = {
    "source": ("RecordSource", resoio.RecordSource.PUBLIC),
    "required_tags": ("Sequence[str]", ()),
    "owner_id": ("str", ""),
    "search": ("str", ""),
    "offset": ("int", 0),
    "count": ("int", 0),
    "sort": ("RecordSort", resoio.RecordSort.CREATION_DATE),
    "sort_direction": ("RecordSortDirection", resoio.RecordSortDirection.DESCENDING),
}


def test_list_records_is_a_coroutine_returning_list_records_response():
    """Pin ``WorldClient.list_records`` as an async method returning the
    generated ``ListRecordsResponse`` (``.records`` list / ``.has_more`` /
    ``.offset``); the hand-written ``RecordPage`` mirror was removed."""
    assert inspect.iscoroutinefunction(resoio.WorldClient.list_records)
    sig = inspect.signature(resoio.WorldClient.list_records)
    assert sig.return_annotation == "ListRecordsResponse"


def test_list_sessions_is_a_coroutine_returning_list_sessions_response():
    """Pin ``WorldClient.list_sessions`` as an async method returning the
    generated ``ListSessionsResponse`` (``.sessions`` list / ``.total_count`` /
    ``.page`` / ``.page_size``); the hand-written ``SessionPage`` mirror was
    removed."""
    assert inspect.iscoroutinefunction(resoio.WorldClient.list_sessions)
    sig = inspect.signature(resoio.WorldClient.list_sessions)
    assert sig.return_annotation == "ListSessionsResponse"


def test_list_records_params_are_all_keyword_only_in_declared_order():
    """Pin that every public param (besides ``self``) is keyword-only, in the
    documented declaration order — positional calls are not promised."""
    sig = inspect.signature(resoio.WorldClient.list_records)
    params = [p for name, p in sig.parameters.items() if name != "self"]
    assert [p.name for p in params] == list(_EXPECTED_LIST_RECORDS_PARAMS)
    assert all(p.kind is inspect.Parameter.KEYWORD_ONLY for p in params)


def test_list_records_param_annotations_and_defaults_match_snapshot():
    """Pin each public param's annotation and default value, including the
    ``search: str = ""`` free-text query keyword."""
    sig = inspect.signature(resoio.WorldClient.list_records)
    actual = {
        name: (param.annotation, param.default)
        for name, param in sig.parameters.items()
        if name != "self"
    }
    assert actual == _EXPECTED_LIST_RECORDS_PARAMS
