---
name: world-modality-python
description: World modality Python layer (world.py + cli/world.py) shape and the wire/public enum offset-mapping gotcha
metadata:
  type: project
---

The `World` modality Python layer lives in `python/src/resoio/world.py`
(`WorldClient` + frozen dataclasses `WorldSession`/`WorldRecord`/`OpenWorld`/
`SessionPage`/`RecordPage` + public enums) and `python/src/resoio/cli/world.py`
(`resoio world sessions|records|random|join|start|list|focus|leave|current`,
nested-subcommand style like `cli/locomotion.py`).

**Why:** Step (post-Step-7) modality. The pinned contract was
`/tmp/world_contract_python.md`.

**How to apply / gotchas for similar work:**

- Public enums in `world.py` omit the wire `UNSPECIFIED = 0` slot, so they are
  numerically offset from the generated betterproto2 wire enums. Map
  public→wire by **name via dict tables** (`_*_TO_WIRE`), never by numeric value.
  Documented default aliases: `SessionFilter.ALL → wire UNSPECIFIED`,
  `RecordSource.PUBLIC → wire PUBLIC`, `RecordSort.CREATION_DATE → wire CREATION_DATE`, `RecordSortDirection.DESCENDING → wire DESCENDING`.
- `Join`/`Focus`/`StartWorld`/`GetCurrent` responses carry `world: OpenWorld | None` (proto `optional`). Join/Focus/Start unwrap via a `_require_world`
  helper (server promised to populate); `get_current()` returns `None` when
  `response.has_world` is False.
- `join()` requires exactly one of `session_id`/`url` (`ValueError` otherwise);
  `url` maps to the request's `session_url` field.
- ruff combines the per-symbol `from ... import X as _WireX` lines into one
  block — write them separately and let `ruff check --fix` collapse them.
