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
| `resoio info` | Info | unary | Print mod/engine version, OS platform, and Wine flag. |
| `resoio record` | Camera / Speaker | Resonite → Python | Capture video and/or audio to a file. `--video` / `--audio` filter; with neither, a muxed mp4/mkv. |
| `resoio screenshot` | Camera | Resonite → Python | Save a single frame as a lossless RGBA PNG. `-o` a `.png` path or `-` for stdout; omitted writes `screenshot_<timestamp>.png` to the current directory. |
| `resoio mic` | Microphone | Python → Resonite | Stream audio into Resonite as a virtual mic. |
| `resoio drive` | Locomotion | Python → Resonite | Interactive WASD driving (`--sprint` / `--look-rate` / `--no-wait`). |
| `resoio grab` | Grabber | unary | Grab at the desktop cursor ray hit point / release (desktop mode only). The action positional (`grab` / `release` / `state` / `interactive`) defaults to `grab`; `--hand` / `--radius` work before or after it. |
| `resoio display` | Display | unary | `get` prints the current snapshot; `set` applies a partial config (`-W/--width`, `-H/--height`, `-F/--max-fps` — at least one required) and prints the post-apply snapshot. |
| `resoio world` | World | unary | List / open worlds and sessions. |
| `resoio context-menu` | ContextMenu | unary | Open / select the radial menu. |
| `resoio dash` | Dash | unary | Drive the ESC dash overlay. |
| `resoio inventory` | Inventory | unary | Browse / spawn inventory items. |
| `resoio cursor` | Cursor | unary | Set / center / get / release the desktop cursor. `set` and `center` hold the position until `release`. |

`record` is the Resonite → Python capture command (it pulls Camera and Speaker), while `mic`
is its independent Python → Resonite counterpart.

## Examples

```bash
# Liveness
resoio ping --message hello

# Record 10 seconds of muxed video+audio
resoio record out.mp4 --duration 10

# Video only
resoio record frames.mp4 --video

# Save a single frame as PNG (timestamped file in the current directory)
resoio screenshot

# ... or to an explicit path / stdout
resoio screenshot -o shot.png
resoio screenshot -o - | feh -

# Read the display settings, then cap the background fps
resoio display get
resoio display set --max-fps 30

# Aim with the held cursor, grab at the ray hit point, then release
resoio cursor center
resoio grab --radius 0.5
resoio grab release
resoio cursor release
```

Run any command with `--help` for its full flag list. For programmatic use, see the
[API Reference](api/connection.md).
