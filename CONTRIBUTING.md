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

Resonite itself runs on the host (via Steam); the container is for build/deploy only.

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
3. Install these plugins into the profile:
   - `ResoniteModding-BepisLoader` (>=1.5.1)
   - `ResoniteModding-BepInExResoniteShim` (>=0.9.3)
   - `ResoniteModding-BepisResoniteWrapper` (>=1.0.2)
   - `ResoniteModding-BepInExRenderer` (>=5.4) — Camera v2 (Renderite framebuffer)
   - `ResoniteModding-RenderiteHook` (>=1.1.1) — injects doorstop into the renderer process
   - `Nytra-InterprocessLib` (>=3.0.0) — shared-memory queue between engine and renderer
4. Launch Resonite once via Gale to generate `<repo>/gale/BepInEx/`.

`gale/` is `.gitignore`d and managed by the host's Gale install.

#### Steam launch options (mandatory)

In Steam → Resonite → Properties → Launch Options:

```text
WINEDLLOVERRIDES="winhttp=n,b" %command%
```

This injects the doorstop (BepInEx 5) into the Renderite renderer process. Without it the
renderer-side plugin never loads and Camera v2 stays dark. Wine prefers the system
`winhttp.dll`, so it must be overridden; Steam sanitizes env passed any other way, making the
launch option the only working path.

### 2. Open the dev container

- **VS Code:** "Dev Containers: Reopen in Container".

- **Zed:** open as a dev container.

- **CLI (headless / CI):**

  ```sh
  devcontainer up --workspace-folder .
  devcontainer exec --workspace-folder . bash
  ```

On startup the container runs:

- `initializeCommand` (host, pre-create): creates `~/.resonite-io` and `~/.resonite-io-debug`
  (0700) and records the host UID/GID into `.env` so deployed artifacts end up host-owned.
- `postCreateCommand` (container, post-create): `scripts/container-init.sh` =
  `dotnet tool restore` + `uv sync` + `pre-commit install` + Claude settings symlink.

### 3. Develop

Inside the container, drive everything through `just`:

| Recipe            | Role                                                                       |
| ----------------- | -------------------------------------------------------------------------- |
| `just init`       | Host setup (docker / `.env` / Gale profile checks)                         |
| `just gen-proto`  | Regenerate the Python code from `.proto` (`python/src/resoio/_generated/`) |
| `just format`     | Format both sides (ruff for Python, csharpier for C#)                      |
| `just test`       | Run both test suites (pytest+cov, dotnet test)                             |
| `just type`       | Run pyright in strict mode                                                 |
| `just build`      | `dotnet build -c Release` for the mod                                      |
| `just run`        | `format` → `gen-proto` → `build` → `test` → `type` (the pre-commit gate)   |
| `just deploy-mod` | Copy DLL+PDB into the Gale profile (`gale/BepInEx/plugins/ResoniteIO/`)    |
| `just check-gale` | Verify BepisLoader and the required plugins are present                    |
| `just docs-serve` | Preview the docs site (MkDocs) with live reload                            |
| `just docs-build` | Build the docs site with `--strict`                                        |
| `just clean`      | Remove build/cache output on both sides                                    |

`just --list` shows everything; per-side sub-recipes (`py-test`, `mod-build`, …) are
fallbacks for running one half. Container start/stop is handled by the dev container tooling,
not by `just`.

**Always run `just run` before committing** — all checks must be green.

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
