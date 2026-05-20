---
name: Generated proto layout
description: How python/src/resoio/_generated/ is structured and excluded from tooling
type: reference
---

`python/src/resoio/_generated/` is a committed protoc output tree:

- `_generated/__init__.py` is empty — the directory is just a namespace marker, no re-exports.
- `_generated/py.typed` is present so consumers see the inner generated tree as typed.
- `_generated/message_pool.py` holds a single `default_message_pool = betterproto2.MessagePool()`; nested service modules import it via `from ...message_pool import default_message_pool`.
- The actual service code lives at `_generated/resonite_io/v1/__init__.py` (one file per `.proto` package).

Tooling exclusions (must stay in sync if more dirs are added):

- `pyproject.toml [tool.pyright].exclude` lists `src/resoio/_generated/`
- `pyproject.toml [tool.ruff].exclude` lists `src/resoio/_generated/`
- `pyproject.toml [tool.coverage.run].omit` lists `src/resoio/_generated/*`

**Why:** generated code does not need to satisfy strict typing or coverage gates and re-running protoc would otherwise churn diffs.
**How to apply:** when a new modality `.proto` lands, do not add new exclude patterns — the existing `_generated/` prefix already covers it. Only revisit if the layout changes.
