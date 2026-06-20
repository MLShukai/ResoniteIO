# Contributing to ResoniteIO

This guide covers the development setup and workflow for ResoniteIO. For the project's design,
scope, and staged implementation plan see [`resonite_io_plan.md`](resonite_io_plan.md);
for repository conventions see [`CLAUDE.md`](CLAUDE.md).

ResoniteIO is a monorepo with three pieces that mirror each other by modality:

- `proto/` — the single source of truth: `.proto` definitions (`resonite_io.v1`).
- `mod/` — the C# side (BepisLoader mod, .NET 10), split into a pure `ResoniteIO.Core`
  library and a thin `ResoniteIO` BepInEx adapter.
- `python/` — the Python side (`resoio`, `uv` + `betterproto2` + `grpclib`).

## Prerequisites (host)

All development tooling (.NET 10 SDK, `uv`, `protoc`, `pre-commit`) lives **inside a dev
container**. On the host you only need:

- `docker` (24+) and `docker compose` v2
- [`just`](https://github.com/casey/just)
- [Gale](https://github.com/Kesomannen/gale) v1.5.4+ (Resonite mod manager)
- A way to open a dev container: VS Code (Dev Containers extension), Zed, or the
  [`@devcontainers/cli`](https://github.com/devcontainers/cli)

The container builds and deploys the mod, and can also launch Resonite itself — either
vanilla (`just resonite-launch --vanilla`) or **with the ResoniteIO mod loaded** from the `./gale`
profile (`just resonite-launch` / `just resonite-stop`, see below). Mod verification runs
entirely inside the container; host Steam + Gale + `just deploy-mod` (GUI launch) still works.

To run Resonite inside the container the host needs a few extra things:

- A **graphical session** (X11 or Xwayland) and **PipeWire/PulseAudio** — the container
  reuses the host's X display and audio socket; there is no headless rendering path.
- **`kernel.apparmor_restrict_unprivileged_userns=0`** (see [AppArmor](#apparmor) below).
- A GPU. NVIDIA, AMD, and Intel are all supported; the vendor is detected automatically.

## Dev environment

### 1. One-time host setup: `just init`

Run once right after cloning. It detects `docker` / `docker compose v2`, creates `.env` from
`.env.example` (launching `$EDITOR`), validates `ResonitePath`, and checks the Gale profile.

```sh
just init
```

If the Gale profile is missing, `just init` prints the steps and exits. On the host:

1. Install Gale v1.5.4+.
2. In the Gale GUI choose **Create profile** and point it at `<repo>/gale`
   (**this path must be EMPTY — do not pre-create the `gale/` directory**).
3. Populate the profile with the required mods. **Recommended:** with the new
   profile selected, choose **Import > ... profile from file**, pick
   `<repo>/GaleProfile.r2z` (a committed Gale profile snapshot pinning the
   required mods at known versions), and **overwrite** the profile. This installs
   the whole required set in one step.
   - **Fallback (manual):** if you prefer, or if the snapshot has fallen behind a
     mod update, install these plugins individually instead:
     - `ResoniteModding-BepisLoader` (>=1.5.1)
     - `ResoniteModding-BepInExResoniteShim` (>=0.9.3)
     - `ResoniteModding-BepisResoniteWrapper` (>=1.0.2)
     - `ResoniteModding-BepInExRenderer` (>=5.4) — Camera v2 (Renderite framebuffer)
     - `ResoniteModding-RenderiteHook` (>=1.1.1) — injects doorstop into the renderer process
     - `Nytra-InterprocessLib` (>=3.0.0) — shared-memory queue between engine and renderer
4. Launch Resonite once via Gale to generate `<repo>/gale/BepInEx/`.

`GaleProfile.r2z` is a convenience snapshot only — `just check-gale` is the source
of truth for which parts must be present. `gale/` is `.gitignore`d and managed by
the host's Gale install.

#### Steam launch options (host Steam only)

If you launch Resonite from **host Steam** (Gale GUI), set the launch option in Steam →
Resonite → Properties → Launch Options:

```text
WINEDLLOVERRIDES="winhttp=n,b" %command%
```

This injects the doorstop (BepInEx 5) into the Renderite renderer process. Without it the
renderer-side plugin never loads and Camera v2 stays dark. Wine prefers the system
`winhttp.dll`, so it must be overridden; Steam sanitizes env passed any other way, making the
launch option the only working path.

The **in-container** launcher (`just resonite-launch`) needs the same override — the doorstop
is a hook `winhttp.dll` proxy that Wine only loads with `WINEDLLOVERRIDES="winhttp=n,b"` — but
`resoio launch` (`python/src/resoio/launcher.py`) sets it for you, so no manual setup is required.
`umu-run` passes the env through (unlike Steam, which sanitizes it), so the launcher can export it
directly.

### 2. Open the dev container

- **VS Code:** "Dev Containers: Reopen in Container".

- **Zed:** open as a dev container.

- **CLI (headless / CI):**

  ```sh
  devcontainer up --workspace-folder .
  devcontainer exec --workspace-folder . bash
  ```

On startup the container runs:

- `initializeCommand` (host, pre-create): records the host UID/GID into `.env` so deployed
  artifacts end up host-owned. (The gRPC socket dir is created inside the container by the mod
  itself, not bind-shared from the host.)
- `postCreateCommand` (container, post-create): `scripts/container-init.sh` =
  `dotnet tool restore` + `uv sync` + `pre-commit install` + Claude settings symlink.

### 3. Develop

Inside the container, drive everything through `just`:

| Recipe                 | Role                                                                       |
| ---------------------- | -------------------------------------------------------------------------- |
| `just init`            | Host setup (docker / `.env` / Gale profile checks)                         |
| `just gen-proto`       | Regenerate the Python code from `.proto` (`python/src/resoio/_generated/`) |
| `just format`          | Format both sides (ruff for Python, csharpier for C#)                      |
| `just test`            | Run both test suites (pytest+cov, dotnet test)                             |
| `just type`            | Run pyright in strict mode                                                 |
| `just build`           | `dotnet build -c Release` for the mod                                      |
| `just run`             | `format` → `gen-proto` → `build` → `test` → `type` (the pre-commit gate)   |
| `just deploy-mod`      | Copy DLL+PDB into the Gale profile (`gale/BepInEx/plugins/ResoniteIO/`)    |
| `just check-gale`      | Verify BepisLoader and the required plugins are present                    |
| `just resonite-launch` | Launch mod-loaded Resonite from `./gale` in the container (see below)      |
| `just resonite-stop`   | Terminate the in-container Resonite (`SIGTERM` → 3 s → `SIGKILL`)          |
| `just docs-serve`      | Preview the docs site (MkDocs) with live reload                            |
| `just docs-build`      | Build the docs site with `--strict`                                        |
| `just clean`           | Remove build/cache output on both sides                                    |

`just --list` shows everything; per-side sub-recipes (`py-test`, `mod-build`, …) are
fallbacks for running one half. Container start/stop is handled by the dev container tooling,
not by `just`.

**Always run `just run` before committing** — all checks must be green.

### 4. Run Resonite in the container (optional)

Both launchers go through `resoio launch` (`python/src/resoio/launcher.py`), which starts
Resonite via `umu-run` (umu-launcher / Proton). The read-only `/resonite` bind is synced into a
writable `/opt/resonite` by `.devcontainer/entrypoint.sh` when the container starts; the first
container start pulls GE-Proton and copies the ~2 GB install, so it is slow; later starts sync
only deltas.

- **`just resonite-launch --vanilla`** runs vanilla Resonite (`Resonite.exe -SkipIntroTutorial`)
  — handy for confirming the base game launches.
- **`just resonite-launch`** launches Resonite **with the ResoniteIO mod loaded** from the
  `./gale` Gale profile. It waits until both the engine (`resonite_pid`) and renderer
  (`renderer_pid`) processes appear and prints both host PIDs; `just resonite-stop` terminates
  them (`SIGTERM` → 3 s → `SIGKILL`). The engine side uses hookfxr
  (`--hookfxr-enable --bepinex-target ./gale/BepInEx`) and the renderer side uses the doorstop
  (a hook `winhttp.dll`). `resoio launch` sets `WINEDLLOVERRIDES="winhttp=n,b"`
  automatically (it is still required for the renderer to load it; `umu-run` passes env
  through, unlike Steam), so **no manual `WINEDLLOVERRIDES` setup is needed** on this path. It
  fail-fasts if the Gale profile has no `BepInEx/` — deploy the mod first with `just deploy-mod`.

The mod's BepInEx log is `gale/BepInEx/LogOutput.log` (`just log`); umu/Proton launch noise is
separated into `gale/BepInEx/umu-launch.log`. For mod development you can still use host Steam +
Gale + `just deploy-mod` and launch through the Gale GUI.

#### AppArmor

pressure-vessel (the Steam Linux Runtime) needs unprivileged user namespaces, which Ubuntu 24.04+
restricts by default. `kernel.apparmor_restrict_unprivileged_userns` must be `0` or the container
fails to start (hard-failed both host-side in `initialize.sh` and container-side in `entrypoint.sh`):

```sh
# temporary (until reboot)
sudo sysctl kernel.apparmor_restrict_unprivileged_userns=0
# persistent
echo 'kernel.apparmor_restrict_unprivileged_userns=0' | sudo tee /etc/sysctl.d/99-resonite-userns.conf
sudo sysctl --system
```

#### GPU

NVIDIA, AMD, and Intel are all supported. `initialize.sh` detects the host GPU vendor and writes
the matching `.env` values, picks the build-arg, and links `.devcontainer/compose.gpu.yml` to the
right per-vendor overlay (`compose.{nvidia,amd,intel}.yml`). NVIDIA relies on
`nvidia-container-toolkit` to inject the host driver; AMD (Mesa RADV) and Intel (Mesa ANV)
userspace drivers are baked into the image. None of this normally needs manual `.env` edits.

## C# mod (`mod/`)

The mod uses the BepisLoader official template layout (`Microsoft.NET.Sdk` + explicit
`PackageReference`). FrooxEngine DLLs under `$(ResonitePath)` are referenced at build time;
proto C# stubs are generated into `obj/` by `Grpc.Tools` (not committed).

- **Deploy:** the `PostBuild` target in
  [`mod/src/ResoniteIO/ResoniteIO.csproj`](mod/src/ResoniteIO/ResoniteIO.csproj) copies
  `ResoniteIO.dll`/`.pdb` into `$(ResonitePath)/BepInEx/plugins/ResoniteIO/`. The path is
  resolved from (1) `.env` `ResonitePath`, (2) Steam Windows, (3) Steam Linux, falling back
  to the `Resonite.GameLibs` NuGet (build-time only, copy skipped — CI-safe). Write
  `ResonitePath` as an absolute path (dotenv does not expand `~` / `$HOME`).
- **F5 debug:** select the `Launch` profile in `Properties/launchSettings.json` to start
  `$(GamePath)Renderite.Host.exe` for BepisLoader debug attach.
- **Thunderstore packaging:** `just mod-pack` (or `dotnet build -c Release -t:PackTS`) builds
  the zip from [`mod/thunderstore.toml`](mod/thunderstore.toml). The package README is
  [`mod/README.md`](mod/README.md) and the icon is `mod/icon.png`.
- **NuGet feeds** (pinned in `mod/NuGet.config`): `nuget.org`,
  `https://nuget.bepinex.dev/v3/index.json` (BepInEx prereleases), and
  `https://nuget-modding.resonite.net/v3/index.json` (ResonitePluginInfoProps, the
  ResoniteModding packages, `Resonite.GameLibs`).

## Python client (`python/`)

```bash
cd python
uv sync --all-extras          # creates python/.venv with resoio and deps
cd .. && just gen-proto        # regenerate src/resoio/_generated/ (committed)
cd python && uv run pytest -v --cov
uv run pyright                 # strict, configured in pyproject.toml
```

- The package is `pyright`-strict for `src/`; the generated code under `_generated/` is
  excluded from strict checking and coverage.
- **Private module convention:** files get a `_` prefix only when they have no tests (truly
  private, e.g. `_socket.py`); files that are tested keep no prefix (e.g. `camera.py`). Public
  surface is curated separately via `__all__` in the package `__init__.py`.

## proto

`proto/` is the single source of truth. The C# side generates stubs at build time; the Python
side commits its generated code. **After changing any `.proto`, run `just gen-proto` and
include the regenerated output in the same commit** (CI checks for a clean regen diff). Only
one change should touch proto at a time to keep that diff coherent.

## Documentation

The public docs site (MkDocs Material + mkdocstrings) lives under `docs/` with `mkdocs.yml` at
the repo root. Preview with `just docs-serve`, build with `just docs-build` (`--strict`).
Adding a modality? See the [`write-docs`](.claude/skills/write-docs/SKILL.md) and
[`add-new-modality`](.claude/skills/add-new-modality/SKILL.md) skills.

## Testing

Tests prefer real resources (in-process Kestrel gRPC over a real UDS, real protobuf wire);
mocking third-party / FrooxEngine surfaces is disallowed. See the
[`testing-strategy`](.claude/skills/testing-strategy/SKILL.md) skill for the full policy and
the four test categories.

## Git workflow

- Branch from `main` as `<type>/<date>/<topic>` (e.g. `feature/20260607/skeleton`); types are
  `feature`, `fix`, `refactor`, `docs`, `chore`. Never commit directly to `main`.
- Commit messages: `<type>(<scope>): <subject>` (e.g.
  `feat(python/camera): receive RGB frames via server-streaming`). Scopes are top-level
  (`mod`, `python`, `proto`, …) or modality-scoped (`mod/camera`).
- Merging to `main` is done by the maintainer. Releases follow [`RELEASE.md`](RELEASE.md).

Full conventions, encapsulation rules, and the task-triggered skills are documented in
[`CLAUDE.md`](CLAUDE.md) and [`.claude/skills/`](.claude/skills/).
