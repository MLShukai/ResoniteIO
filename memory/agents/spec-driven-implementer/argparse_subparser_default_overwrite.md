---
name: argparse-subparser-default-overwrite
description: Python 3.12+ argparse — nested subparser leaf defaults overwrite parent-parsed flag values; resoio CLI uses flat optional positional instead
type: feedback
---

Nested argparse subparsers are unsafe for "flag before or after subcommand" CLIs: `_SubParsersAction.__call__` parses the leaf into a fresh namespace and copies *all* attrs back, so a leaf's defaults clobber values the parent already parsed (`resoio grab --hand right release` ended up `hand=primary`). The often-cited "hasattr guard" does NOT protect against this on the repo's Python (3.12+, verified empirically 2026-06-11).

**Why:** A spec for the `resoio grab` CLI rename assumed the hasattr guard made shared parent option-parsers safe across parent+leaves; tests pinned the mixed flag-position forms and failed. The orchestrator's resolution: drop subparsers entirely.

**How to apply:** For resoio CLI commands needing a default action with flags accepted in any position, use a single flat parser with an optional positional (`action`, `nargs="?"`, `default=...`, `choices=[...]`) and dispatch in `_run` — see `python/src/resoio/cli/grab.py`. If subparsers are ever unavoidable, leaf options need `default=argparse.SUPPRESS` to avoid the overwrite.
