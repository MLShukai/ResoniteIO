"""Shared gRPC channel lifecycle for the per-modality client classes.

Every ``<Modality>Client`` opens a single :class:`grpclib.client.Channel`
on ``__aenter__`` (resolving the UDS path lazily so env vars patched
between construction and connection are honoured), builds a stub on it,
and closes the channel on ``__aexit__``. :class:`_BaseClient` factors that
boilerplate out; subclasses supply only their stub type and their RPC
methods.
"""

from __future__ import annotations

import glob
import logging
import os
from abc import ABC, abstractmethod
from importlib import metadata
from pathlib import Path
from types import TracebackType
from typing import ClassVar, Self

# betterproto2 generates one ``ServiceStub`` subclass per service; bounding
# the type var on that base makes each subclass pin a concrete stub type.
from betterproto2.grpclib.grpclib_client import ServiceStub
from grpclib.client import Channel

__all__ = [
    "AmbiguousSocketError",
    "SocketNotFoundError",
    "_BaseClient",
    "_reset_version_check",
]

_SOCKET_GLOB = "resonite-*.sock"
_DEFAULT_SOCKET_DIR_NAME = ".resonite-io"

# PyPI distribution name (the import package is `resoio`); used for version lookup.
_DISTRIBUTION_NAME = "resonite-io"
_RELEASES_URL = "https://github.com/MLShukai/ResoniteIO/releases"
_LATEST_ZIP_CMD = (
    "curl -L -o ResoniteIO.zip "
    "https://github.com/MLShukai/ResoniteIO/releases/latest/download/ResoniteIO.zip"
)

# Process-global guard: the mod/client version mismatch warning fires at most once
# per process, on the first successful version probe across any modality client.
_version_checked = False


def _reset_version_check() -> None:
    """Reset the once-per-process version-probe guard (test hook only)."""
    global _version_checked
    _version_checked = False


async def _maybe_warn_version_mismatch(
    channel: Channel, logger: logging.Logger
) -> None:
    """Probe the mod version once per process and warn on mismatch.

    Runs on the first client ``__aenter__`` after which it never repeats (guarded
    by :data:`_version_checked`). Never raises: a connection-level failure leaves
    the guard unset so a later connect retries, while a server response (match,
    mismatch, or an old mod missing the RPC) marks the probe done.
    """
    global _version_checked
    if _version_checked:
        return

    # Local imports keep the import graph acyclic (connection stub <-> _client).
    from grpclib.const import Status
    from grpclib.exceptions import GRPCError

    from resoio._generated.resonite_io.v1 import ConnectionStub, GetModVersionRequest

    try:
        client_version = metadata.version(_DISTRIBUTION_NAME)
    except metadata.PackageNotFoundError:
        # Editable checkout without installed metadata: cannot compare; skip.
        return

    try:
        stub = ConnectionStub(channel)
        mod_version = (await stub.get_mod_version(GetModVersionRequest())).version
    except GRPCError as exc:
        if exc.status is Status.UNIMPLEMENTED:
            _version_checked = True
            logger.warning(
                "ResoniteIO mod is too old to report its version (client=%s); "
                "please update it from %s. Latest mod: %s",
                client_version,
                _RELEASES_URL,
                _LATEST_ZIP_CMD,
            )
        return
    except Exception:
        # Connection-level / unexpected failure: leave the guard unset so the
        # probe retries on a later connect. Never break __aenter__.
        return

    _version_checked = True
    if mod_version != client_version:
        logger.warning(
            "ResoniteIO version mismatch: mod=%s, client=%s. Install a matching "
            "mod build from %s via Gale (Import > Local mod...), or `pip install` "
            "a matching resonite-io. Latest mod: %s",
            mod_version,
            client_version,
            _RELEASES_URL,
            _LATEST_ZIP_CMD,
        )


class SocketNotFoundError(RuntimeError):
    """No ``resonite-*.sock`` matched the configured search directory."""


