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
    "CHANNELS",
    "DTYPE",
    "SAMPLE_RATE",
    "AmbiguousSocketError",
    "AudioChunk",
    "CameraClient",
    "ConnectionClient",
    "ContextMenuClient",
    "ContextMenuItem",
    "ContextMenuState",
    "CursorClient",
    "CursorState",
    "DashActionResult",
    "DashClient",
    "DashElement",
    "DashRect",
    "DashScreen",
    "DashState",
    "DashTree",
    "DisplayClient",
    "DisplayInfo",
    "DriveSummary",
    "Frame",
    "GrabResult",
    "GrabState",
    "InventoryClient",
    "InventoryEntry",
    "InventoryEntryKind",
    "InventoryListing",
    "InventoryMutationResult",
    "InventorySpawnResult",
    "LocomotionClient",
    "LocomotionCmd",
    "ManipulationClient",
    "MicrophoneAudioChunk",
    "MicrophoneClient",
    "MicrophoneStreamSummary",
    "OpenWorld",
    "RecordPage",
    "RecordSort",
    "RecordSortDirection",
    "RecordSource",
    "ResetSummary",
    "SessionFilter",
    "SessionPage",
    "SocketNotFoundError",
    "SpeakerClient",
    "Thumbnail",
    "WorldClient",
    "WorldRecord",
    "WorldSession",
    "__version__",
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
        "ManipulationClient",
        "WorldClient",
        "InventoryClient",
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
# Public Thumbnail dataclass + WorldClient.fetch_thumbnail signature
#
# These pin the public shape of the World thumbnail-fetch API a downstream
# caller writes against: the ``Thumbnail`` value object and the
# ``fetch_thumbnail(uri)`` entry point. Contract pins, not behaviour tests —
# the round-trip behaviour lives in test_world.py. An intentional change
# updates these snapshots in the same commit.
# ---------------------------------------------------------------------------


def test_thumbnail_is_a_frozen_dataclass():
    """Downstream code may use ``Thumbnail`` as a hashable value (dict key /
    set member); freezing the dataclass is part of the public promise."""
    assert dataclasses.is_dataclass(resoio.Thumbnail)
    params = resoio.Thumbnail.__dataclass_params__
    assert params.frozen is True


def test_thumbnail_field_names_and_types_match_snapshot():
    """Pin ``Thumbnail`` fields: ``data: bytes`` then ``content_type: str``."""
    fields = dataclasses.fields(resoio.Thumbnail)
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


def test_fetch_thumbnail_returns_thumbnail():
    """Pin the documented return type as the public ``Thumbnail`` value
    object."""
    sig = inspect.signature(resoio.WorldClient.fetch_thumbnail)
    assert sig.return_annotation == "Thumbnail"


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


def test_list_records_is_a_coroutine_returning_record_page():
    """Pin ``WorldClient.list_records`` as an async method returning the public
    ``RecordPage`` value object."""
    assert inspect.iscoroutinefunction(resoio.WorldClient.list_records)
    sig = inspect.signature(resoio.WorldClient.list_records)
    assert sig.return_annotation == "RecordPage"


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
