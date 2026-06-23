# Changelog

This file holds the project's release notes. On `v*` tag publish,
`.github/workflows/publish.yml` extracts the `## [X.Y.Z]` section to use as the
GitHub Release body. The format follows
[Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### 🐛 Fixed

- **`resoio launch` could not find a properly installed mod**: `launch` looked for
  the plugin DLL only at the flat path `BepInEx/plugins/ResoniteIO/ResoniteIO.dll`,
  but a Thunderstore / Gale install nests it one level deeper —
  `BepInEx/plugins/ResoniteIO/ResoniteIO/ResoniteIO.dll`, with the package's
  project files (`manifest.json` / `icon.png` / …) sitting directly under
  `BepInEx/plugins/ResoniteIO/` (the same layout every other mod uses). `launch`
  now searches `BepInEx/plugins/` **recursively** for `ResoniteIO.dll` — the way
  BepInEx itself discovers plugins — so it works regardless of how the mod was
  installed (nested Thunderstore layout, namespaced package dir, or a flat copy).

### 🔧 Changed

- **`just deploy-mod` now deploys the real distribution artifact**: instead of
  copying loose DLLs into a flat `BepInEx/plugins/ResoniteIO/`, `deploy-mod` builds
  the Thunderstore package (`just mod-pack`) and unpacks it into the Gale profile
  exactly the way Gale's installer does — project files + `plugins/` →
  `BepInEx/plugins/ResoniteIO/` (DLLs nested under `…/ResoniteIO/ResoniteIO/`), and
  `Renderer/` → `Renderer/BepInEx/plugins/ResoniteIO/` (renderer DLLs under
  `…/ResoniteIO/ResoniteIO.Renderer/`). The local dev layout now
  matches what users get from Thunderstore. The build-time auto-deploy (the mod and
  renderer csproj `PostBuild` copies into the Gale profile) is removed; deployment
  goes through `just deploy-mod` only.

## [0.6.0] - 2026-06-22

### ✨ Added

- **`resoio launch` / `resoio terminate` (start/stop Resonite via umu-launcher)**:
  New commands and Python functions (`resoio.launch` / `resoio.terminate`) that
  start and force-stop the Resonite client without gRPC.

  - `launch` spawns the umu-launcher chain and PID-diffs the **engine**
    (`resonite_pid`) and **renderer** (`renderer_pid`) host processes into
    existence, returning both as a `LaunchResult`.
  - `terminate` stages `SIGTERM` → `SIGKILL` over those two PIDs (or auto-detects
    the single running instance when given none, erroring if more than one is
    found).
  - `RESONITE_EXE` (default: the Steam install) and `MOD_PATH` (the Gale profile
    with the mod deployed) select the install; the ResoniteIO mod must be
    installed (via Gale / Thunderstore) or `launch` errors with guidance.
  - The cooperative gRPC quit stays available as `resoio shutdown`.
  - Exposed as `resoio.launch` / `resoio.terminate` / `LaunchResult` /
    `LauncherError` and the `resoio launch` (`-e/--exe` / `-p/--profile` /
    `--vanilla` / `--format human|json`) and `resoio terminate`
    (`[resonite_pid] [renderer_pid]`) CLI commands.

- **Run Resonite inside the dev container**: the dev container can now launch
  Resonite itself via the new `resoio launch` / `resoio terminate` commands (and
  the thin `just resonite-launch` / `just resonite-stop` wrappers).

  - The container entrypoint rsyncs the read-only `/resonite` bind into a writable
    `/opt/resonite`, and `resoio launch` starts Resonite through `umu-run` /
    Proton **with the ResoniteIO mod loaded** from the `./gale` Gale profile (the
    first run pulls GE-Proton and copies the ~2 GB install). `resoio launch --vanilla` runs **vanilla** Resonite with no mod.
  - Engine side loads via hookfxr, renderer side via a doorstop `winhttp.dll` —
    `resoio launch` sets `WINEDLLOVERRIDES="winhttp=n,b"` automatically, so **no
    manual Steam-style `WINEDLLOVERRIDES` setup is needed** on this path.
  - The whole mod loop runs inside the container: the mod (GrpcHost) creates its
    gRPC socket under the container's `~/.resonite-io/` (it makes the directory
    itself before binding) and the Python client connects there — no host
    bind-share.
  - The mod's BepInEx log stays at `gale/BepInEx/LogOutput.log` (`just log`);
    umu/Proton launch noise is split into `gale/BepInEx/umu-launch.log`.
  - Rendering needs a host graphical session (X11 / Xwayland) and
    PipeWire/PulseAudio for audio. **NVIDIA / AMD / Intel** GPUs are all supported
    — `initialize.sh` detects the vendor and selects the matching per-vendor
    compose overlay (`.devcontainer/compose.{nvidia,amd,intel}.yml` via the
    `compose.gpu.yml` symlink).
  - **Requires `kernel.apparmor_restrict_unprivileged_userns=0`** on the host
    (pressure-vessel needs unprivileged user namespaces, which Ubuntu 24.04+
    restricts by default); the container start hard-fails without it.
  - The dev image base also moved from `debian:bookworm-slim` to `debian:13-slim`
    (trixie), and `compose.yml` moved from the repo root to
    `.devcontainer/compose.yml`.

