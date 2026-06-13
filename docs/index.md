# ResoniteIO

![ResoniteIO — Resonite ⇄ Python](assets/banner.png)

**ResoniteIO** is a bidirectional IPC bridge that turns [Resonite](https://resonite.com/)
into a runtime environment for AI agents. A C# mod running inside the Resonite client
(`ResoniteIO`, loaded via BepisLoader) and a Python package (`resoio`) talk to each other
over **gRPC on a Unix Domain Socket**.

!!! note "Linux only"
    ResoniteIO targets Resonite running on Linux through Steam Play (Proton). Windows is not
    supported. See [Installation](getting-started/installation.md) for details.

## Design philosophy

ResoniteIO is built like **real-time robotics middleware, not a reinforcement-learning
environment**. There is no `Observation` / `Action` abstraction and no global `step()`.
Instead, each capability is exposed as an independent, asynchronous **modality** stream,
each carrying its own timestamps. Any synchronization you need is done on the receiving
side.

- **Camera / Speaker** — Resonite → Python (server-streaming): vision and audio out.
- **Microphone / Locomotion** — Python → Resonite (client-streaming): voice in, movement.
- **Grabber / Display / World / ContextMenu / Dash / Inventory / Cursor** — request/response
  (unary): grabbing objects, reading the display, navigating worlds, driving the UI.

## Two-layer C# design

The C# side is split into two layers:

- **`ResoniteIO.Core`** — a pure library with zero dependency on Resonite. It holds the
  gRPC server, the per-modality services, and the domain logic.
- **`ResoniteIO`** — a thin BepInEx plugin that only does engine bridging (the
  `FrooxEngine<Modality>Bridge` adapters).

The dependency direction is strictly **Core ← Mod**. The Python client (`resoio`) is also
Resonite-independent.

## Where to go next

- [Installation](getting-started/installation.md) — how to install the mod and the Python client.
- [Quick Start](getting-started/quickstart.md) — your first `ping` and a camera stream.
- [Architecture › Overview](architecture/overview.md) — Core/Mod layering and transport.
- [Architecture › Modalities](architecture/modalities.md) — the full modality matrix.
- [API Reference](api/connection.md) — the `resoio` Python client API.
- [CLI](cli.md) — the `resoio` command-line tool.
- [Examples](https://github.com/MLShukai/ResoniteIO/tree/main/python/examples) — minimal runnable scripts, one per modality.

## License

[MIT](https://github.com/MLShukai/ResoniteIO/blob/main/LICENSE).
