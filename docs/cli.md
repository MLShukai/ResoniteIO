# CLI

Installing `resoio` provides a `resoio` command (entry point `resoio.cli:main`). Commands are
**flat, named by action** — there are no subcommand groups (e.g. `resoio mic`, not
`resoio voice mic`). Each command maps to a modality client.

```bash
resoio --help
```

## Commands

| Command | Modality | Direction | Notes |
| --- | --- | --- | --- |
| `resoio ping` | Session | unary | Liveness check. |
| `resoio record` | Camera / Speaker | Resonite → Python | Capture video and/or audio to a file. `--video` / `--audio` filter; with neither, a muxed mp4/mkv. |
| `resoio mic` | Microphone | Python → Resonite | Stream audio into Resonite as a virtual mic. |
| `resoio locomotion` | Locomotion | Python → Resonite | Send movement commands. |
| `resoio manipulate` | Manipulation | unary | Grab / release. |
| `resoio display` | Display | unary | Read display info. |
| `resoio world` | World | unary | List / open worlds and sessions. |
| `resoio context-menu` | ContextMenu | unary | Open / select the radial menu. |
| `resoio dash` | Dash | unary | Drive the ESC dash overlay. |
| `resoio inventory` | Inventory | unary | Browse / spawn inventory items. |
| `resoio cursor` | Cursor | unary | Set / center / get the desktop cursor. |

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

# Center the desktop cursor (useful before opening a centered context menu)
resoio cursor center
```

Run any command with `--help` for its full flag list. For programmatic use, see the
[API Reference](api/session.md).
