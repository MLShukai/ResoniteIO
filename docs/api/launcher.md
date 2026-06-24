# Launcher

Start and stop the Resonite client through **umu-launcher** — pure host process
control, no gRPC. `launch` spawns the umu-run chain and PID-diffs the engine and
renderer processes into existence; `terminate` stages `SIGTERM` → `SIGKILL` over
the two PIDs (or auto-detects the single running instance). The cooperative gRPC
quit is [`resoio.shutdown`](lifecycle.md). See the [CLI](../cli.md) `resoio launch`
/ `resoio terminate` commands.

Pass Resonite's own command-line launch options as a typed
[`LaunchOptions`](#resoio.launcher.LaunchOptions) via `launch(options=...)`
(`-DataPath`, `-CachePath`, `-Screen`, `-Verbose`, …) instead of hand-assembling
raw flag strings. Anything `LaunchOptions` does not model can still be passed
through `launch(extra_args=...)`.

::: resoio.launcher.launch

::: resoio.launcher.terminate

::: resoio.launcher.LaunchResult

::: resoio.launcher.LauncherError

::: resoio.launcher.LaunchOptions

::: resoio.launcher.Device

::: resoio.launcher.CloudProfile