- **`Contact` modality**: A new unary modality that drives the dash "Contacts"
  tab by reading/writing the cloud contact list (`Engine.Cloud.Contacts` /
  `Engine.Cloud.Users`) directly — no UI automation.

  - `ListContacts` returns the synced contacts with presence (online status +
    current session name / access level) plus the contact / request counts and a
    list-loaded flag, with client-side `search` (username / alternate-username
    substring) and `filter` (accepted friends / incoming requests). Like the dash
    tab it hides `ShouldBeHidden` contacts (ignored / blocked / none) by default —
    pass `include_hidden` to include them, and every contact carries an
    `is_hidden` flag.
  - `GetContact` fetches one by user id (absent → `found=false`). `SearchUsers`
    queries the cloud for users to add (exact or substring, read-only).
  - `AddContact` (resolving the username mod-side when omitted), `AcceptRequest`,
    and `RemoveContact` mutate the list; remove declines a request / deletes a
    friend, which the engine marks `Ignored` so the entry drops out of the default
    (hidden) list.
  - Unknown ids return `NotFound`, cloud failures `Internal`, and an unavailable
    cloud `FailedPrecondition`.
  - Exposed as `ContactClient` and the nested `resoio contact` CLI (`list` (with
    `--include-hidden`) / `get` / `search` / `add` / `accept` / `remove`, each
    with `--format human|json`).

- **`Auth` modality**: A new unary modality for Resonite cloud authentication —
  sign in / out and read the auth status — driving `Engine.Cloud.Session`
  directly (`Login` / `Logout` / `Status`, all returning a unified `AuthStatus`
  of `logged_in` / `user_id` / `user_name` / `session_expires_unix_nanos`).

  - `login` takes a credential (username / email / `U-` id) and a password (plus
    an optional `totp` for 2FA) and `remember_me` (default true), which delegates
    session persistence to the engine — **resoio stores no credentials on disk**.
  - Wrong credentials return `Unauthenticated`; a 2FA-enabled account with
    no/blank code returns `FailedPrecondition`, and the CLI then prompts for the
    code and retries once.
  - **Security**: the plaintext password is never persisted, logged, placed in an
    exception / gRPC status detail, or `--format json` output, and there is **no
    `--password` CLI flag** — the password comes only from `RESONITE_IO_PASSWORD`,
    piped stdin, or a hidden prompt.
  - All three leaves support `--format human|json`; the human `status` output
    renders the session expiry as a UTC datetime, and the `--format json` document
    adds a derived ISO-8601 `session_expires_iso` next to the exact
    `session_expires_unix_nanos`. When the credential is omitted, the interactive
    prompt reads `Username or Email` — a username, email, or user id is accepted.
  - Exposed as `AuthClient` and the nested `resoio auth login` / `logout` /
    `status` CLI.

