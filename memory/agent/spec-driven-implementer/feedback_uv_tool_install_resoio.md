---
name: uv-tool-install-resoio-version-skew
description: uv tool install --editable re-resolves deps and may pick betterproto2 newer than the lock; generated stubs are pinned to compiler 0.9.x and fail at import.
metadata:
  type: feedback
---

`uv tool install --editable ./python --force` creates an isolated venv that ignores `python/uv.lock` and resolves fresh. As of 2026-05-17 it pulled `betterproto2==0.10.0`, but `python/src/resoio/_generated/` was emitted by `betterproto2_compiler==0.9.0`. `betterproto2.check_compiler_version` raises `ImportError` at first import of any generated module.

**Why:** Plan calls for `~/.local/bin/resoio` to back tab-completion in commit 3 (clicomp.sh + container-init.sh). If `uv tool install` is used as-is, `resoio --help` fails at runtime even though `uv run resoio --help` works.

**How to apply:** For commit 3 (`scripts/container-init.sh` change adding `uv tool install --editable . --force`):

- Either re-regenerate proto with the resolved `betterproto2_compiler` after install (run `just gen-proto` from inside the tool venv — not trivial), or
- Pass `--with-requirements python/uv.lock` is unsupported by `uv tool install` (only `--with`), so the practical fix is `uv tool install --editable . --force --with 'betterproto2==<pinned>'` aligned with the lock, or
- Drop `uv tool install` and use a wrapper script that runs `uv run --project /workspace/python resoio "$@"` so the locked env is used.

Verify by running `resoio --help` in a fresh container shell after `just container-init`.
