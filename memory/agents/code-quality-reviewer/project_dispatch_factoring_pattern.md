---
name: dispatch-factoring-pattern
description: Why _dispatch differs between same-return modalities (ContextMenu) and multi-return modalities (Dash) — not an inconsistency to "fix"
type: project
---

Python modality clients in `python/src/resoio/` share an async-context-manager

- `_dispatch` helper shape, but `_dispatch`'s responsibility legitimately
  varies by how many distinct result types the modality's RPCs return.

**Fact:** When every RPC returns the *same* dataclass (e.g. `ContextMenuClient`
— all RPCs return `ContextMenuState`), `_dispatch` folds in BOTH the
not-connected guard AND the proto→dataclass decode, so public methods are
one-liners (`return await self._dispatch(...)`). When RPCs return *different*
types (e.g. `DashClient` — `DashState` / `DashTree` / `DashActionResult`),
`_dispatch` is generic `_dispatch[T]` and centralizes ONLY the guard; each
public method applies its own typed `_xxx_from_proto` decoder.

**Why:** Folding the decode into `_dispatch` for a multi-return modality would
require erasing the return type to `Any`, breaking pyright strict. The guard is
the only concern shared across all RPCs, so that is all that gets centralized.

**How to apply:** Do NOT "fix" Dash to match ContextMenu (or vice versa) for
consistency — the difference is a correct adaptation, not a DRY/altitude
defect. Also note: proto message fields declared `optional=True` (e.g.
`DashElement.rect` is `DashRect | None`) require a real None-guard in the
`_from_proto` helper; that branch is type-safety, not dead code.
