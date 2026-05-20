---
name: proto-rpc-naming-except
description: 本プロジェクトは buf の RPC_REQUEST_STANDARD_NAME / RPC_RESPONSE_STANDARD_NAME を except して、streaming RPC のデータ型をモダリティ固有のドメイン名で命名する
metadata:
  type: feedback
---

`proto/resonite_io/v1/*.proto` で streaming RPC のメッセージ型は **モダリティ固有の
ドメイン名** (例: `CameraFrame`, `CameraStreamRequest`) で命名し、buf の
`RPC_REQUEST_STANDARD_NAME` / `RPC_RESPONSE_STANDARD_NAME` (`<Rpc>Request` /
`<Rpc>Response` envelope 命名を要求) は `buf.yaml` の `except` に追加して許容する。
Step 3 で Camera を追加する際にこのルールを除外した (commit `84379c7`)。

**Why:** Plan §1 Proto schema で `CameraFrame` は「データ型として再利用しうるドメイン
オブジェクト」として命名する方針が固まっている。`StreamFramesResponse` のような
RPC 名にバインドされた envelope 名は、他モダリティ (Audio: `AudioChunk`, Locomotion:
`PoseSample` 等) と命名が揃わず、Python 側 dataclass を直接 import する際にも冗長。
`SERVICE_SUFFIX` を既に except している (`Session` / `Camera` を service 名に採る)
方針の延長線上にある統一規約。

**How to apply:** 新しいモダリティ proto を追加するとき、message 型はドメイン名で
自由に命名してよい。buf lint が `RPC_REQUEST_STANDARD_NAME` /
`RPC_RESPONSE_STANDARD_NAME` で警告を出す場合は既に `buf.yaml` で除外済みなので
追加対応不要。逆に「envelope 名を強制したい」気持ちが湧いたら本ルールを見直す
タイミング。

## 関連

- \[\[core-mod-layering\]\]: Core POCO (例 `Bridge.CameraFrame`) は proto 生成型と
  別物として保ち、命名で区別する (`V1.CameraFrame` ↔ `Bridge.CameraFrame`)。
