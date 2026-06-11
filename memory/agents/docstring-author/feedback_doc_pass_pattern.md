---
name: doc-verification-pass-pattern
description: Effective workflow for verifying docs after a spec-driven modality change in resonite-io
type: feedback
---

For "final docstring/doc verification" tasks after spec-driven implementation
in resonite-io, the source-side docs (proto comments, C# XML doc, Python
docstrings, CLI help) are usually already correct — the specs dictate exact
doc wording and implementers follow it. The real work is in `docs/` and
`python/examples/`.

**Why:** Verified on 2026-06-10 (Cursor hold / ray-based Grab): all of
`mod/src/`, `python/src/`, and `proto/` matched the spec verbatim; only
`docs/api/*.md`, `docs/cli.md`, `docs/architecture/modalities.md`, and one
example script needed attention.

**How to apply:**

1. Read the spec's confirmed doc wording (確定文面) tables first.
2. Grep for stale terms across `mod/src`, `python/src`, `docs`, `proto`
   (e.g. removed concepts like "one-shot warp", "WorldPoint",
   "SetMousePosition") — a zero-hit grep quickly clears the source side.
3. Focus edits on `docs/` pages: per-modality API page admonitions
   (breaking-change notes use `!!! warning` with 4-space indented body,
   maintained by hand — mdformat excludes `docs/`), the CLI table row, and
   the modalities matrix row.
4. This agent environment has no Bash tool — ask the orchestrator to run
   `just docs-build` (--strict) to validate.
