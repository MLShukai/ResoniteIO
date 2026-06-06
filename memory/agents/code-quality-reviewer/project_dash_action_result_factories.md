---
name: dash-action-result-factories
description: FrooxEngineDashBridge の Invoke/Highlight/Scroll は DashActionResultSnapshot を 3x ずつ重複生成していた。Rejected/Succeeded の private factory に畳むのが正解
metadata:
  type: project
---

`FrooxEngineDashBridge` の操作系 RPC (Invoke / Highlight / Scroll) は best-effort UIX 操作で、結果を例外でなく `DashActionResultSnapshot` で返す。リファクタ前は各メソッドが「型不一致で reject」と「成功」の snapshot を inline 構築していて、同一 shape が 3 メソッド × 2 ケース = 6 箇所に重複していた。

**修正**: 既存の `NotFound(refId)` (Found=false) と対称に `Rejected(refId, detail)` (Found=true, Ok=false) と `Succeeded(refId)` (Found=true, Ok=true) の private static factory を追加し、3 メソッドを guard-chain (resolve → component check → succeed/reject) として読めるようにした。

**Why:** プロジェクトの DRY 規約「2 回まで OK、3 回目で抽象化」に合致。`NotFound` が既に factory の前例。public API / wire / Core←Mod 境界は不変 (private helper のみ)。
**How to apply:** 他モダリティの best-effort 操作 Bridge (将来の Manipulation 等) でも `<Modality>ActionResultSnapshot` 系を返すなら同じ NotFound/Rejected/Succeeded factory 三点セットを最初から置く。Service 層は既に generic `HandleAsync<TSnap,TProto>` + MapToProto overload で綺麗なので触らない。
