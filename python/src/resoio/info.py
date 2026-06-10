"""Read static server info from the Resonite IO ``Info`` modality.

Unary RPC reporting metadata about the running server: mod version,
engine version, OS platform, and whether the Resonite client runs under
Wine/Proton. All four values are fixed by the time the mod binds the
UDS, so the response is an immutable snapshot.

Unlike the other modalities this one is exposed as module-level
functions rather than a client class: the version-mismatch probe in the
shared client base needs to fetch the mod version *before* any client
is usable, so :func:`fetch_server_info` works on a bare channel and
:func:`get_server_info` wraps it with one-shot channel lifecycle.
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass

from grpclib.client import Channel

from resoio._client import resolve_socket_path
from resoio._generated.resonite_io.v1 import (
    GetServerInfoRequest,
    InfoStub,
    ServerInfo as _PbServerInfo,
    ServerPlatform as _PbServerPlatform,
)

__all__ = [
    "ServerInfo",
    "ServerPlatform",
    "fetch_server_info",
    "get_server_info",
]

_logger = logging.getLogger("resoio.info")


class ServerPlatform(enum.Enum):
    """OS platform the Resonite client runs on (mirrors FrooxEngine)."""

    UNSPECIFIED = "unspecified"
    WINDOWS = "windows"
    OSX = "osx"
    LINUX = "linux"
    ANDROID = "android"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class ServerInfo:
    """Immutable snapshot of the running mod and engine.

    Attributes:
        mod_version: Mod version derived from the csproj ``<Version>``.
        engine_version: Engine version string (``Engine.VersionString``).
        platform: OS platform the Resonite client runs on.
        is_wine: True when the client runs under Wine/Proton.
    """

    mod_version: str
    engine_version: str
    platform: ServerPlatform
    is_wine: bool


_PLATFORM_FROM_PROTO: dict[_PbServerPlatform, ServerPlatform] = {
    _PbServerPlatform.WINDOWS: ServerPlatform.WINDOWS,
    _PbServerPlatform.OSX: ServerPlatform.OSX,
    _PbServerPlatform.LINUX: ServerPlatform.LINUX,
    _PbServerPlatform.ANDROID: ServerPlatform.ANDROID,
    _PbServerPlatform.OTHER: ServerPlatform.OTHER,
}


def _info_from_proto(pb: _PbServerInfo) -> ServerInfo:
    return ServerInfo(
        mod_version=pb.mod_version,
        engine_version=pb.engine_version,
        platform=_PLATFORM_FROM_PROTO.get(pb.platform, ServerPlatform.UNSPECIFIED),
        is_wine=pb.is_wine,
    )


async def fetch_server_info(channel: Channel) -> ServerInfo:
    """Fetch the server info over an already-open gRPC channel.

    Shared channel-level helper: the version-mismatch probe in the
    client base calls this on the channel it is about to hand to a
    modality stub. Use :func:`get_server_info` for standalone calls.

    Args:
        channel: An open :class:`grpclib.client.Channel` to the UDS.

    Returns:
        The :class:`ServerInfo` snapshot reported by the mod.

    Raises:
        grpclib.exceptions.GRPCError: The RPC failed at the transport or
            server layer (``UNIMPLEMENTED`` means the mod predates the
            Info service).
    """
    response = await InfoStub(channel).get_server_info(GetServerInfoRequest())
    return _info_from_proto(response)


async def get_server_info(socket_path: str | None = None) -> ServerInfo:
    """Fetch the server info over a one-shot UDS connection.

    Info deliberately has no client class: the version-mismatch probe
    in the shared client base must read the mod version before any
    client is usable, so the modality is exposed as module functions
    (:func:`fetch_server_info` is the bare-channel form).

    Args:
        socket_path: Explicit UDS path. With ``None`` the path is
            resolved via ``RESONITE_IO_SOCKET`` →
            ``RESONITE_IO_SOCKET_DIR`` → ``~/.resonite-io/``; resolution
            may raise :class:`resoio.SocketNotFoundError` or
            :class:`resoio.AmbiguousSocketError`.

    Returns:
        The :class:`ServerInfo` snapshot reported by the mod.

    Raises:
        grpclib.exceptions.GRPCError: The RPC failed at the transport or
            server layer (``UNIMPLEMENTED`` means the mod predates the
            Info service).
    """
    path = socket_path or resolve_socket_path()
    _logger.debug("Opening Info channel on UDS path: %s", path)
    channel = Channel(path=path)
    try:
        return await fetch_server_info(channel)
    finally:
        channel.close()
