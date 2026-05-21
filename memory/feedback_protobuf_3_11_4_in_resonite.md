---
name: protobuf-3-11-4-in-resonite
description: Resonite が同梱する Google.Protobuf 3.11.4 が default ALC で先に load されることがあり、PluginAssemblyResolver で plugin folder 同梱の 3.30 に置換しきれない。3.15+ API (UnsafeByteOperations 等) は使えない
metadata:
  type: feedback
---

実機の Resonite には Google.Protobuf 3.11.4 が同梱されており、起動中に他コードから
先に load されるケースがある。その場合 `PluginAssemblyResolver`
(`mod/src/ResoniteIO/Loading/PluginAssemblyResolver.cs`) は `AssemblyLoadContext.Default.Resolving`
event hook なので「assembly が見つからない場合」しか発火せず、すでに 3.11.4 が
load された後では plugin folder 同梱の 3.30 に差し替えできない。

**Why:** Step 1 (2026-05-17) で `CameraService.MapToProto` に
`UnsafeByteOperations.UnsafeWrap` (Protobuf 3.15+ API) を導入し実機で動かしたところ、
`OnEngineReady` で probe を試した瞬間に下記の例外で mod が死んだ:

```
System.TypeLoadException: Could not load type 'Google.Protobuf.UnsafeByteOperations'
from assembly 'Google.Protobuf, Version=3.11.4.0, Culture=neutral,
PublicKeyToken=a7d26565bac4d604'.
```

JIT がメソッド突入時に referenced type を eager 解決するため、`try/catch` で囲んでも
catch されずに上位に伝搬する。

**How to apply:**

- Camera / 他モダリティ Service / Bridge で **Protobuf 3.15+ API** (`UnsafeByteOperations`,
  `ParserHelpers.WithoutOffload`, 一部の `ByteString` 拡張等) を呼ばないこと。
  3.11.4 で確実に存在する API のみ使う (`ByteString.CopyFrom`, `MessageParser` 等)。
- 必要になった場合は **PluginAssemblyResolver を Resolving event 以外の方法** で改造
  する必要がある (e.g. `AssemblyLoadContext.LoadFromAssemblyPath` を Load() 内で先回り
  実行して 3.30 を default ALC に差し込む)。これは別途検証が必要で副作用大。
- 「typeof(NewerProtoApi) を probe する」コードも危険 (JIT が同じ TypeLoadException を
  上げる)。診断したいなら `Assembly.Load(...).GetType("...")` リフレクション経由にする。
- ベンチマーク結果上、UnsafeWrap で削れるのは `t.map_proto` の ~0.1ms/frame で
  `t.iter` 全体 33ms の 0.3% でしかない (実測値、640×480)。**そもそも費用対効果は低い**。
  4K 配信などで `ByteString.CopyFrom` が ms オーダになって初めて検討対象。

参考: \[\[camera-render-to-bitmap-30fps-cap\]\] (capture 側が支配的なので送信側最適化は
そもそも効きにくい)。
