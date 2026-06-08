"""Client for the Resonite IO ``Connection`` gRPC service over a UDS."""

from __future__ import annotations

import logging
from typing import override

from grpclib.client import Channel

from resoio._client import _BaseClient
from resoio._generated.resonite_io.v1 import ConnectionStub, PingRequest, PingResponse

__all__ = [
    "ConnectionClient",
]

_logger = logging.getLogger(__name__)


class ConnectionClient(_BaseClient[ConnectionStub]):
    """Async client for the Resonite IO ``Connection`` service over a UDS.

    Use as an async context manager so the gRPC channel is closed
    deterministically. With ``socket_path=None`` the path is resolved on
    ``__aenter__`` via ``RESONITE_IO_SOCKET`` →
    ``RESONITE_IO_SOCKET_DIR`` → ``~/.resonite-io/``; resolution may
    raise :class:`SocketNotFoundError` or :class:`AmbiguousSocketError`.
    """

    _logger = _logger
    _log_label = "Connection"

    @override
    def _make_stub(self, channel: Channel) -> ConnectionStub:
        return ConnectionStub(channel)

    async def ping(self, message: str) -> PingResponse:
        stub = self._require_stub()
        return await stub.ping(PingRequest(message=message))
