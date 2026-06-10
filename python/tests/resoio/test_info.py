"""Integration-real tests for :mod:`resoio.info` (``get_server_info``).

Per testing-strategy: a real ``grpclib.server.Server`` on a real tmp_path UDS
hosting a self-owned ``InfoBase`` fake; no mocking of grpclib / asyncio /
betterproto internals. ``get_server_info`` is the BaseClient-independent
public entry point — it resolves the socket through the same env-driven order
every modality client uses (``RESONITE_IO_SOCKET`` etc.) or takes an explicit
``socket_path``, fires ``Info.GetServerInfo`` once, and decodes the wire
message into the frozen :class:`resoio.info.ServerInfo` dataclass.
"""

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

import pytest
from grpclib.const import Status
from grpclib.exceptions import GRPCError

from resoio._generated.resonite_io.v1 import (
    GetServerInfoRequest,
    InfoBase,
    ServerInfo as PbServerInfo,
    ServerPlatform as PbServerPlatform,
)
from resoio.info import ServerInfo, ServerPlatform, get_server_info

if TYPE_CHECKING:
    from grpclib._typing import IServable

UdsServer = Callable[["IServable"], Awaitable[str]]

_SAMPLE_PB_INFO = PbServerInfo(
    mod_version="9.9.9-mod",
    engine_version="2025.1.1.1",
    platform=PbServerPlatform.LINUX,
    is_wine=True,
)


class _FakeInfo(InfoBase):
    """Info fake returning a configurable generated ``ServerInfo``."""

    def __init__(self, info: PbServerInfo) -> None:
        self._info = info
        self.requests: list[GetServerInfoRequest] = []

    async def get_server_info(self, message: GetServerInfoRequest) -> PbServerInfo:
        self.requests.append(message)
        return self._info


class _UnimplementedInfo(InfoBase):
    """Models a mod predating the Info modality: ``GetServerInfo`` answers
    ``UNIMPLEMENTED`` via the un-overridden generated base.

    The service is hosted (rather than omitted from the grpclib server)
    because grpclib's unknown-service answer drops the content-type header
    and grpclib's *client* then reports ``UNKNOWN`` — a fake-server quirk
    the real C# Kestrel server does not share (it sends a proper
    trailers-only ``UNIMPLEMENTED``).
    """


class TestGetServerInfo:
    async def test_resolves_socket_from_env_and_returns_decoded_dataclass(
        self, uds_server: UdsServer
    ):
        """No-arg call resolves the UDS via the shared env order
        (``RESONITE_IO_SOCKET``) and decodes all four wire fields into the
        public ``ServerInfo`` dataclass, including the enum conversion."""
        fake = _FakeInfo(_SAMPLE_PB_INFO)
        await uds_server(fake)

        info = await get_server_info()

        assert isinstance(info, ServerInfo)
        assert info.mod_version == "9.9.9-mod"
        assert info.engine_version == "2025.1.1.1"
        assert info.platform is ServerPlatform.LINUX
        assert info.is_wine is True
        assert len(fake.requests) == 1

    async def test_explicit_socket_path_connects_without_env_resolution(
        self, uds_server: UdsServer, monkeypatch: pytest.MonkeyPatch
    ):
        """An explicit ``socket_path`` argument is honoured even when the env
        var route is unavailable (deleted after server start)."""
        socket_path = await uds_server(_FakeInfo(_SAMPLE_PB_INFO))
        monkeypatch.delenv("RESONITE_IO_SOCKET", raising=False)

        info = await get_server_info(socket_path=socket_path)

        assert info.mod_version == "9.9.9-mod"
        assert info.is_wine is True

    async def test_unimplemented_from_pre_info_server_passes_through(
        self, uds_server: UdsServer
    ):
        """A mod predating Info yields ``UNIMPLEMENTED``; ``get_server_info``
        must surface the ``GRPCError`` unchanged (the "mod too old"
        interpretation belongs to the version-check probe, not to this API)."""
        await uds_server(_UnimplementedInfo())

        with pytest.raises(GRPCError) as excinfo:
            await get_server_info()

        assert excinfo.value.status is Status.UNIMPLEMENTED

    @pytest.mark.parametrize(
        ("wire_platform", "expected_platform"),
        [
            (PbServerPlatform.UNSPECIFIED, ServerPlatform.UNSPECIFIED),
            (PbServerPlatform.WINDOWS, ServerPlatform.WINDOWS),
            (PbServerPlatform.OSX, ServerPlatform.OSX),
            (PbServerPlatform.LINUX, ServerPlatform.LINUX),
            (PbServerPlatform.ANDROID, ServerPlatform.ANDROID),
            (PbServerPlatform.OTHER, ServerPlatform.OTHER),
        ],
    )
    async def test_each_wire_platform_decodes_to_matching_public_enum(
        self,
        uds_server: UdsServer,
        wire_platform: PbServerPlatform,
        expected_platform: ServerPlatform,
    ):
        """Every wire ``ServerPlatform`` value maps onto the matching member of
        the public enum (full round-trip over the real wire)."""
        await uds_server(
            _FakeInfo(
                PbServerInfo(
                    mod_version="v",
                    engine_version="e",
                    platform=wire_platform,
                    is_wine=False,
                )
            )
        )

        info = await get_server_info()

        assert info.platform is expected_platform
