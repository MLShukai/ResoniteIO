---
name: manipulation-service-no-handleasync
description: なぜ ManipulationService を ContextMenuService 流の単一 HandleAsync helper に統合しないか
metadata:
  type: feedback
---

`ManipulationService` は ContextMenu と違い、3 RPC を単一の `HandleAsync` helper に
統合「しない」のが正しい。RequireBridge / InvokeBridge の 2 分割のまま各 override に
インラインで呼ぶ形を維持する。

**Why:**

- ContextMenu の 5 RPC は全部 `ContextMenuState` を返し hand しか引数が無いので
  `HandleAsync(rpc, hand, call, ctx)` 1 本に畳める。
- Manipulation は RPC ごとに形が違う: `Grab` は point+radius を取り別 proto 型
  `ManipulationGrabResult` (Grabbed フィールド付き) を返す。`Release`/`GetState` は
  `ManipulationGrabState` を返す。共通化できるのは Release/GetState の 2 つだけで、
  これは「2 回まで OK、3 回目で抽象化」閾値の内側 (CLAUDE.md 開発原則 2)。
- Grab を無理に HandleAsync に押し込むと over-abstraction になり repo の simplicity
  方針に反する。

**How to apply:** Manipulation 周りの refactor で「ContextMenu に揃えて HandleAsync に
統合しろ」という指摘が来ても実施しない。RequireBridge/InvokeBridge の 2 helper 構成は
ContextMenu の内部 helper と shape が一致しており既に house style に沿っている。
