---
name: world-cli-surface-pins
description: Which parts of resoio world.py / cli/world.py are pinned by tests vs free to refactor
type: project
---

The World feature's Python surface is pinned by `python/tests/resoio/test_api_contract.py`
and `tests/resoio/cli/test_world.py`. When refactoring this area:

**Pinned (do NOT change):** `Thumbnail(data, content_type)` frozen+slots dataclass,
`fetch_thumbnail(self, uri: str) -> Thumbnail`, all `WorldClient` method signatures,
public enum members. CLI: subcommand names (`sessions/records/thumbnail/join/start/list/ focus/leave/current`, NO `random`), flag names/dests (`--all` -> dest `show_all`,
`-w/--wide`, `--limit` default 20), compact columns (sessions: name,host,users,access,
session_id; records: name,owner,tags,record_id), `--wide` appends `thumbnail_url`,
truncation footer exact text `... showing {limit} of {total} (use --all)` -> STDERR,
save message `saved {n} bytes ({content_type}) -> {path}` -> STDERR.

**Why:** tests assert rendered output via capsys and signatures via inspect, so output
must stay byte-identical and signatures unchanged.

**How to apply:** Internal helpers (`_print_table`, `_cap_rows`, `_print_sessions/records/ open_worlds`, `_add_table_args`) are NOT referenced by tests — free to restructure as long
as stdout/stderr bytes are identical. The `Thumbnail` construction in `fetch_thumbnail` is a
single-use 2-field wrap; do NOT extract a `_thumbnail_from_wire` helper (single-use
abstraction, against project style). `_open_world_from_wire` exists only because it has
multiple call sites.
