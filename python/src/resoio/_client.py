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
]

_SOCKET_GLOB = "resonite-*.sock"
_DEFAULT_SOCKET_DIR_NAME = ".resonite-io"


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
