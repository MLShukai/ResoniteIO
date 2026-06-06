"""Shared gRPC channel lifecycle for the per-modality client classes.

Every ``<Modality>Client`` opens a single :class:`grpclib.client.Channel`
on ``__aenter__`` (resolving the UDS path lazily so env vars patched
between construction and connection are honoured), builds a stub on it,
and closes the channel on ``__aexit__``. :class:`_BaseClient` factors that
boilerplate out; subclasses supply only their stub type and their RPC
methods.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from types import TracebackType
from typing import ClassVar, Generic, Self, TypeVar

# betterproto2 generates one ``ServiceStub`` subclass per service; bounding
# the type var on that base makes each subclass pin a concrete stub type.
from betterproto2.grpclib.grpclib_client import ServiceStub
from grpclib.client import Channel

from resoio._socket import resolve_socket_path

__all__ = [
    "_BaseClient",
]

TStub = TypeVar("TStub", bound=ServiceStub)


class _BaseClient(ABC, Generic[TStub]):
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
