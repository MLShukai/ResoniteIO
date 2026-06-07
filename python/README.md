# resoio

Python client for [Resonite IO](../README.md). Wraps the `resonite_io.v1` gRPC
schema (UDS transport, async via `grpclib`) into a friendly client library.

## Quick start

```bash
# From the repo root, install all dependencies (creates python/.venv)
cd python
uv sync --all-extras

# (Re)generate the protoc output checked into src/resoio/_generated/
cd .. && bash scripts/gen_proto.sh

# Run the test suite
cd python && uv run pytest -v --cov

# Type-check (pyright strict, configured via pyproject.toml)
uv run pyright
```

## Layout

```
python/
├── pyproject.toml         # uv-managed project, pyright/ruff/pytest config
├── src/resoio/
│   ├── __init__.py        # exposes __version__ via importlib.metadata
│   ├── connection.py      # ConnectionClient (Step 2 placeholder)
│   ├── py.typed           # PEP 561 marker
│   └── _generated/        # protoc output, committed
└── tests/                 # mirrors src/resoio/ 1-to-1
```

The package is `pyright`-strict for `src/`. The generated protobuf code under
`_generated/` is excluded from strict type checking and from coverage.
