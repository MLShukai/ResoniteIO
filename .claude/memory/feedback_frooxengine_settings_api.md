---
name: frooxengine-settings-api
description: FrooxEngine の SettingComponent には `Settings.GetActiveSetting<T>() / UpdateActiveSetting<T>()` 静的 API でアクセス。`Engine.Current.GetCoreSetting` は存在しない。UpdateActiveSetting は内部で RunSynchronously して engine thread に dispatch する
metadata:
  type: feedback
---

FrooxEngine の `SettingComponent<T>` (Graphics / Locomotion / Cuteness 等の
カテゴリ別 setting class) にアクセスする canonical API は static class
`FrooxEngine.Settings` 経由:

```csharp
T? Settings.GetActiveSetting<T>() where T : SettingComponent<T>, new()
bool Settings.UpdateActiveSetting<T>(Action<T> update) where T : SettingComponent<T>, new()
// async バリアント: GetActiveSettingAsync / UpdateActiveSettingAsync
```

**Why:** ChatGPT 等が示唆する `Engine.Current.GetCoreSetting<T>()` は **存在
しない**。実 API は `Settings.GetActiveSetting<T>()`。`UpdateActiveSetting` は
内部で `setting.RunSynchronously(...)` を使うため、書き込みは engine update tick
上で適用される — Bridge 側で別途 engine thread dispatch を組む必要は無い。

**How to apply:**

- 新規 setting-write Bridge を書くときは `Settings.UpdateActiveSetting<TSetting>(s => { s.Field.Value = ...; })` 形式
- 取得失敗 (`GetActiveSetting<T>() == null`) は engine 起動直後の race。
  Service 層で `*NotReadyException` に翻訳して client を retry 可能にする
- 設定型は `decompiled/FrooxEngine/FrooxEngine/*Settings.cs` を直接 grep して
  実フィールド名を確認 (例: 解像度は `DesktopRenderSettings` ではなく
  **`ResolutionSettings.CurrentTargetResolution` + `CurrentCommitedResolution`**、
  fps cap は `DesktopRenderSettings.MaximumBackgroundFramerate`)
- engine の `RenderSystem.On<Foo>SettingsChanged` が renderer に config 送出
  するため、setting に値を書けば自動で renderer まで伝搬する (`DesktopConfig` /
  `ResolutionConfig` 等の renderer command は engine が裏で送る)
- **foreground fps は engine 公式 API では制御できない**: `RenderSystem.OnDesktopRenderSettingsChanged`
  は `DesktopConfig.maximumForegroundFramerate` を `null` のまま送るため、
  `Settings` 経由では foreground fps cap を変えられない。必要なら reflection で
  private `RenderSystem._messagingHost.SendCommand(new DesktopConfig {...})` を
  叩く (knowledge §3.4 の max_fps_foreground=120 と同 path)
