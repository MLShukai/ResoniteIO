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
    "ContextMenuClient",
    "ContextMenuItem",
    "ContextMenuState",
    "DisplayClient",
    "DisplayInfo",
    "DriveSummary",
    "Frame",
    "LocomotionClient",
    "LocomotionCmd",
    "MicrophoneAudioChunk",
    "MicrophoneClient",
    "MicrophoneStreamSummary",
    "OpenWorld",
    "RecordPage",
    "RecordSort",
    "RecordSortDirection",
    "RecordSource",
    "ResetSummary",
    "SessionClient",
    "SessionFilter",
    "SessionPage",
    "SocketNotFoundError",
    "SpeakerClient",
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
        "SessionClient",
        "CameraClient",
        "SpeakerClient",
        "MicrophoneClient",
        "LocomotionClient",
        "DisplayClient",
        "ContextMenuClient",
        "WorldClient",
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
