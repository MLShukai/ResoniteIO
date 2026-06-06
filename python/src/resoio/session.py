"""Client for the Resonite IO ``Session`` gRPC service over a UDS."""

from __future__ import annotations

import logging
from typing import override

from grpclib.client import Channel

from resoio._client import _BaseClient
from resoio._generated.resonite_io.v1 import PingRequest, PingResponse, SessionStub
from resoio._socket import (
    AmbiguousSocketError,
    SocketNotFoundError,
)

# Re-exported for backwards compatibility: the exception types historically
# lived in this module and are documented in ``SessionClient`` docstring.
__all__ = [
    "AmbiguousSocketError",
    "SessionClient",
    "SocketNotFoundError",
]

_logger = logging.getLogger("resoio.session")


class SessionClient(_BaseClient[SessionStub]):
    """Async client for the Resonite IO ``Session`` service over a UDS.

    Use as an async context manager so the gRPC channel is closed
    deterministically. With ``socket_path=None`` the path is resolved on
    ``__aenter__`` via ``RESONITE_IO_SOCKET`` →
    ``RESONITE_IO_SOCKET_DIR`` → ``~/.resonite-io/``; resolution may
    raise :class:`SocketNotFoundError` or :class:`AmbiguousSocketError`.
    """

    _logger = _logger
    _log_label = "Session"

    @override
    def _make_stub(self, channel: Channel) -> SessionStub:
        return SessionStub(channel)

    async def ping(self, message: str) -> PingResponse:
        stub = self._require_stub()
        return await stub.ping(PingRequest(message=message))
