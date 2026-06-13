# Modalities

Each capability is an independent, asynchronous modality with its own gRPC service, C#
service/bridge pair, and Python client. Modalities do not depend on each other — you can use
any subset.

## Matrix

| Modality | Direction | RPC style | Python client | What it does |
| --- | --- | --- | --- | --- |
| Connection | request/response | unary | [`ConnectionClient`](../api/connection.md) | Liveness check (`ping`). |
| Info | request/response | unary | [`get_server_info`](../api/info.md) | Mod/engine version, OS platform, Wine flag, engine/renderer host PIDs. |
| Camera | Resonite → Python | server-streaming | [`CameraClient`](../api/camera.md) | RGBA frames from the headset/view. |
| Speaker | Resonite → Python | server-streaming | [`SpeakerClient`](../api/speaker.md) | Audio rendered by Resonite (engine output tap). |
| Microphone | Python → Resonite | client-streaming | [`MicrophoneClient`](../api/microphone.md) | Push audio into Resonite as a virtual mic. |
| Locomotion | Python → Resonite | client-streaming | [`LocomotionClient`](../api/locomotion.md) | Drive movement commands; reset. |
| Grabber | request/response | unary | [`GrabberClient`](../api/grabber.md) | Grab at the desktop cursor ray hit point / release (desktop mode only). |
| Display | request/response | unary | [`DisplayClient`](../api/display.md) | Read display info. |
| World | request/response | unary | [`WorldClient`](../api/world.md) | List/open worlds, sessions, and records. |
| ContextMenu | request/response | unary | [`ContextMenuClient`](../api/context_menu.md) | Open/select the radial context menu. |
| Dash | request/response | unary | [`DashClient`](../api/dash.md) | Drive the ESC dash overlay (Userspace). |
| Inventory | request/response | unary | [`InventoryClient`](../api/inventory.md) | Browse and spawn inventory items. |
| Cursor | request/response | unary | [`CursorClient`](../api/cursor.md) | Set/hold/release/get the desktop cursor in normalized coords. |
| Lifecycle | Python → Resonite | unary | [`LifecycleClient`](../api/lifecycle.md) | Ask the engine to quit gracefully (`shutdown`); `resoio.terminate` wraps it with engine-PID reporting. |

Each modality also ships a minimal runnable script under
[`python/examples/`](https://github.com/MLShukai/ResoniteIO/tree/main/python/examples), and the
matching [API Reference](../api/connection.md) page links it.

## Direction conventions

Audio is split by direction on purpose: **Speaker** carries Resonite → Python audio (what
the agent "hears"), and **Microphone** carries Python → Resonite audio (what the agent
"says"). The same split logic gives Camera (out) and the input modalities (Locomotion,
Microphone) their streaming directions.

## Mirrored structure

The C# and Python sides mirror each other per modality. Adding a new one means a
`<Modality>Service` + `I<Modality>Bridge` in Core, a `FrooxEngine<Modality>Bridge` in the
mod, and a `<Modality>Client` in Python — see the
[C# Mod](csharp-mod.md) page and the project's `add-new-modality` workflow.
