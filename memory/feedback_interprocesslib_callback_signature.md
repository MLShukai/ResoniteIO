---
name: interprocesslib-callback-signature
description: Nytra InterprocessLib `Messenger.ReceiveValueArray<T>` の callback は `Action<T[]?>` (nullable fresh array)。namespace は `InterprocessLib` (DLL 名と異なる)
metadata:
  type: feedback
---

Nytra-InterprocessLib `Messenger` (engine 側 `InterprocessLib.FrooxEngine.dll` /
renderer 側 `InterprocessLib.Unity.dll`、namespace は両方とも単に
`InterprocessLib`) の receive callback シグネチャは:

```csharp
void ReceiveValueArray<T>(string id, Action<T[]?> callback)
//                                          ^^^^^ nullable!
```

**Why:** ChatGPT 等は `ArraySegment<byte>` / `ReadOnlyMemory<byte>` / `Span<byte>`
を示唆しがちだが、実際は **fresh `T[]?` を per-frame allocate して渡す**。
nullable がついているので `byte[]?` で受ける必要があり、`byte[]` で受けると
`CS8622: Nullability of reference types ... doesn't match the target delegate 'Action<byte[]?>'` で TreatWarningsAsErrors に蹴られる。

API の正確な signature は `mono.cecil` で DLL を reflect して確認するのが最速:

```bash
dotnet run --project /tmp/peek -- /path/to/InterprocessLib.FrooxEngine.dll
# (cecil-based dumper that lists Methods + Events)
```

**How to apply:**

- engine 側 / renderer 側 receiver の callback は `void OnFrameReceived(byte[]? data)`
- 内部で null チェック → header parse → `bridge.Push(...)` の順
- `using InterprocessLib;` (NOT `using InterprocessLib.FrooxEngine;`) —
  DLL 名と namespace が異なる点に注意
- static event `Messenger.OnFailure` (Action<Exception>) / `OnWarning`
  (Action<string>) / `OnDebug` / `OnShutdown` は **必ず Dispose で `-=`**
  しないと memory leak (knowledge §7 落とし穴 #8)
