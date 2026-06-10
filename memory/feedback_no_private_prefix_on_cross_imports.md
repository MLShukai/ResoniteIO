---
name: no-private-prefix-on-cross-imports
description: private モジュール (_foo.py) から他モジュールへ import されるシンボルには _ prefix を付けない。privacy はモジュール名の _ prefix が担う
metadata:
  type: feedback
---

`_` prefix 付き private モジュール (例: `resoio/cli/_recording_io.py`) を切り出す
とき、**そこから sibling モジュールに import されるシンボルには `_` prefix を
付けない**。privacy の表明はモジュール名の `_` prefix が担っており、import される
シンボル側にまで `_` を付けるのは二重で誤り。

**Why:** 2026-06-10 のユーザーフィードバック。`record.py` → `_recording_io.py`
分割時に `_WavFloat32Writer` 等の `_` をそのまま持ち込んだところ、「private prefix
は import されるべき対象には付かない」と指摘を受けた。unprefixed にすれば pyright
strict の `reportPrivateUsage` / unused 系の回避策 (`__all__` への `_` シンボル
列挙) も不要になる。

**How to apply:**

- 抽出先モジュール内部でしか使わない helper / 定数だけ `_` prefix を残す
- `__all__` は export 表面のドキュメントとして引き続き置く
- テストが旧 `_` 名を pin している場合は抽出元側で
  `from ._foo import sym as _sym` の alias で互換維持 (テストは編集しない)
- 既存の `resoio._client` → `_BaseClient` はこの規約より前の legacy。リネームは
  12+ ファイルに波及するため、ユーザー判断を仰いでから行う
