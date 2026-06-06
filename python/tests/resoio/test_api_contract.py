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
    "LocomotionClient",
    "LocomotionCmd",
    "MicrophoneAudioChunk",
    "MicrophoneClient",
    "MicrophoneStreamSummary",
    "ResetSummary",
    "SessionClient",
    "SocketNotFoundError",
    "SpeakerClient",
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
        "DashClient",
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
