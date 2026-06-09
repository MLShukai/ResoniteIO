# Quick Start

This page assumes the C# mod is deployed and the Resonite client is running, and that you
have the `resoio` Python client installed (see [Installation](installation.md)).

Every client is an **async context manager** so the gRPC channel is opened and closed
deterministically. With `socket_path=None` the socket path is resolved on entry from
`RESONITE_IO_SOCKET` → `RESONITE_IO_SOCKET_DIR` → `~/.resonite-io/`.

## Ping the session

```python
import asyncio

from resoio import ConnectionClient


async def main() -> None:
    async with ConnectionClient() as session:
        response = await session.ping("hello")
        print(response.message)


asyncio.run(main())
```

`ConnectionClient` also exposes `get_mod_version()`, which returns the running C# mod's
version string — compare it against `resoio.__version__` to warn on a client/mod mismatch.

## Stream camera frames

`Camera` is a server-streaming modality (Resonite → Python). Each [`Frame`](../api/camera.md)
carries an `(H, W, 4)` RGBA8 array plus a capture timestamp.

```python
import asyncio

from resoio import CameraClient


async def main() -> None:
    async with CameraClient() as camera:
        async for frame in camera.stream(width=640, height=480, fps_limit=30):
            print(frame.frame_id, frame.width, frame.height, frame.pixels.shape)
            if frame.frame_id >= 100:
                break


asyncio.run(main())
```

## From the command line

The same capabilities are reachable from the `resoio` CLI without writing code:

```bash
resoio ping --message hello
resoio record --video out.mp4     # capture Camera (and/or Speaker) to a file
```

See the [CLI](../cli.md) page for the full command list, and the
[API Reference](../api/connection.md) for every client.

## Runnable examples

Every modality has a minimal, runnable script under
[`python/examples/`](https://github.com/MLShukai/ResoniteIO/tree/main/python/examples) (one
file per modality) — the fastest way to see a client's call shape end to end. Each
[API Reference](../api/connection.md) page links its matching example, and the
[examples README](https://github.com/MLShukai/ResoniteIO/blob/main/python/examples/README.md)
lists the per-modality preconditions.