- **`Session` modality**: A new unary userspace modality that drives the dash
  "Session" dialog — the connected session's Settings, Users, and Permissions
  tabs — by reading/writing `World.Configuration` / `World.AllUsers` /
  `World.Permissions` directly (no UI automation).

  - **Settings** use a get + partial-apply model (`GetSettings` /
    `ApplySettings`): world name/description, max users, access level,
    hide-from-listing, mobile-friendly, away-kick, auto-save, auto-cleanup, and
    tags. Partial updates use `proto3 optional` presence, so `false` / `0` can be
    set explicitly and unset fields are left untouched (`tags` use a
    `replace_tags` gate); `ApplySettings` returns nothing — call `GetSettings` to
    read the new state.
  - **Users** expose `ListUsers` plus host-gated `KickUser` / `BanUser` /
    `SilenceUser` / `RespawnUser` / `SetUserRole`; targets resolve by `user_id`
    (preferred), `user_name`, or `local` (self), and `respawn` defaults to self.
  - **Permissions** expose `ListRoles` (with the default
    anonymous/visitor/contact/host/owner roles) and `GetUserRoleOverrides`.
  - Host-gated operations return `PermissionDenied` when the local user lacks the
    right, and out-of-range `max_users` returns `InvalidArgument`.
  - Exposed as `SessionClient` and the nested `resoio session` CLI (`settings get`/`set`, `users list`, `user kick`/`ban`/`silence`/`respawn`/`role`, `roles list`, `overrides list`).

- **`resoio shutdown` / `resoio.shutdown`**: The graceful-stop command and
  convenience function are now named `shutdown`, matching Resonite's terminology
  and the `Lifecycle.Shutdown` RPC. Behaviour is unchanged — it reads the engine
  PID from `Info` (for reporting) and sends `Lifecycle.Shutdown`; the engine quits
  itself and Steam/Proton reaps the renderer + launch wrappers. Prints / returns
  the engine's host PID, or "resonite not running" / `None` when no engine is
  reachable.

- **`resoio --format human|json`**: Commands that return structured data (`ping`,
  `info`, `display`, `cursor`, `grabber`, `context-menu`, `dash`, `world`, `mic`,
  `session`) gained a `--format` flag. `human` (default) keeps the existing text
  output unchanged; `json` prints one machine-readable document to stdout (proto
  field names in snake_case, enums as their name, big ints exact, non-ASCII
  preserved). `--format` is not added to pid/path-only commands (`shutdown` /
  `terminate`, `screenshot` / `record` / `world thumbnail`), interactive commands
  (`drive` / `grabber interactive` / `inventory`), or the side-effect-only
  `session user kick` / `ban` / `respawn` leaves.

- **`resoio wait` / `resoio.wait_for_ready`**: A new startup-readiness gate that
  blocks until the Resonite IO server answers `Connection.Ping`.

  - The public async `wait_for_ready(socket_path=None, *, timeout=None, interval=0.1)` polls until a ping round-trips and returns the resolved socket
    path, retrying while the socket is absent, has no listener yet, or the engine
    is still warming up (`FAILED_PRECONDITION`); `AmbiguousSocketError` and other
    gRPC errors propagate, and `timeout` (`None` = wait forever) raises
    `TimeoutError`.
  - The `resoio wait` CLI wraps it: it prints the resolved socket path on success,
    takes an optional `pid` to target `resonite-{pid}.sock`, and `-T/--timeout`
    (default 30s, `<=0` tries once) bounds the wait. `--format` is not added
    (path-only output).

- **Grabber post-grab interactions (`Use` / `Unuse` / `Equip` / `Dequip`)**: The
  Grabber service gained four unary RPCs (all returning `GrabberGrabState`) for
  operating what a hand holds.

  - `Use` presses a virtual button (`primary` = left-click / `secondary` =
    right-click) and **holds it down** until `Unuse`, driven by a per-tick
    `ExternalInput` re-injection repeater (Locomotion-style) so the press survives
    across RPCs. `primary` injects **both** the digital `Interact` action **and**
    the analog press-strength action, which is what makes strength-driven tools
    such as Pens / Geometry Line Brushes (the `BrushTool` family, which fire on
    analog `primaryStrength`, not on the digital press) draw — hold `Use`, sweep
    the cursor with `cursor set` to move the tip, then `Unuse`.
  - `Equip` finds an `ITool` on a grabbed object and equips it into the hand;
    `Dequip` removes the equipped tool (both no-ops when nothing applies).
  - `Use` takes an optional `strength` (analog primary press pressure, `0..1`,
    default `1.0`, server-clamped, ignored for `secondary` and missing → `1.0`)
    usable as e.g. brush pressure. `GrabberGrabState` gained `is_tool_equipped` /
    `equipped_tool_name` / `held_buttons`.
  - Exposed as `GrabberClient.use` / `unuse` / `click` (a press+release
    convenience) / `equip` / `dequip` (`use` / `click` take `strength: float = 1.0`) and the `resoio grabber` actions `use` / `unuse` / `click` / `equip` /
    `dequip` with `--button {primary,secondary}` and `--strength` (default `1.0`).

