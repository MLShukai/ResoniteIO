# Changelog

This file holds the project's release notes. On `v*` tag publish,
`.github/workflows/publish.yml` extracts the `## [X.Y.Z]` section to use as the
GitHub Release body. The format follows
[Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- **`Auth` modality**: A new unary modality for Resonite cloud authentication —
  sign in / out and read the auth status — driving `Engine.Cloud.Session`
  directly (`Login` / `Logout` / `Status`, all returning a unified `AuthStatus`
  of `logged_in` / `user_id` / `user_name` / `session_expires_unix_nanos`).
  `login` takes a credential (username / email / `U-` id) and a password (plus an
  optional `totp` for 2FA) and `remember_me` (default true), which delegates
  session persistence to the engine — **resoio stores no credentials on disk**.
  Wrong credentials return `Unauthenticated`; a 2FA-enabled account with no/blank
  code returns `FailedPrecondition`, and the CLI then prompts for the code and
  retries once. Exposed as `AuthClient` and the nested `resoio auth login` /
  `logout` / `status` CLI. **Security**: the plaintext password is never
  persisted, logged, placed in an exception / gRPC status detail, or
  `--format json` output, and there is **no `--password` CLI flag** — the
  password comes only from `RESONITE_IO_PASSWORD`, piped stdin, or a hidden
  prompt. All three leaves support `--format human|json`
- **`Session` modality**: A new unary userspace modality that drives the dash
  "Session" dialog — the connected session's Settings, Users, and Permissions
  tabs — by reading/writing `World.Configuration` / `World.AllUsers` /
  `World.Permissions` directly (no UI automation). Settings use a get +
  partial-apply model (`GetSettings` / `ApplySettings`): world name/description,
  max users, access level, hide-from-listing, mobile-friendly, away-kick,
  auto-save, auto-cleanup, and tags. Partial updates use `proto3 optional`
  presence, so `false` / `0` can be set explicitly and unset fields are left
  untouched (`tags` use a `replace_tags` gate); `ApplySettings` returns nothing —
  call `GetSettings` to read the new state. Users expose `ListUsers` plus
  host-gated `KickUser` / `BanUser` / `SilenceUser` / `RespawnUser` /
  `SetUserRole`; targets resolve by `user_id` (preferred), `user_name`, or
  `local` (self), and `respawn` defaults to self. Permissions expose `ListRoles`
  (with the default anonymous/visitor/contact/host/owner roles) and
  `GetUserRoleOverrides`. Host-gated operations return `PermissionDenied` when
  the local user lacks the right, and out-of-range `max_users` returns
  `InvalidArgument`. Exposed as `SessionClient` and the nested `resoio session`
  CLI (`settings get`/`set`, `users list`,
  `user kick`/`ban`/`silence`/`respawn`/`role`, `roles list`, `overrides list`)
- **ResoniteLink enable in `Session` settings**: `SessionSettings` now reports
  `resonite_link_enabled` / `resonite_link_port` (read from `World.ResoniteLink`,
  port normalized to `0` when off), and `ApplySettings` can turn ResoniteLink on
  via `World.StartResoniteLink()` (host + ResoniteLink-permission gated,
  idempotent) using `apply_settings(resonite_link_enabled=True)` or
  `resoio session settings set --resonite-link`. **Enable-only**: the engine
  exposes no runtime stop API (the dash itself offers only an Enable button), so
  requesting disable returns `FailedPrecondition`
- **`resoio shutdown` / `resoio.shutdown`**: The graceful-stop command and
  convenience function are now named `shutdown`, matching Resonite's terminology
  and the `Lifecycle.Shutdown` RPC. Behaviour is unchanged — it reads the engine
  PID from `Info` (for reporting) and sends `Lifecycle.Shutdown`; the engine
  quits itself and Steam/Proton reaps the renderer + launch wrappers. Prints /
  returns the engine's host PID, or "resonite not running" / `None` when no
  engine is reachable
- **`resoio --format human|json`**: Commands that return structured data
  (`ping`, `info`, `display`, `cursor`, `grab`, `context-menu`, `dash`, `world`,
  `mic`, `session`) gained a `--format` flag. `human` (default) keeps the
  existing text output unchanged; `json` prints one machine-readable document to
  stdout (proto field names in snake_case, enums as their name, big ints exact,
  non-ASCII preserved). `--format` is not added to pid/path-only commands
  (`shutdown` / `terminate`, `screenshot` / `record` / `world thumbnail`),
  interactive commands (`drive` / `grab interactive` / `inventory`), or the
  side-effect-only `session user kick` / `ban` / `respawn` leaves

### Changed

- **`resoio record` default output is now a file (breaking)**: with no `-o`,
  `record` saves `record_<timestamp>.mp4` (`.wav` for `--audio`) to the current
  directory instead of streaming to stdout. Pass `-o -` for the previous stdout
  behaviour, or `-o PATH` for an explicit file
- **`screenshot` / `record` / `world thumbnail` print the saved path**: on a
  file save these now print the saved absolute path to stdout (`screenshot` was
  previously silent; `world thumbnail` previously logged to stderr), so a caller
  can capture stdout to locate the artifact. `-o -` still streams raw bytes with
  no path line. `world thumbnail` also gained the dated-default / `-o -` target
  rules to match `screenshot` / `record`
- **`resoio mic` summary moves to stdout**: the end-of-stream summary
  (`received_frames` / `received_samples` / `dropped_frames` / `unix_nanos`) is
  the command result and now prints to stdout in both formats (was stderr);
  errors and status messages stay on stderr

### Deprecated

- **`resoio terminate` / `resoio.terminate`**: Renamed to `shutdown` (above).
  The `terminate` command and function still work but are **no longer
  maintained** and will be **removed in a future release**. The CLI prints a
  deprecation notice on stderr and `resoio.terminate` emits a
  `DeprecationWarning`; both forward to `shutdown`. Migrate to `resoio shutdown`
  / `resoio.shutdown`

## [0.5.0] - 2026-06-13

Adds the `Lifecycle` modality (graceful shutdown), a one-shot camera
screenshot, inventory thumbnail fetching, and engine/renderer host PIDs in
`Info`. Also **breaking**: the Dash modality is redesigned from a flat tree to
a tab/control model (gRPC route / C# surface / Python client + CLI all change),
so update the ResoniteIO mod and the `resoio` Python package in lockstep.

### Added

- **`Lifecycle.Shutdown` RPC**: A new `Lifecycle` modality with a unary
  `Shutdown` RPC that asks the engine to quit gracefully
  (`Engine.RequestShutdown`, the in-app Quit path). The mod schedules the
  shutdown on the engine tick and ACKs before the process tears down, so the
  RPC returns promptly and the engine exits asynchronously. Exposed as
  `LifecycleClient.shutdown()`
- **`ServerInfo.resonite_pid` / `renderer_pid`**: `Info.GetServerInfo` now also
  reports the engine (`Resonite.exe`) and renderer (`Renderite.Renderer.exe`)
  host PIDs. The engine runs natively on Linux (`is_wine=false`), so
  `resonite_pid` (`Environment.ProcessId`) and `renderer_pid`
  (`RenderSystem.RendererProcess`, `0` when headless) are real host kernel PIDs.
  Surfaced on `ServerInfo` and in the `resoio info` output (new `resonite_pid=` /
  `renderer_pid=` lines)
- **`resoio terminate` / `resoio.terminate`**: Stops the running Resonite client
  gracefully — it reads the engine PID from `Info` (for reporting) and sends
  `Lifecycle.Shutdown`; the engine quits itself and Steam/Proton reaps the
  renderer + launch wrappers. A pure gRPC call (no OS signals), so it works from
  anywhere the UDS is reachable. Prints / returns the engine's host PID, or
  "resonite not running" / `None` when no engine is reachable
- **`CameraClient.shot()` and `resoio screenshot`**: A convenience method that
  captures a single Camera frame and closes the stream (instead of opening a
  stream and breaking on the first frame), plus a CLI command that saves it as
  an opaque PNG. `resoio screenshot` takes `-o` / `--output` (a `.png` path or
  `-` for stdout) and otherwise writes a timestamped
  `screenshot_<timestamp>.png` to the current directory. The PNG drops the alpha
  channel, because the engine framebuffer's non-opaque alpha would otherwise
  render washed-out in image viewers. Exposed as `CameraClient.shot()`
- **`Inventory.FetchThumbnail` RPC**: A unary RPC that returns the thumbnail
  image of an inventory item, resolving the item's `Record.ThumbnailURI`
  server-side and returning the raw image bytes plus their content type (e.g.
  `"image/webp"`, returned verbatim from the Resonite CDN, not re-encoded).
  Exposed as `InventoryClient.fetch_thumbnail()` (returning the new
  `InventoryThumbnail` dataclass) and the `thumb` command in the interactive
  `resoio inventory` REPL

### Changed

- **Breaking — the Dash modality is redesigned to a tab/control model**: the
  flat-tree contract (`GetTree` / `ListScreens` / `SetScreen` with the
  `DashTree` / `DashElement` / `DashRect` / `DashScreen` / `DashScreenList`
  messages) is replaced by a tab-first model. The bottom tab bar is enumerated
  with `ListTabs` → `DashTabList`, the current tab's controls (Button /
  ScrollRect) with `ListControls` → `DashControlList`, and a new `SetTab` RPC
  switches tabs (`Open` / `Close` / `GetState` / `Invoke` / `Scroll` /
  `Highlight` are retained). On the Python side the `DashTree` / `DashElement` /
  `DashScreen` dataclasses are replaced by `DashTab` / `DashControl`, and the
  `resoio dash` CLI is restructured into `open` / `close` / `state` / `tabs` /
  `tab` / `ls` / `invoke` / `scroll` / `highlight` (tab navigation first, then
  control interaction within the current tab). The gRPC route is wire-broken by
  the message/RPC changes — update the ResoniteIO mod and the `resoio` Python
  package in lockstep

## [0.4.0] - 2026-06-11

A **breaking** release that renames the Manipulation modality to Grabber
(gRPC route / C# surface / Python module all change), makes Cursor
`SetPosition` a persistent hold until `Release`, switches `Grab` to a
ray-based targeting model, and redesigns the CLI
(`manipulate` → `grab`, `locomotion drive` → `drive`,
`display` split into `get` / `set`). Update the ResoniteIO mod and the
`resoio` Python package in lockstep.

### Changed

- **Breaking — the Manipulation modality is renamed to Grabber**: the gRPC
  route changed from `/resonite_io.v1.Manipulation/*` to
  `/resonite_io.v1.Grabber/*` (`manipulation.proto` → `grabber.proto`,
  `Manipulation*` messages → `Grabber*`), the C# surface is now
  `GrabberService` / `IGrabberBridge` / `FrooxEngineGrabberBridge`, and the
  Python module and client are `resoio.grabber` / `GrabberClient` (the
  `GrabResult` / `GrabState` dataclasses keep their names). An old mod and a
  new client (or vice versa) cannot talk over the renamed route — update the
  ResoniteIO mod and the `resoio` Python package in lockstep
- **Breaking — Cursor `SetPosition` now holds the cursor until `Release`**:
  `SetPosition` was a one-shot warp (the engine cursor reverted to the OS
  pointer on the next frame, especially under Wine/Proton). It now registers a
  persistent engine-side cursor lock so the in-engine cursor stays at the set
  position across RPCs, while a Harmony patch on
  `InputInterface.CollectOutputState` masks the lock from the renderer so the
  **real OS mouse pointer is never captured** (no warp, no confine, no
  center-pin). `InputInterface.SetMousePosition` (OS warp) is no longer called.
  While held, real mouse movement does not move the in-engine cursor (clicks
  still fire at the held position); switching world focus deactivates the hold
- **Breaking — `Manipulation.Grab` is now ray-based**:
  `ManipulationGrabRequest.point` (`WorldPoint`) was removed (field 2 is
  reserved). Grab always targets the point where the desktop cursor ray hits
  the world and grabs grabbables within `radius` of that point. A ray miss
  returns `grabbed=false` (not an error); VR mode (screen output inactive)
  returns `FAILED_PRECONDITION`. The Python client's `ManipulationClient.grab`
  lost its `point` parameter and the CLI lost `--point`. Aim with
  `resoio cursor set X Y` (held until release), then `resoio grab`
- **Breaking — `resoio display` is split into `get` / `set` subcommands**: the
  implicit branching ("no flags = get, any flag = set") is gone.
  `resoio display get` prints the current snapshot; `resoio display set`
  requires at least one of `-W/--width`, `-H/--height`, `-F/--max-fps` and
  prints the post-apply snapshot
- **Breaking — `resoio locomotion drive` is flattened to `resoio drive`**: the
  `locomotion` command group is removed; the flags
  (`--sprint` / `--look-rate` / `--no-wait`) are unchanged
- **Breaking — `resoio manipulate` is renamed to `resoio grab`** (following
  the modality rename): the action positional
  (`grab` / `release` / `state` / `interactive`) is optional and defaults to
  `grab`, and `--hand` / `--radius` are accepted before or after the action
- **CLI required arguments are now enforced by argparse**:
  `resoio cursor set <x> <y>`, `resoio dash invoke <ref_id>`, and
  `resoio context-menu highlight/invoke <index>` reject missing positionals as
  a usage error at parse time instead of failing mid-command. The argv shape
  of valid invocations is unchanged

### Added

- **`Cursor.Release` RPC**: releases the held cursor and returns control to the
  OS pointer. Idempotent (releasing while not held succeeds and returns the
  current state). Exposed as `CursorClient.release()` and
  `resoio cursor release`
- **`CursorState.held` field**: reports whether the cursor is currently held,
  returned by `SetPosition` / `GetPosition` / `Release` and shown in the CLI
  output (`held=True/False`)

### Fixed

- **Grabbed objects no longer fly behind the user's head**: in desktop mode
  the hand moves from its rest pose to a holding pose right after a grab, and
  a far-away grab left a large holder-local offset that got swung around with
  the hand. The bridge now pins the grabbed object at its grab-time pose (the
  cursor position) until the hand settles, so it stays where it was grabbed
  and follows the hand from there

## [0.3.0] - 2026-06-09

Adds a mod/client version-compatibility check and switches distribution to
GitHub Release only (Thunderstore upload paused).

### Added

- **`Connection.GetModVersion`**: Added a unary RPC that returns the running
  mod version. The Python client probes it once per process on first connect
  (`_BaseClient.__aenter__`) and warns when the mod is older than or mismatched
  with the client, pointing to the GitHub Release for an aligned build. The
  probe never fails the connection (errors are swallowed). Exposed on the Python
  side as `ConnectionClient.get_mod_version()`. The `ModInfo` is injected into
  the Core `ConnectionService` (Core ← Mod direction preserved; the Mod supplies
  `PluginMetadata.VERSION` via `GrpcHost.Start(modVersion)`)

### Changed

- **Distribution**: Switched to distributing via GitHub Release only.
  Thunderstore upload is paused (package unapproved + layout mismatch); the mod
  is installed through Gale's `Import > Local mod...`. The zip build pipeline
  (`tcli` / `PackTS` / `thunderstore.toml`) is retained for future store
  re-enablement, and the `github-release` job additionally attaches a fixed-name
  `ResoniteIO.zip` for a stable `releases/latest/download/ResoniteIO.zip` URL.
  README / installation docs now describe the GitHub Release zip → Gale local
  import flow (supporting plugins must be installed beforehand, since local
  import does not auto-resolve dependencies)

## [0.2.0] - 2026-06-08

A **breaking** release that refines the public API of the Python client `resoio`,
cleaning up leaks from implementation details. It also reworks the locomotion
input model into a partial-update scheme and fixes a bug where view rotation
(yaw/pitch) was not applied on the live client. Migrating from 0.1.x requires
following the API changes listed under Removed / Changed below.

### Added

- **Python `resoio`**: Added the received-chunk type `SpeakerChunk` and the
  generated proto response types `ListSessionsResponse` / `ListRecordsResponse` /
  `FetchThumbnailResponse` for the `World` modality to the top-level exports

### Changed

- **Python `resoio` Locomotion (breaking)**: Reworked movement input from the
  single-shot command `LocomotionCmd` (all fields required) into the partial
  update `LocomotionClient.send(field=None)` that sends only changed fields.
  Fields left as `None` are not put on the wire, and the Resonite-side bridge
  retains the previous value. The drive summary is obtained from the
  `drive_summary` property after the `async with` block exits. Under the hood,
  the 8 control fields of the proto `LocomotionCommand` were made `optional`
  (field presence), and `LocomotionPartialInput` + `MergeInto` were added to the
  C# Core to merge only present fields into the held state
- **Python `resoio` Speaker (breaking)**: Renamed the received-chunk type
  `AudioChunk` to `SpeakerChunk`. Removed the constants `CHANNELS` / `DTYPE` /
  `SAMPLE_RATE` from the top-level exports (kept at the `resoio.speaker`
  module level since they collide with microphone names)
- **Python `resoio` Microphone (breaking)**: Removed the wrapper type
  `MicrophoneAudioChunk`; `stream()` / `paced()` now take a raw NumPy ndarray
  directly (frame_id / unix_nanos are managed automatically by the library)
- **Python `resoio` Camera (breaking)**: Changed `Frame.width` / `height` /
  `channels` into read-only properties derived from `pixels`. Removed the
  `width` / `height` / `fps_limit` arguments from `stream()` (resolution config
  is the responsibility of the Display modality)
- **Python `resoio` World (breaking)**: Removed the output mirror dataclasses
  `RecordPage` / `SessionPage` / `Thumbnail` and now expose the generated proto
  response types directly. The input-side enum remaps (`RecordSort`, etc.) are
  retained
- **Python `resoio` (breaking)**: Moved the socket exceptions
  `AmbiguousSocketError` / `SocketNotFoundError` from `resoio.connection` to the
  internal `resoio._client` and re-exported them from the top level. The
  `resoio.connection` module is now purified to `Ping` only (the top-level
  import names are unchanged, but `from resoio.connection import AmbiguousSocketError` etc. is breaking)
- **Thunderstore mod**: Bundled `CHANGELOG.md` and `LICENSE` in the distributed
  package
- **Thunderstore mod**: Expanded publish categories (added `tools` / `audio` /
  `controls` in addition to `mods`)
- **Documentation**: Documented Linux-only support (no Windows support) in the
  README and docs site

### Removed

- **Python `resoio`**: Removed `LocomotionCmd` / `AudioChunk` /
  `MicrophoneAudioChunk` / `CHANNELS` / `DTYPE` / `SAMPLE_RATE` / `RecordPage` /
  `SessionPage` / `Thumbnail` from the top-level exports (following the API
  rework under Changed above)

### Fixed

- **Thunderstore mod**: Fixed an issue where the distributed package bundled the
  entire ASP.NET Core shared framework, bloating to 131 files / 24MB (including
  unused DLLs for Blazor / MVC / Razor / Identity / SignalR, etc.) and getting
  rejected by Thunderstore moderation as "files from another mod mixed in"
  (Invalid submission). Switched to an allow-list approach (`_BundledAspNetCoreDll`)
  that narrows the bundled DLLs to just the real dependency closure of GrpcHost
  (Kestrel + gRPC), reducing it to 67 files / 4.9MB (no change to functionality
  or wire compatibility)
- **Thunderstore mod**: Fixed the distributed package not including the Camera v2
  Renderer-side plugin (`ResoniteIO.Renderer`). Because `UnityEngine.CoreModule`
  is non-redistributable and the renderer cannot be built in CI, the
  locally-built artifact is committed as a prebuilt (`mod/prebuilt/renderer/`,
  guarded by a source-hash drift check in `just run` and CI) and pack/CI bundle
  it verbatim into `Renderer/ResoniteIO.Renderer/`, which the Gale BepisLoader
  installer routes to `Renderer/BepInEx/plugins/`
- **mod Locomotion**: Fixed an issue where view rotation (yaw/pitch) did not reach
  the engine while cursor lock was absent, so the avatar would not turn. Because
  `ScreenCameraInputs.Look.Active` is gated on `InputInterface.IsCursorLocked`,
  a low-priority cursor lock is acquired internally only while look input is
  active to satisfy the precondition (released when input is 0 / on Dispose,
  etc.; an existing cursor lock is not overwritten)
- **Python `resoio` Locomotion**: Fixed `LocomotionClient.__aexit__` leaking the
  connection by skipping channel close when the drive task raised; it now always
  closes via try/finally

## [0.1.1] - 2026-06-07

A hotfix for packaging defects found after the 0.1.0 release. Fixes 2 issues
that made the distributed artifacts non-functional.

### Fixed

- **Thunderstore mod**: Fixed an issue where the distributed package contained
  only `ResoniteIO.dll` / `.pdb` and was missing the Core/Mod two-layer
  `ResoniteIO.Core.dll` and the Kestrel/gRPC runtime DLLs, so the mod could not
  load. Now stages and bundles the same `@(PluginFiles)` set as the Gale deploy,
  packaging all required DLLs without omission
  (`StageThunderstorePlugin` target + `thunderstore.toml`)
- **Python `resonite-io`**: Fixed an issue where `import resoio` after
  `pip install resonite-io` raised `ImportError` due to a betterproto2 version
  mismatch. Pinned the runtime dependency to match the generated code's compiler
  major.minor at `betterproto2[grpclib]>=0.10,<0.11` (regenerated `_generated/`
  with compiler 0.10.1; dev kept in lockstep)

## [0.1.0] - 2026-06-07

The first public release. A complete foundation for the bidirectional IPC
bridge that uses Resonite as an execution environment for AI agents (C# mod
`ResoniteIO` ↔ Python package `resoio`, gRPC over Unix Domain Socket).

### Added

- **IPC foundation**: A bidirectional bridge over gRPC over Unix Domain Socket.
  Production IPC uses the UDS at `$HOME/.resonite-io/`, and the debug bridge uses
  `$HOME/.resonite-io-debug/`
- **C# Core/Mod two-layer architecture**: Separated into the Resonite-independent
  pure library `ResoniteIO.Core` (gRPC server / Service / per-modality domain
  logic) and the thin BepInEx adapter `ResoniteIO` (BepisLoader) that only
  handles engine bridging. The dependency direction is Core ← Mod
- **Modalities** (each an independent async stream): `Connection` (Ping) /
  `Camera` (server-streaming RGB frames) / `Speaker` (server-streaming audio,
  Resonite → Python) / `Microphone` (client-streaming audio, Python → Resonite) /
  `Locomotion` (client-streaming) / `Manipulation` (Grab/Release unary) /
  `Display` / `World` / `ContextMenu` / `Dash` / `Inventory` /
  `Cursor` (set/get the desktop cursor in normalized coordinates)
- **Python package `resoio`**: Per-modality async clients
  (`ConnectionClient` / `CameraClient` / `SpeakerClient` / `MicrophoneClient` /
  `LocomotionClient` / `ManipulationClient` / `DisplayClient` / `WorldClient` /
  `ContextMenuClient` / `DashClient` / `InventoryClient` / `CursorClient`).
  Based on betterproto2 + grpclib, conforming to pyright strict
- **CLI `resoio`**: Action-named flat commands (`ping` / `record` / `mic` /
  `locomotion` / `manipulate` / `display` / `world` / `context-menu` / `dash` /
  `inventory` / `cursor`). `record` captures Camera/Speaker to mp4/mkv with the
  `--video` / `--audio` filters, and `mic` streams Microphone to Resonite
- **proto definitions**: `proto/resonite_io/v1/` is the single source of truth;
  the Python-side generated code is committed, and the C# side is generated at
  build time by the csproj
- **Development environment**: A `debian:bookworm-slim`-based devcontainer
  (`compose.yml` / `.devcontainer/`), a `justfile` task runner, and container ↔
  host Resonite bridge scripts (`scripts/host_agent.py` / `scripts/resonite_cli.py`)
- **CI / release / documentation**: GitHub Actions quality gates
  (`pre-commit` / `test` / `type-check` / `dotnet` / `proto-check`), a `v*`
  tag-driven `publish.yml` that publishes the Thunderstore mod + PyPI package
  simultaneously, and a versioned documentation site via mike (MkDocs Material)

[0.1.0]: https://github.com/MLShukai/ResoniteIO/releases/tag/v0.1.0
[0.1.1]: https://github.com/MLShukai/ResoniteIO/compare/v0.1.0...v0.1.1
[0.2.0]: https://github.com/MLShukai/ResoniteIO/compare/v0.1.1...v0.2.0
[0.3.0]: https://github.com/MLShukai/ResoniteIO/compare/v0.2.0...v0.3.0
[0.4.0]: https://github.com/MLShukai/ResoniteIO/compare/v0.3.0...v0.4.0
[0.5.0]: https://github.com/MLShukai/ResoniteIO/compare/v0.4.0...v0.5.0
[unreleased]: https://github.com/MLShukai/ResoniteIO/compare/v0.5.0...HEAD
