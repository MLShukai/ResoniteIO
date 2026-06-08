# resonite-io

Python client for [ResoniteIO](https://github.com/MLShukai/ResoniteIO) — a bidirectional IPC
bridge that turns [Resonite](https://resonite.com/) into a runtime environment for AI agents.
The `resonite-io` distribution imports as `resoio` and wraps the `resonite_io.v1` gRPC schema
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
