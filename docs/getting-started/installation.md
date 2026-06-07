# Installation

ResoniteIO has two halves that install separately: the **C# mod** (runs inside the Resonite
client) and the **`resoio` Python client** (runs wherever your agent code runs). They
connect over a Unix Domain Socket, so both halves must run on the same host (or share the
socket directory).

!!! note "Documentation versions"
    These docs are versioned with [mike](https://github.com/jimporter/mike) and deployed to
    GitHub Pages by CI: pushing to `main` updates the **`dev`** version, and a stable release
    tag publishes a numbered version and moves the **`latest`** alias. Use the version selector
    (top of the page) to switch. To build locally, run `just docs-serve` / `just docs-build`.

## C# mod — Thunderstore

!!! warning "Placeholder"
    The Thunderstore package is not published yet. Once it is, you will install it through a
    Resonite mod manager such as [Gale](https://github.com/Kesomannen/gale):

    ```text
    # PLACEHOLDER — not yet available
    Search Thunderstore for "ResoniteIO" and install it into your Gale profile.
    ```

Until then, build and deploy the mod from source (see below).

## Python client — PyPI

!!! warning "Placeholder"
    The PyPI package is not published yet. Once it is:

    ```bash
    # PLACEHOLDER — not yet available
    pip install resoio
    ```

Until then, install the Python client from source (see below).

## Build from source (works today)

This is the supported path right now. The full development environment — .NET 10, `uv`,
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

The `resoio` package is `pyright`-strict and ships type information (PEP 561).

## Socket location

By default the client resolves the socket under `~/.resonite-io/`. Override it with
`RESONITE_IO_SOCKET` (full path) or `RESONITE_IO_SOCKET_DIR` (directory). See
[`ConnectionClient`](../api/connection.md) for the resolution order.
