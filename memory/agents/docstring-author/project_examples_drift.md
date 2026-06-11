---
name: examples-drift-after-breaking-changes
description: python/examples/ scripts drift after breaking modality changes; docstring-author must check them but report (not edit) logic fixes
type: project
---

`python/examples/` scripts are a recurring blind spot in doc passes after
breaking modality changes. Implementers update `python/src/` docstrings and
proto comments per spec, but example scripts are listed only loosely (or not
at all) in spec "ドキュメント影響" sections.

**Why:** During the 2026-06-10 Cursor-hold / ray-grab verification,
`manipulation_grab.py` (now `grabber_grab.py`) was updated but `cursor_move.py` was missed — it never
calls `release()`, so under the new hold semantics it leaves the cursor held
forever (its docstring claim "restores the original position" is now wrong).

**How to apply:** In every final doc-verification pass, read each affected
modality's `python/examples/*.py`. Docstring fixes are in scope; behavioral
fixes (e.g. adding a `release()` call) are logic — report them to the
orchestrator instead of editing. Note `docs/api/<modality>.md` links these
examples, so a stale example also makes the docs page misleading.
