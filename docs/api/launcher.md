# Launcher

Start and stop the Resonite client through **umu-launcher** — pure host process
control, no gRPC. `launch` spawns the umu-run chain and PID-diffs the engine and
renderer processes into existence; `terminate` stages `SIGTERM` → `SIGKILL` over
the two PIDs (or auto-detects the single running instance). The cooperative gRPC
quit is [`resoio.shutdown`](lifecycle.md). See the [CLI](../cli.md) `resoio launch`
/ `resoio terminate` commands.

::: resoio.launcher.launch

::: resoio.launcher.terminate

::: resoio.launcher.LaunchResult

::: resoio.launcher.LauncherError
