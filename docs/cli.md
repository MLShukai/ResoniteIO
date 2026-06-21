# CLI

Installing the `resonite-io` package provides a `resoio` command (entry point `resoio.cli:main`). Commands are
**flat, named by action** — there are no subcommand groups (e.g. `resoio mic`, not
`resoio voice mic`). Each command maps to a modality client.

```bash
resoio --help
```

## Commands

| Command | Modality | Direction | Notes |
| --- | --- | --- | --- |
| `resoio ping` | Connection | unary | Liveness check. |
| `resoio wait` | Connection | unary | Block until `Connection.Ping` succeeds (startup readiness), then print the resolved socket path. Sockets whose owning engine PID is gone are skipped. Optional `pid` targets `resonite-{pid}.sock`; `-T/--timeout` (default 30s, `<=0` tries once) bounds the wait. |
| `resoio info` | Info | unary | Print mod/engine version, OS platform, Wine flag, and engine/renderer host PIDs. |
| `resoio record` | Camera / Speaker | Resonite → Python | Capture video and/or audio. `--video` / `--audio` filter (neither = muxed). `-o -` streams to stdout; `-o PATH` (`.mp4` / `.wav`) writes that file; omitted writes `record_<timestamp>.mp4` (`.wav` for `--audio`) to the current directory. On file save the saved absolute path is printed to stdout. |
| `resoio screenshot` | Camera | Resonite → Python | Save a single frame as an opaque PNG. `-o PATH` (`.png`) or `-o -` for stdout; omitted writes `screenshot_<timestamp>.png` to the current directory. On file save the saved absolute path is printed to stdout. |
| `resoio mic` | Microphone | Python → Resonite | Stream audio into Resonite as a virtual mic. |
| `resoio drive` | Locomotion | Python → Resonite | Interactive WASD driving (`--sprint` / `--look-rate` / `--no-wait`). |
| `resoio grab` | Grabber | unary | Grab at the desktop cursor ray hit point / release (desktop mode only). The action positional (`grab` / `release` / `state` / `interactive`) defaults to `grab`; `--hand` / `--radius` work before or after it. |
| `resoio display` | Display | unary | `get` prints the current snapshot; `set` applies a partial config (`-W/--width`, `-H/--height`, `-F/--max-fps` — at least one required) and prints the post-apply snapshot. |
| `resoio world` | World | unary | List / open worlds and sessions. |
| `resoio context-menu` | ContextMenu | unary | Open / select the radial menu. |
| `resoio dash` | Dash | unary | Drive the ESC dash overlay. |
| `resoio inventory` | Inventory | unary | Interactive REPL: browse (`ls`/`cd`), mutate (`mkdir`/`cp`/`mv`/`rm`), `spawn`, and `thumb` (save an item's thumbnail image). |
| `resoio session` | Session | unary | Configure the connected session via nested subcommands: `settings get`/`set` (partial apply; `set --resonite-link` enables ResoniteLink — enable-only, the engine has no runtime disable), `users list`, `user kick`/`ban`/`silence`/`respawn`/`role` (target with `--id`/`--name`/`--self`; `respawn` defaults to self), `roles list`, `overrides list`. |
| `resoio contact` | Contact | unary | Browse and manage contacts (friends) via nested subcommands: `list` (`--search` / `--filter all\|accepted\|requests` / `--include-hidden`), `get`, `search` (`--exact`), `add` (`--username`), `accept`, `remove`. `list` hides dash-hidden (ignored / blocked) contacts by default; `--include-hidden` shows them. The mutating ops (`add` / `accept` / `remove`) write the real cloud contact list. |
| `resoio auth` | Auth | unary | Resonite cloud sign-in via nested subcommands: `login` (credential positional; password via env/stdin/prompt, never a flag), `logout`, `status`. |
| `resoio cursor` | Cursor | unary | Set / center / get / release the desktop cursor. `set` and `center` hold the position until `release`. |
| `resoio launch` | — (umu-launcher) | local process | Start Resonite (engine + renderer) via umu-launcher and print both host PIDs. `-e/--exe` / `RESONITE_EXE` and `-p/--profile` / `MOD_PATH` select the install + mod profile; `--vanilla` skips the mod. Non-gRPC. |
| `resoio terminate` | — (signals) | local process | Force-stop Resonite by killing the engine + renderer (`SIGTERM` → `SIGKILL`). Takes `[resonite_pid] [renderer_pid]` (from `launch`) or auto-detects the single running instance. Non-gRPC. |
| `resoio shutdown` | Lifecycle | unary | Ask the engine to quit gracefully (`Lifecycle.Shutdown`). Best-effort — on Linux the engine often hangs during teardown and never exits, so follow up with `terminate` when you need a guaranteed stop. Prints the engine's host PID (from `Info`). |

`record` is the Resonite → Python capture command (it pulls Camera and Speaker), while `mic`
is its independent Python → Resonite counterpart.

`launch` / `terminate` are **local process control** (no gRPC). `launch` spawns the
umu-launcher chain and waits until the **engine** (`resonite_pid`) and **renderer**
(`renderer_pid`) host processes appear, printing both; it refuses to start a second instance.
`terminate` signals those two PIDs (`SIGTERM` → `SIGKILL`); given no PIDs it auto-detects the
single running instance (and errors if it finds more than one). Because they work from the host
process table they run before the UDS exists and regardless of whether the client is reachable.
`shutdown`, by contrast, is a pure gRPC call (`Lifecycle.Shutdown`) that asks a **running**
engine to quit gracefully — use it when the client is up and reachable. It is best-effort,
though: on Linux (including the dev container) FrooxEngine frequently hangs during teardown and
the engine never exits on its own, so reach for `terminate` when you need a **guaranteed** stop
(or already hold the PIDs from `launch`). The cooperative pattern is `shutdown` to ask the
engine nicely, then `terminate` to make sure the process is gone.

## `auth`

`resoio auth` signs the engine in and out of the Resonite cloud account (Python → Resonite),
mirroring how a `gh auth login`-style flow works. It has three nested leaves:

- `resoio auth login [credential]` — authenticate. `credential` is an optional positional
  (username or email). The **password is never a flag** and never appears on `argv`; it is read
  from, in order:
    1. the `RESONITE_IO_PASSWORD` environment variable,
    2. piped **stdin** (e.g. `printf '%s' "$pw" | resoio auth login alice`),
    3. an interactive **hidden prompt** (no echo) when neither of the above is provided.
- `resoio auth logout` — sign the engine out.
- `resoio auth status` — report whether the engine is logged in, and for whom. The human
  output renders the session expiry as a UTC datetime; `--format json` carries both the exact
  `session_expires_unix_nanos` and a derived ISO-8601 `session_expires_iso` (`null` when there
  is no expiry).

`login` flags:

- `--totp CODE` — two-factor one-time code, when the account has 2FA enabled.
- `--no-remember` — do not persist the session. By default the login asks the engine to
  remember the session (`remember_me=True`); persistence is delegated entirely to the engine.

All three leaves accept `--format human|json` (see below).

**Security stance.** The password is never passed on the command line or written to logs — only
the env var, piped stdin, or the hidden prompt can supply it. `--no-remember` controls only
whether the **engine** persists the session; `resoio` itself stores no credentials and keeps no
session state. When `remember_me` is set, persistence is the engine's responsibility, not the
CLI's.

```bash
# Sign in (hidden password prompt; nothing sensitive on argv)
resoio auth login alice@example.com

# Non-interactive: feed the password via env or piped stdin
RESONITE_IO_PASSWORD="$pw" resoio auth login alice@example.com
printf '%s' "$pw" | resoio auth login alice@example.com --totp 123456

# Don't let the engine persist this session
resoio auth login alice@example.com --no-remember

# Inspect / tear down
resoio auth status --format json | jq .logged_in
resoio auth logout
```

## Output format (`--format`)

Commands that return structured data accept `--format human|json` (default `human`):

- `human` keeps the existing human-readable text.
- `json` prints a single machine-readable document to **stdout** — proto field names in
  `snake_case`, enums as their name string, big integers (e.g. `unix_nanos`) exact, non-ASCII
  preserved.

Errors always go to **stderr** and the **exit code** signals success/failure; stdout carries only
the result document.

`--format` is **not** on every command. Commands that return a single value print it raw on one
line instead of as JSON:

- `shutdown` prints the engine host PID; `terminate` prints the PIDs it killed (or `resonite
  not running`). (`launch` *does* take `--format`, returning a `resonite_pid` / `renderer_pid`
  pair.)
- `wait` prints the **resolved socket path** that became ready.
- `screenshot` / `record` / `world thumbnail` print the **saved absolute path** when writing a file
  (and `-o -` streams raw bytes to stdout with no path line).

Interactive commands (`drive`, `grab interactive`, `inventory`) have no structured output and do not
accept `--format` (`grab interactive --format json` exits with code 2).

## Examples

```bash
# Liveness
resoio ping --message hello

# Block until the engine is up (max 60s), then ping it
resoio wait -T 60 && resoio ping

# Wait for a specific engine PID's socket
resoio wait 12345

# Record 10 seconds of muxed video+audio to a timestamped file in the CWD
# (the saved absolute path is printed to stdout)
resoio record --duration 10

# ... or to an explicit path / stdout
resoio record -o out.mp4 --duration 10
resoio record -o - --video | ffplay -

# Save a single frame as PNG (timestamped file in the current directory)
resoio screenshot

# ... or to an explicit path / stdout
resoio screenshot -o shot.png
resoio screenshot -o - | feh -

# Machine-readable output, piped to jq
resoio info --format json | jq .platform
resoio world sessions --format json | jq '.[].name'
resoio session users list --format json | jq '.[].user_name'
resoio contact list --filter requests --format json | jq '.[].username'

# Read the display settings, then cap the background fps
resoio display get
resoio display set --max-fps 30

# Aim with the held cursor, grab at the ray hit point, then release
resoio cursor center
resoio grab --radius 0.5
resoio grab release
resoio cursor release

# Start Resonite (engine + renderer) and capture both PIDs
resoio launch --format json     # {"resonite_pid": ..., "renderer_pid": ...}

# Stop it — by the PIDs from launch, or auto-detect the running instance
resoio terminate 12345 12399
resoio terminate

# ... or ask a running engine to quit gracefully over gRPC (prints the engine host PID)
resoio shutdown
```

Run any command with `--help` for its full flag list. For programmatic use, see the
[API Reference](api/connection.md).
