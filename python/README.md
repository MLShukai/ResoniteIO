# resonite-io

Python client for [ResoniteIO](https://github.com/MLShukai/ResoniteIO) — a bidirectional IPC
bridge that lets your Python code observe and control [Resonite](https://resonite.com/). The
`resonite-io` distribution imports as `resoio` and wraps the `resonite_io.v1` gRPC schema
(Unix Domain Socket transport, async via `grpclib`) into a friendly, fully typed client
library and a `resoio` CLI.

## Install

```bash
pip install resonite-io
```

## Requires

**Linux only.** The client connects over a Unix Domain Socket (POSIX) and targets a Resonite
client running on Linux through Steam Play (Proton). Windows is not supported, and there are
no plans to support it.

A Resonite client running the **ResoniteIO mod** on the same host (the two halves connect
over a Unix Domain Socket). See the documentation for installing the mod.

The optional `resoio launch` / `resoio terminate` commands start and stop Resonite as host
processes; they require [umu-launcher](https://github.com/Open-Wine-Components/umu-launcher)
(`umu-run`) on your `PATH`. Connecting to a Resonite you start yourself (e.g. via Steam) does
not need it.

## Quick start

```python
import asyncio

from resoio import ConnectionClient


async def main() -> None:
    async with ConnectionClient() as client:
        response = await client.ping("hello")
        print(response.message)


asyncio.run(main())
```

## Documentation

- **Docs:** <https://mlshukai.github.io/ResoniteIO/>
- **Source:** <https://github.com/MLShukai/ResoniteIO>

## License

[MIT](https://github.com/MLShukai/ResoniteIO/blob/main/LICENSE)
