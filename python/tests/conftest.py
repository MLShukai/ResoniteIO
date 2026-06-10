"""Shared pytest fixtures for the resoio test suite.

Per CLAUDE.md / testing-strategy the project consolidates shared
fixtures here as the surface grows.
"""

from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from grpclib.server import Server

from resoio import _client

if TYPE_CHECKING:
    # grpclib's own type for "an object Server([...]) accepts": a generated
    # <Modality>Base servicer. Guarded so the private module is never
    # imported at runtime (testing-strategy: don't depend on 3rd-party
    # internals at runtime).
    from grpclib._typing import IServable


@pytest.fixture(autouse=True)
def _mod_version_probe_done() -> Iterator[None]:
    """Mark the once-per-process mod-version probe as already done per test.

    The probe fires an ``Info.GetServerInfo`` RPC on the first client
    ``__aenter__`` per process (see
    ``resoio._client._maybe_warn_version_mismatch``). Left
    unmanaged it would run against whichever fake server connects first and
    couple tests through module state. Defaulting it to "done" keeps unrelated
    connects probe-free; the version-check tests reset it explicitly to
    exercise the behaviour.
    """
    _client._version_checked = True
    yield


@pytest.fixture
async def uds_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[Callable[["IServable"], Awaitable[str]]]:
    """Start a real grpclib ``Server`` on a tmp_path UDS for one fake servicer.

    This is the canonical "grpclib end-to-end round-trip" harness from
    testing-strategy: a real ``grpclib.server.Server`` listens on a real
    Unix Domain Socket with an in-process self-owned fake servicer, and
    ``RESONITE_IO_SOCKET`` is pointed at it so a ``<Modality>Client``
    connects over the real wire (no grpclib / asyncio / betterproto
    internals are mocked).

    Yields a ``start(servicer)`` coroutine factory so the test can build
    its fake first (often configured per-test) and then bring the server
    up. The factory returns the socket path string. The server is closed
    and the socket unlinked automatically on teardown.
    """
    started: list[Server] = []

    async def _start(servicer: "IServable") -> str:
        socket_path = tmp_path / "rio.sock"
        server = Server([servicer])
        await server.start(path=str(socket_path))
        started.append(server)
        monkeypatch.setenv("RESONITE_IO_SOCKET", str(socket_path))
        return str(socket_path)

    try:
        yield _start
    finally:
        for server in started:
            server.close()
            await server.wait_closed()
