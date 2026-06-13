---
name: resolver-substring-ambiguity-tests
description: When testing _resolve_one / _match_one style client-side resolvers, verify the ambiguous-substring query is actually ambiguous against the real function before committing.
metadata:
  type: feedback
---

When writing tests for client-side label resolvers (`resoio.dash._resolve_one`,
and any future `_match_one`-style helper) that rank exact > casefold-exact >
unique casefold substring, **a query you intend as "ambiguous" is often actually
unique** because the substring may hit multiple keys *of the same item* rather
than multiple items.

**Why:** `_resolve_one` counts matching *items*, not matching *keys*. Example
that bit me: query `"settings"` against controls `("Open Settings" label / "Settings.Open" locale_key)` + `("World List")` resolves *uniquely* to the first
control (both its keys match, but only one item) — NOT ambiguous. To force real
ambiguity you need a substring shared across *different items*, e.g. a `"-ref"`
suffix shared by two `ref_id`s (`ctrl-open-ref`, `ctrl-list-ref`).

**How to apply:** Before committing a resolver ambiguity/no-match/exact-wins
test, run the real function in a quick `uv run python -c` snippet over the exact
fixture list and confirm the branch you assert actually fires (the project python
needs `uv run` — system python3 is too old for PEP 695 `class _Base[T]` generics
and will SyntaxError). Keep the "exact ref_id wins over a substring of another
item's label" case (set one item's `ref_id` equal to a substring of another's
`label`) — it is the highest-value resolver test and is easy to get subtly wrong.