class AmbiguousSocketError(RuntimeError):
    """Multiple candidate sockets found; set ``RESONITE_IO_SOCKET`` to pick
    one."""


def resolve_socket_path() -> str:
    """Resolve the UDS path for a Resonite IO gRPC client.

    Resolution order is unified across all modality clients so a
    zero-argument client just works under the same effective user as the
    running mod (including across the pressure-vessel sandbox):

    1. ``RESONITE_IO_SOCKET`` (explicit absolute path)
    2. ``RESONITE_IO_SOCKET_DIR`` (directory containing ``resonite-*.sock``)
    3. ``~/.resonite-io/`` (matches the C# Mod default)

    Empty env-var values fall through to the next step so a stray
    ``FOO=`` in shell config does not produce a bogus empty path.
    """
    explicit = os.environ.get("RESONITE_IO_SOCKET")
    if explicit:
        return explicit

    search_dir = os.environ.get("RESONITE_IO_SOCKET_DIR")
    if search_dir:
        return _pick_single_socket(search_dir)

    return _pick_single_socket(str(Path.home() / _DEFAULT_SOCKET_DIR_NAME))


def _pick_single_socket(directory: str) -> str:
    pattern = os.path.join(directory, _SOCKET_GLOB)
    candidates = sorted(glob.glob(pattern))
    if not candidates:
        raise SocketNotFoundError(
            f"No Resonite IO socket matched {pattern!r}. "
            "Is the mod running and bound to a UDS?"
        )
    if len(candidates) > 1:
        joined = ", ".join(candidates)
        raise AmbiguousSocketError(
            f"Multiple Resonite IO sockets matched {pattern!r}: {joined}. "
            "Set RESONITE_IO_SOCKET to disambiguate."
        )
    return candidates[0]


class _BaseClient[TStub: ServiceStub](ABC):
    """Async UDS gRPC channel lifecycle shared by every modality client.

    Subclasses set the class attributes :attr:`_logger` and
    :attr:`_log_label`, implement :meth:`_make_stub`, and add their RPC
    methods (guarding each with :meth:`_require_stub`). The public
    ``socket_path`` property and the ``async with`` channel lifecycle live
    here.
    """

    # Set per subclass: the module logger and the human-readable modality
    # label used in the "Opening <label> channel" debug log line.
    _logger: ClassVar[logging.Logger]
    _log_label: ClassVar[str]

    def __init__(self, socket_path: str | None = None) -> None:
        # Defer resolution to __aenter__ so env vars patched between
        # construction and connection are honoured, and so resolution
        # errors surface at the connect site.
        self._explicit_path: str | None = socket_path
        self._channel: Channel | None = None
        self._stub: TStub | None = None
        self._resolved_path: str | None = None

    @property
    def socket_path(self) -> str | None:
        """Resolved UDS path, or ``None`` before ``__aenter__``."""
        return self._resolved_path

    @abstractmethod
    def _make_stub(self, channel: Channel) -> TStub:
        """Build the concrete service stub on ``channel``."""

    def _require_stub(self) -> TStub:
        stub = self._stub
        if stub is None:
            name = type(self).__name__
            raise RuntimeError(
                f"{name} is not connected. Use `async with {name}(): ...`."
            )
        return stub

    async def __aenter__(self) -> Self:
        path = self._explicit_path or resolve_socket_path()
        self._logger.debug("Opening %s channel on UDS path: %s", self._log_label, path)
        channel = Channel(path=path)
        self._channel = channel
        self._stub = self._make_stub(channel)
        self._resolved_path = path
        await _maybe_warn_version_mismatch(channel, self._logger)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        channel = self._channel
        # Reset state before close() so a raising close still leaves the
        # client in a clean "not connected" state for retry / re-enter.
        self._channel = None
        self._stub = None
        self._resolved_path = None
        if channel is not None:
            channel.close()
