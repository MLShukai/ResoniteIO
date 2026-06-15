---
name: session-py-already-at-convention
description: session.py / cli/session.py / contact.py / cli/contact.py の Python は実装時点で既に規約準拠で、refactor 余地はほぼ無い。flag_values tuple を畳もうとすると lateral か型安全性低下になる
metadata:
  type: feedback
---

`python/src/resoio/session.py` と `python/src/resoio/cli/session.py` は spec-driven-implementer が書いた時点で既に inventory.py / world.py / cli/world.py / cli/display.py の規約に完全準拠しており、public API を変えない範囲での refactor 余地はほぼ無い。2026-06-14 のレビューで no-op 判断。**contact.py / cli/contact.py も同様** (2026-06-15 レビューで no-op)。contact は world の直系 sibling: `_CONTACT_FILTER_TO_WIRE` (ALL→UNSPECIFIED offset map)・`ContactFilter` enum・`_BaseClient[ContactStub]` + `@override _make_stub`・per-method `stub = self._require_stub()`、CLI 側は `_register_*` per-leaf + `_CONTACT_FILTER_BY_NAME` explicit dict + `_emit_contact` helper (add/accept の 2x を畳む、`_emit_open_worlds` 同型) すべて確立規約どおり。unused import / dead code / `Any` なし。

**Why:** 試した変更がすべて lateral か退化だった。

- `cli/session.py` `_run_settings_set` の 13-entry `flag_values` tuple は `apply_settings(...)` の 13 kwargs と並列に見えて DRY 違反に見えるが、(1) `**dict` 展開にすると pyright の per-kwarg 型チェックが死に `# pyright: ignore[reportArgumentType]` が必要になる (型安全性低下＝NG)、(2) passthrough 名の定数 tuple + `getattr` 化は 13-entry を 11-entry 定数に置換するだけで net 削減ゼロ＋文字列 getattr 間接化で grep 性低下。`display set` (テストが "mirrors display set" と明記) は inline `a is None and ...` だが session は 13 field あり inline chain は非現実的なので tuple+`all()` がその自然なスケール形。
- CLI `_run_*` handler の `async with Client(socket)` 4 行 shape は 7 個重複して見えるが、world.py/display.py の確立規約が「handler ごとに明示展開」。`_dispatch` factoring は *client* 層 (ContextMenu/Dash) の話で CLI handler 層ではない (project_dispatch_factoring_pattern 参照)。
- `_format_roles` の `default_*_role` 5 行は手書き padding でやや brittle だが one-shot 表示で出力が正しく、computed-width 化は behavior-equivalent rewrite (taste + 出力 pin リスク)。

**How to apply:** Session Python に再依頼が来ても、まず enum map / converter / CLI handler shape が world.py 系と一致しているか diff 確認し、一致していれば「規約準拠で no-op」と報告して手を入れない。`flag_values` tuple を畳む提案は型安全性を犠牲にするので出さない。
