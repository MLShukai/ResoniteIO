"""Minimal Lifecycle.Shutdown example.

Asks the running engine to quit gracefully over the Resonite IO UDS, the same
path the in-app Quit button takes (FrooxEngine ``Engine.RequestShutdown``). The
engine ACKs immediately and exits asynchronously, so the call returns promptly
and does not wait for the process to die. Assumes a Resonite client with the
ResoniteIO mod loaded is running on the host.

For a one-call stop that also reports the engine's host PID, use
:func:`resoio.shutdown` (it reads the PID from ``Info`` then sends this RPC).

Run from inside the dev container:

    uv run python python/examples/lifecycle_shutdown.py
"""

import asyncio

from resoio import LifecycleClient

SOCKET_PATH: str | None = None


async def main() -> None:
    async with LifecycleClient(SOCKET_PATH) as client:
        response = await client.shutdown()
    print(f"accepted={response.accepted}")


if __name__ == "__main__":
    asyncio.run(main())
