"""Minimal Info.GetServerInfo example.

Fetches the static server info snapshot (mod version, engine version,
OS platform, Wine flag) over the Resonite IO UDS and prints it. The
snapshot is fixed at engine startup, so no readiness retry is needed:
the Info service answers as soon as the UDS is bound. Assumes a
Resonite client with the ResoniteIO mod loaded is running on the host.

Run from inside the dev container:

    uv run python python/examples/server_info.py
"""

import asyncio

from resoio import get_server_info

SOCKET_PATH: str | None = None


async def main() -> None:
    info = await get_server_info(SOCKET_PATH)
    print(f"mod_version={info.mod_version}")
    print(f"engine_version={info.engine_version}")
    print(f"platform={info.platform.value}")
    print(f"is_wine={'true' if info.is_wine else 'false'}")


if __name__ == "__main__":
    asyncio.run(main())
