"""Tests for the once-per-process mod/client version mismatch warning.

Per testing-strategy: a real ``grpclib.server.Server`` on a real UDS with a
self-owned ``ConnectionBase`` fake; no mocking of grpclib / asyncio /
betterproto internals. The probe runs inside ``_BaseClient.__aenter__``; its
process-global guard is re-armed per test here (the package-level autouse
fixture in ``conftest.py`` otherwise marks it done so unrelated tests stay
probe-free).
"""

import logging
import time
from collections.abc import Awaitable, Callable, Iterator
from importlib import metadata
from typing import TYPE_CHECKING

import pytest

from resoio import _client
from resoio._generated.resonite_io.v1 import (
    ConnectionBase,
    GetModVersionRequest,
    GetModVersionResponse,
    PingRequest,
    PingResponse,
)
from resoio.connection import ConnectionClient

if TYPE_CHECKING:
    from grpclib._typing import IServable

UdsServer = Callable[["IServable"], Awaitable[str]]

# The probe compares the mod version against this installed distribution version.
_INSTALLED_VERSION = metadata.version("resonite-io")
# A version guaranteed to differ from whatever is installed.
_MISMATCHED_VERSION = f"{_INSTALLED_VERSION}-mismatch-sentinel"


class _VersionConnection(ConnectionBase):
    """Connection fake that reports a configurable mod version."""

    def __init__(self, version: str) -> None:
        self._version = version

    async def ping(self, message: PingRequest) -> PingResponse:
        return PingResponse(message=message.message, server_unix_nanos=time.time_ns())

    async def get_mod_version(
        self, message: GetModVersionRequest
    ) -> GetModVersionResponse:
        return GetModVersionResponse(version=self._version)


class _OldConnection(ConnectionBase):
    """A pre-version-API mod: only ``ping`` is implemented, so ``get_mod_version``
    falls through to the generated base and raises ``UNIMPLEMENTED``."""

    async def ping(self, message: PingRequest) -> PingResponse:
        return PingResponse(message=message.message, server_unix_nanos=time.time_ns())


@pytest.fixture(autouse=True)
def _rearm_probe() -> Iterator[None]:
    """Re-arm the once-per-process probe so each test exercises first-
    connect."""
    _client._reset_version_check()
    yield


def _warnings_containing(
    caplog: pytest.LogCaptureFixture, needle: str
) -> list[logging.LogRecord]:
    return [
        record
        for record in caplog.records
        if record.levelno == logging.WARNING and needle in record.getMessage()
    ]


class TestModVersionProbe:
    async def test_get_mod_version_returns_server_version(self, uds_server: UdsServer):
        await uds_server(_VersionConnection("9.9.9-server"))
        async with ConnectionClient() as client:
            assert await client.get_mod_version() == "9.9.9-server"

    async def test_warns_once_on_mismatch(
        self, uds_server: UdsServer, caplog: pytest.LogCaptureFixture
    ):
        await uds_server(_VersionConnection(_MISMATCHED_VERSION))
        with caplog.at_level(logging.WARNING, logger="resoio.connection"):
            async with ConnectionClient():
                pass
            warnings = _warnings_containing(caplog, "version mismatch")
            assert len(warnings) == 1
            assert _MISMATCHED_VERSION in warnings[0].getMessage()
            assert _INSTALLED_VERSION in warnings[0].getMessage()

            # A second connect in the same process must not warn again.
            async with ConnectionClient():
                pass
            assert len(_warnings_containing(caplog, "version mismatch")) == 1

    async def test_no_warning_when_versions_match(
        self, uds_server: UdsServer, caplog: pytest.LogCaptureFixture
    ):
        await uds_server(_VersionConnection(_INSTALLED_VERSION))
        with caplog.at_level(logging.WARNING, logger="resoio.connection"):
            async with ConnectionClient():
                pass
        assert _warnings_containing(caplog, "version mismatch") == []

    async def test_warns_when_mod_too_old(
        self, uds_server: UdsServer, caplog: pytest.LogCaptureFixture
    ):
        await uds_server(_OldConnection())
        with caplog.at_level(logging.WARNING, logger="resoio.connection"):
            async with ConnectionClient():
                pass
        assert len(_warnings_containing(caplog, "too old")) == 1
