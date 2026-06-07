# Installation

ResoniteIO has two halves that install separately: the **C# mod** (runs inside the Resonite
client) and the **`resonite-io` Python client** (imported as `resoio`, runs wherever your
agent code runs). They
connect over a Unix Domain Socket, so both halves must run on the same host (or share the
socket directory).

!!! note "Documentation versions"
    These docs are versioned with [mike](https://github.com/jimporter/mike) and deployed to
    GitHub Pages by CI: pushing to `main` updates the **`dev`** version, and a stable release
    tag publishes a numbered version and moves the **`latest`** alias. Use the version selector
    (top of the page) to switch. To build locally, run `just docs-serve` / `just docs-build`.

## C# mod — Thunderstore

Install through a Resonite mod manager such as [Gale](https://github.com/Kesomannen/gale):
search Thunderstore for **ResoniteIO** (package `mlshukai-ResoniteIO`) and add it to your
Gale profile. The package declares its dependencies (InterprocessLib, RenderiteHook,
BepisResoniteWrapper, and — transitively — BepisLoader), so the mod manager pulls in the
full plugin set for you.

After installing, set the Steam launch option so BepisLoader can hook the client:

```text
WINEDLLOVERRIDES="winhttp=n,b" %command%
```

The [repository README](https://github.com/MLShukai/ResoniteIO#readme) explains why the
launch option is mandatory. Prefer to build the mod yourself? See
[Build from source](#build-from-source) below.

## Python client — PyPI

```bash
pip install resonite-io
```

or, inside a [`uv`](https://docs.astral.sh/uv/) project:

```bash
uv add resonite-io
```

The distribution is named `resonite-io` on PyPI but imports as `resoio`
(`import resoio`). It requires Python ≥ 3.12, is `pyright`-strict, and ships type
information (PEP 561).

## Build from source

Building from source is the path for contributing to ResoniteIO or running an unreleased
version. The full development environment — .NET 10, `uv`,
`protoc`, and tooling — lives inside a dev container; see the
[repository README](https://github.com/MLShukai/ResoniteIO#readme) for the one-time
`just init` host setup and how to open the dev container.

### C# mod

From inside the dev container:

```bash
just build        # dotnet build -c Release
just deploy-mod   # copy DLL + PDB into the Gale profile (gale/BepInEx/plugins/ResoniteIO/)
```

The mod requires a Gale profile with BepisLoader and the supporting plugins, plus the Steam
launch option `WINEDLLOVERRIDES="winhttp=n,b" %command%`. The README documents the exact
plugin list and why the launch option is mandatory.

### Python client

```bash
cd python
uv sync --all-extras   # creates python/.venv with the resoio package and deps
```

## Socket location

By default the client resolves the socket under `~/.resonite-io/`. Override it with
`RESONITE_IO_SOCKET` (full path) or `RESONITE_IO_SOCKET_DIR` (directory). See
[`ConnectionClient`](../api/connection.md) for the resolution order.
