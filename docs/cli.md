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
| `resoio cursor` | Cursor | unary | Set / center / get / release the desktop cursor. `set` and `center` hold the position until `release`. |
| `resoio shutdown` | Lifecycle | unary | Ask the engine to quit gracefully (`Lifecycle.Shutdown`); the engine exits itself and Steam/Proton reaps the renderer + launch wrappers. Prints the engine's host PID (from `Info`). |
| `resoio terminate` | Lifecycle | unary | **Deprecated** alias of `shutdown` (no longer maintained, removed in a future release). Behaves identically but prints a deprecation notice on stderr. |

`record` is the Resonite → Python capture command (it pulls Camera and Speaker), while `mic`
is its independent Python → Resonite counterpart.

`shutdown` is a pure gRPC call (no OS signals), so it works from anywhere the UDS is
reachable. A graceful shutdown is enough to stop the whole client — there is no SIGTERM/SIGKILL
fallback, because the engine's own PID is not discoverable by name (`pgrep -f Resonite.exe`
matches the Steam/Proton launch wrappers, which must not be signalled). `terminate` is the
deprecated former name of this command; prefer `shutdown`.

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

- `shutdown` / `terminate` print the engine host PID.
- `screenshot` / `record` / `world thumbnail` print the **saved absolute path** when writing a file
  (and `-o -` streams raw bytes to stdout with no path line).

Interactive commands (`drive`, `grab interactive`, `inventory`) have no structured output and do not
accept `--format` (`grab interactive --format json` exits with code 2).

## Examples

```bash
# Liveness
resoio ping --message hello

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

# Read the display settings, then cap the background fps
resoio display get
resoio display set --max-fps 30

# Aim with the held cursor, grab at the ray hit point, then release
resoio cursor center
resoio grab --radius 0.5
resoio grab release
resoio cursor release

# Ask the engine to quit gracefully (prints the engine host PID)
resoio shutdown
```

Run any command with `--help` for its full flag list. For programmatic use, see the
[API Reference](api/connection.md).