### 🔧 Changed

- **`resoio grab` is renamed to `resoio grabber`, and the action is now
  required**: 💥 Breaking: the top-level Grabber command is `resoio grabber` and
  the action must be named explicitly — `resoio grabber grab` / `release` /
  `state` / `interactive`. Bare `resoio grabber` now errors with the argparse
  usage code; the old implicit-`grab` default (where `resoio grab` ran a grab with
  no action) is **removed**. The old `resoio grab` command name is also removed
  (no alias), so argparse rejects it. This aligns the command with the `Grabber`
  modality name (like `cursor` / `display` / `world`). The Python API
  (`GrabberClient`) and the gRPC wire are unchanged.
- **`resoio terminate` / `resoio.terminate` now force-stops the processes**: 💥
  Breaking: it was a deprecated alias of `resoio shutdown` (a graceful
  `Lifecycle.Shutdown` over gRPC); it now **kills** the engine + renderer host
  processes (`SIGTERM` → `SIGKILL`) and takes `[resonite_pid] [renderer_pid]` (or
  auto-detects the single running instance). Use `resoio shutdown` /
  `resoio.shutdown` for the cooperative gRPC quit. The old gRPC
  `resoio.terminate(socket_path=...)` signature is removed.
- **`resoio shutdown` / `resoio.shutdown` documented as best-effort**: the
  graceful `Lifecycle.Shutdown` ACK only confirms the quit was *requested*, not
  that the engine exited. On Linux (including the dev container) FrooxEngine
  frequently hangs during teardown and the engine never exits on its own
  (issue #49), so the docs and example now spell out the cooperative pattern —
  `shutdown` to ask nicely, then `terminate` for a guaranteed stop. Behaviour is
  unchanged; the live e2e now drives that real flow (graceful request, then forced
  terminate) instead of asserting a graceful exit that does not happen
  in-container.
- **`resoio record` default output is now a file**: 💥 Breaking: with no `-o`,
  `record` saves `record_<timestamp>.mp4` (`.wav` for `--audio`) to the current
  directory instead of streaming to stdout. Pass `-o -` for the previous stdout
  behaviour, or `-o PATH` for an explicit file.
- **`screenshot` / `record` / `world thumbnail` print the saved path**: on a file
  save these now print the saved absolute path to stdout (`screenshot` was
  previously silent; `world thumbnail` previously logged to stderr), so a caller
  can capture stdout to locate the artifact. `-o -` still streams raw bytes with
  no path line. `world thumbnail` also gained the dated-default / `-o -` target
  rules to match `screenshot` / `record`.
- **`resoio mic` summary moves to stdout**: the end-of-stream summary
  (`received_frames` / `received_samples` / `dropped_frames` / `unix_nanos`) is
  the command result and now prints to stdout in both formats (was stderr); errors
  and status messages stay on stderr.
- **Socket resolution skips dead sockets**: directory-based socket resolution
  (`resolve_socket_path`, used by every modality client) now reads the engine PID
  from each `resonite-{pid}.sock` candidate and skips ones whose process is gone
  (`psutil.pid_exists`), so a stale socket left behind by a SIGKILL'd engine no
  longer causes a spurious `AmbiguousSocketError` or a connect to a dead UDS; only
  live sockets count toward the found / ambiguous decision. Names that do not
  encode an integer PID are kept. Adds a `psutil` runtime dependency.

### 🗑️ Removed

- **Container ↔ host Resonite bridge removed (migrated to in-container mod
  launch)**: now that the dev container launches the mod-loaded Resonite itself
  (`just resonite-start`), the host-side daemon (`scripts/host_agent.py`), its
  container client (`scripts/resonite_cli.py`), the `just host-agent` recipe, and
  the debug socket `~/.resonite-io-debug/host-agent.sock` are all removed.

  - The production gRPC UDS is **no longer bind-shared with the host** — the mod
    creates it inside the container under `~/.resonite-io/`.
  - The host **desktop** screenshot bridge (the `just resonite-screenshot` recipe
    / host-agent / `pyscreenshot`) is removed; screenshots now go through the
    existing in-engine `resoio screenshot` (`CameraClient.shot()`, Camera v2
    framebuffer — e.g. `resoio screenshot -o foo.png`).
  - `just resonite-up` is renamed to `just resonite-vanilla`. The `GaleProfile` /
    `GaleBin` env vars are dropped (the Gale profile is read from `./gale`).

## [0.5.0] - 2026-06-13

Adds the `Lifecycle` modality (graceful shutdown), a one-shot camera
screenshot, inventory thumbnail fetching, and engine/renderer host PIDs in
`Info`. Also **breaking**: the Dash modality is redesigned from a flat tree to
a tab/control model (gRPC route / C# surface / Python client + CLI all change),
so update the ResoniteIO mod and the `resoio` Python package in lockstep.

### ✨ Added

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

### 🔧 Changed

- **The Dash modality is redesigned to a tab/control model**: 💥 Breaking: the
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

### 🔧 Changed

- **The Manipulation modality is renamed to Grabber**: 💥 Breaking: the gRPC
  route changed from `/resonite_io.v1.Manipulation/*` to
  `/resonite_io.v1.Grabber/*` (`manipulation.proto` → `grabber.proto`,
  `Manipulation*` messages → `Grabber*`), the C# surface is now
  `GrabberService` / `IGrabberBridge` / `FrooxEngineGrabberBridge`, and the
  Python module and client are `resoio.grabber` / `GrabberClient` (the
  `GrabResult` / `GrabState` dataclasses keep their names). An old mod and a
  new client (or vice versa) cannot talk over the renamed route — update the
  ResoniteIO mod and the `resoio` Python package in lockstep
- **Cursor `SetPosition` now holds the cursor until `Release`**: 💥 Breaking:
  `SetPosition` was a one-shot warp (the engine cursor reverted to the OS
  pointer on the next frame, especially under Wine/Proton). It now registers a
  persistent engine-side cursor lock so the in-engine cursor stays at the set
  position across RPCs, while a Harmony patch on
  `InputInterface.CollectOutputState` masks the lock from the renderer so the
  **real OS mouse pointer is never captured** (no warp, no confine, no
  center-pin). `InputInterface.SetMousePosition` (OS warp) is no longer called.
  While held, real mouse movement does not move the in-engine cursor (clicks
  still fire at the held position); switching world focus deactivates the hold
- **`Manipulation.Grab` is now ray-based**: 💥 Breaking:
  `ManipulationGrabRequest.point` (`WorldPoint`) was removed (field 2 is
  reserved). Grab always targets the point where the desktop cursor ray hits
  the world and grabs grabbables within `radius` of that point. A ray miss
  returns `grabbed=false` (not an error); VR mode (screen output inactive)
  returns `FAILED_PRECONDITION`. The Python client's `ManipulationClient.grab`
  lost its `point` parameter and the CLI lost `--point`. Aim with
  `resoio cursor set X Y` (held until release), then `resoio grab`
- **`resoio display` is split into `get` / `set` subcommands**: 💥 Breaking: the
  implicit branching ("no flags = get, any flag = set") is gone.
  `resoio display get` prints the current snapshot; `resoio display set`
  requires at least one of `-W/--width`, `-H/--height`, `-F/--max-fps` and
  prints the post-apply snapshot
- **`resoio locomotion drive` is flattened to `resoio drive`**: 💥 Breaking: the
  `locomotion` command group is removed; the flags
  (`--sprint` / `--look-rate` / `--no-wait`) are unchanged
- **`resoio manipulate` is renamed to `resoio grab`** (following the modality
  rename): 💥 Breaking: the action positional
  (`grab` / `release` / `state` / `interactive`) is optional and defaults to
  `grab`, and `--hand` / `--radius` are accepted before or after the action
- **CLI required arguments are now enforced by argparse**:
  `resoio cursor set <x> <y>`, `resoio dash invoke <ref_id>`, and
  `resoio context-menu highlight/invoke <index>` reject missing positionals as
  a usage error at parse time instead of failing mid-command. The argv shape
  of valid invocations is unchanged

### ✨ Added

- **`Cursor.Release` RPC**: releases the held cursor and returns control to the
  OS pointer. Idempotent (releasing while not held succeeds and returns the
  current state). Exposed as `CursorClient.release()` and
  `resoio cursor release`
- **`CursorState.held` field**: reports whether the cursor is currently held,
  returned by `SetPosition` / `GetPosition` / `Release` and shown in the CLI
  output (`held=True/False`)

### 🐛 Fixed

- **Grabbed objects no longer fly behind the user's head**: in desktop mode
  the hand moves from its rest pose to a holding pose right after a grab, and
  a far-away grab left a large holder-local offset that got swung around with
  the hand. The bridge now pins the grabbed object at its grab-time pose (the
  cursor position) until the hand settles, so it stays where it was grabbed
  and follows the hand from there

## [0.3.0] - 2026-06-09

Adds a mod/client version-compatibility check and switches distribution to
GitHub Release only (Thunderstore upload paused).

### ✨ Added

- **`Connection.GetModVersion`**: Added a unary RPC that returns the running
  mod version. The Python client probes it once per process on first connect
  (`_BaseClient.__aenter__`) and warns when the mod is older than or mismatched
  with the client, pointing to the GitHub Release for an aligned build. The
  probe never fails the connection (errors are swallowed). Exposed on the Python
  side as `ConnectionClient.get_mod_version()`. The `ModInfo` is injected into
  the Core `ConnectionService` (Core ← Mod direction preserved; the Mod supplies
  `PluginMetadata.VERSION` via `GrpcHost.Start(modVersion)`)

### 🔧 Changed

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

### ✨ Added

- **Python `resoio`**: Added the received-chunk type `SpeakerChunk` and the
  generated proto response types `ListSessionsResponse` / `ListRecordsResponse` /
  `FetchThumbnailResponse` for the `World` modality to the top-level exports

### 🔧 Changed

- **Python `resoio` Locomotion**: 💥 Breaking: Reworked movement input from the
  single-shot command `LocomotionCmd` (all fields required) into the partial
  update `LocomotionClient.send(field=None)` that sends only changed fields.
  Fields left as `None` are not put on the wire, and the Resonite-side bridge
  retains the previous value. The drive summary is obtained from the
  `drive_summary` property after the `async with` block exits. Under the hood,
  the 8 control fields of the proto `LocomotionCommand` were made `optional`
  (field presence), and `LocomotionPartialInput` + `MergeInto` were added to the
  C# Core to merge only present fields into the held state
- **Python `resoio` Speaker**: 💥 Breaking: Renamed the received-chunk type
  `AudioChunk` to `SpeakerChunk`. Removed the constants `CHANNELS` / `DTYPE` /
  `SAMPLE_RATE` from the top-level exports (kept at the `resoio.speaker`
  module level since they collide with microphone names)
- **Python `resoio` Microphone**: 💥 Breaking: Removed the wrapper type
  `MicrophoneAudioChunk`; `stream()` / `paced()` now take a raw NumPy ndarray
  directly (frame_id / unix_nanos are managed automatically by the library)
- **Python `resoio` Camera**: 💥 Breaking: Changed `Frame.width` / `height` /
  `channels` into read-only properties derived from `pixels`. Removed the
  `width` / `height` / `fps_limit` arguments from `stream()` (resolution config
  is the responsibility of the Display modality)
- **Python `resoio` World**: 💥 Breaking: Removed the output mirror dataclasses
  `RecordPage` / `SessionPage` / `Thumbnail` and now expose the generated proto
  response types directly. The input-side enum remaps (`RecordSort`, etc.) are
  retained
- **Python `resoio`**: 💥 Breaking: Moved the socket exceptions
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

### 🗑️ Removed

- **Python `resoio`**: Removed `LocomotionCmd` / `AudioChunk` /
  `MicrophoneAudioChunk` / `CHANNELS` / `DTYPE` / `SAMPLE_RATE` / `RecordPage` /
  `SessionPage` / `Thumbnail` from the top-level exports (following the API
  rework under Changed above)

### 🐛 Fixed

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

### 🐛 Fixed

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

### ✨ Added

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
[0.6.0]: https://github.com/MLShukai/ResoniteIO/compare/v0.5.0...v0.6.0
[unreleased]: https://github.com/MLShukai/ResoniteIO/compare/v0.6.0...HEAD
