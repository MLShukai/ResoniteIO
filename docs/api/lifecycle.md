# Lifecycle

!!! example "Runnable example"
    [`python/examples/lifecycle_shutdown.py`](https://github.com/MLShukai/ResoniteIO/blob/main/python/examples/lifecycle_shutdown.py) — asks the engine to quit gracefully via `Lifecycle.Shutdown`.

!!! warning "Graceful shutdown is best-effort"
    `Lifecycle.Shutdown` only *asks* the engine to quit — the ACK confirms the request, not that the process died. On Linux (including the dev container) FrooxEngine frequently hangs during teardown and the engine never exits on its own. When you need a guaranteed stop, follow up with [`resoio.terminate`](launcher.md) (a forceful kill by host PID): `shutdown` to ask nicely, `terminate` to make sure.

::: resoio.lifecycle.LifecycleClient

::: resoio.lifecycle.shutdown
