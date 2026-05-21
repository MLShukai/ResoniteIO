---
name: worldmanager-world-focused
description: FrooxEngine の WorldManager.WorldFocused event 仕様と、ResoniteIO Bridge での読み出し戦略
metadata:
  type: reference
---

# WorldManager.WorldFocused event 仕様 (FrooxEngine)

`decompiled/FrooxEngine/FrooxEngine/WorldManager.cs` での確認内容
(Step 2 着手時、`just decompile` 出力で確認):

## API シグネチャ

```csharp
// WorldManager.cs
public World FocusedWorld { get; private set; }     // null 取り得る
public event Action<World> WorldFocused;            // 切替時に発火
```

```csharp
// World.cs
public User LocalUser { get; private set; }         // null 取り得る (接続前)
public string Name { get; }                         // Configuration.WorldName.Value (Sync<string> 値読み)
```

```csharp
// User.cs
public string UserName { get; }                     // userName.Value (Sync<string> 値読み)
```

## 発火タイミング

- `RunWorldFocused(World world)` が `Update()` 内 (engine update tick 上) で
  `WorldFocused?.GetInvocationList()` を逐次呼ぶ
- 旧 focused world が destroy された場合は `FocusedWorld = null` のクリア経路もある
- event は **focus 切替時に 1 回**。subscriber が後から購読しても既存 focus 状態の
  通知は来ない → 後発購読時は `WorldManager.FocusedWorld` を直接読んで初期 snapshot
  を確保する必要がある (`FrooxEngineSessionBridge.cs` で実装)

## スレッド安全性

- event 発火スレッド = engine update tick (single-threaded)
- `World.Name` / `User.UserName` は `Sync<string>` 値読みで参照型代入 publish。
  別スレッドから getter を叩いても tearing は起きるが crash しない
- ResoniteIO Bridge では `volatile World? _focusedWorld` で snapshot を保持し、
  getter は engine tick 上でない任意スレッドから cost-free に呼べる前提

## ResoniteIO での利用ポイント

- Step 2: `FrooxEngineSessionBridge` が `WorldFocused` を購読してログ出力 + snapshot 更新
- Step 3+ (Camera 等): per-frame で snapshot を読む場合も上記 tearing 許容性で十分。
  precision が必要になったら engine tick 上から push する設計に切り替える

## 関連

- \[\[core-mod-layering\]\]: Bridge IF は Core 側、FrooxEngine 実装は Mod 側
- \[\[engine-onshutdown-deferred\]\]: Engine.OnShutdown 経由の stop hook は Step 3 で再評価
