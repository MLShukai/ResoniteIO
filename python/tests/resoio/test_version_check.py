"""Tests for the once-per-process mod/client version mismatch warning.

Per testing-strategy: a real ``grpclib.server.Server`` on a real UDS with
self-owned generated-base fakes; no mocking of grpclib / asyncio /
betterproto internals. The probe runs inside ``_BaseClient.__aenter__`` and
now reaches the server via the Info service (``fetch_server_info`` /
``Info.GetServerInfo``); a mod that predates the Info modality answers
``UNIMPLEMENTED``, which the probe reports as a "mod too old" warning (the
pre-Info behaviour and wording are unchanged). The probe's process-global
guard is re-armed per test here (the package-level autouse fixture in
``conftest.py`` otherwise marks it done so unrelated tests stay probe-free).
"""

import logging
from collections.abc import Awaitable, Callable, Iterator
from importlib import metadata
from typing import TYPE_CHECKING

import pytest

from resoio import _client
from resoio._generated.resonite_io.v1 import (
    GetServerInfoRequest,
    InfoBase,
    ServerInfo as PbServerInfo,
    ServerPlatform as PbServerPlatform,
)
from resoio.connection import ConnectionClient

if TYPE_CHECKING:
    from grpclib._typing import IServable

UdsServer = Callable[["IServable"], Awaitable[str]]

# The probe compares the mod version against this installed distribution version.
_INSTALLED_VERSION = metadata.version("resonite-io")
# A version guaranteed to differ from whatever is installed.
_MISMATCHED_VERSION = f"{_INSTALLED_VERSION}-mismatch-sentinel"


class _VersionInfo(InfoBase):
    """Info fake reporting a configurable mod version (other fields dummy).

    The probe only consumes ``mod_version``; engine/platform/wine are filled
    with placeholders so the message stays wire-valid.
    """

    def __init__(self, version: str) -> None:
        self._version = version

    async def get_server_info(self, message: GetServerInfoRequest) -> PbServerInfo:
        return PbServerInfo(
            mod_version=self._version,
            engine_version="0.0.0-engine",
            platform=PbServerPlatform.OTHER,
            is_wine=False,
        )


class _PreInfoMod(InfoBase):
    """A pre-Info mod: the probe's ``Info.GetServerInfo`` call answers
    ``UNIMPLEMENTED`` via the un-overridden generated base.

    Hosted (rather than omitting Info from the grpclib server) because
    grpclib's unknown-service answer drops the content-type header and the
    grpclib client then reports ``UNKNOWN`` — a fake-server quirk the real
    C# Kestrel server does not share.
    """


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
    async def test_warns_once_on_mismatch(
        self, uds_server: UdsServer, caplog: pytest.LogCaptureFixture
    ):
        await uds_server(_VersionInfo(_MISMATCHED_VERSION))
        with caplog.at_level(logging.WARNING):
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
        await uds_server(_VersionInfo(_INSTALLED_VERSION))
        with caplog.at_level(logging.WARNING):
            async with ConnectionClient():
                pass
        assert _warnings_containing(caplog, "version mismatch") == []

    async def test_warns_when_mod_too_old(
        self, uds_server: UdsServer, caplog: pytest.LogCaptureFixture
    ):
        await uds_server(_PreInfoMod())
        with caplog.at_level(logging.WARNING):
            async with ConnectionClient():
                pass
        assert len(_warnings_containing(caplog, "too old")) == 1
