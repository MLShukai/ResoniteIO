from __future__ import annotations

import asyncio
from pathlib import Path

from resoio.connection import ConnectionClient
from tests.helpers import mark_e2e


class TestConnectionPing:
    @mark_e2e
    def test_smoke(self, resonite_session: Path) -> None:
        async def call() -> None:
            async with ConnectionClient() as client:
                response = await client.ping("e2e-smoke")
            assert response.message == "e2e-smoke"
            assert response.server_unix_nanos > 0

        asyncio.run(call())
