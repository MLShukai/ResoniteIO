---
name: bridge-refactor-notes
description: Mod Bridge リファクタ時の非自明な注意点 (Renderite.Shared の Chirality、composed resolver / AddRange の既存スタイル)
type: project
---

Mod 側 Bridge をリファクタするときの非自明ポイント。

- `using Renderite.Shared;` は orphan に見えても `Chirality` enum がそこに住んでいるため必要 (FrooxEngine namespace ではない)。削除候補と誤判定しない。`RaycastHit` は `FrooxEngine` 側。
- **Why:** decompiled を grep しないと名前空間が分からず、unused using と誤って消すと build が落ちる。
- **How to apply:** Bridge の using を整理する前に `decompiled/` で declaring namespace を確認する。

既存スタイルの先例 (リファクタ方針の判断材料):

- per-RPC の「world → selector → handler/grabber 解決」3 行は、ContextMenu bridge が単一 composed helper (`ResolveHandler(hand)`) に畳むスタイル。3 回以上重複したら同様に composed resolver (tuple 返し可) に寄せる。
- proto repeated string field への詰め替えは `proto.Xxx.AddRange(snapshot.Xxx)` (WorldService 先例)。要素変換が要る repeated message は foreach のまま。
- 実機検証済みのレイキャスト等 engine ロジックは「verbatim 移動のみ」(private helper 抽出) に留め、式・順序・例外 message を変えない。
