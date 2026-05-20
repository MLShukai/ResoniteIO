---
name: wave-1-2-cleanup-2026-05-20
description: Wave 1 (Core レイアウト modality 集約) + Wave 2 (UnixNanosClock 抽出 / SafeShutdown 統合 / Locomotion.Reset 例外ガード / Renderer perf 改修) 直後の docstring trim 記録
metadata:
  type: project
---

2026-05-20、commits `20460db` → `c2c2ffa` (Wave 1〜2 のリファクタリング 4 本)
直後に行った XML doc / コメントの小さな整合 pass の記録。

**Why:** Wave 1 で Core 側の `Bridge/` フォルダがモダリティ別 (`Session/`,
`Camera/`, `Locomotion/`, `Display/`) に再編され、Wave 2 で `OnEngineReady`
の partial-failure 経路と `OnProcessExit` を `SafeShutdown` に統合、
SessionHost.Start に未注入モダリティ WARN 列挙、LocomotionService.Reset に
Bridge 例外ガード、Renderer 側 (FrameSender / FrameCapture) のバッファ再
利用 + FrameId 試行ベース化が landed した。実装は揃ったが、これらの
"挙動が変わった事実" を **既存** docstring に折り込む短い pass が残って
いた (新規 docstring の追加は禁止というユーザー指示)。

**How to apply:**

- `mod/` 配下の `Core.Bridge` 言及は **Wave 1 で全て解消済み**
  (`grep -rn "Core\.Bridge" mod/` で 0 hit)。今後の trim で見つけたら
  単純に旧 namespace 残骸なので削るだけ
- `ResoniteIOPlugin.OnEngineReady` の `<remarks>` には起動途中の例外も
  `SafeShutdown` chain に流す旨を 1 文追加した。Process 終了経路と起動
  失敗経路が同じ Dispose chain を共有する事実は load-bearing
  (\[\[load-bearing-whys\]\] item 1 と並ぶ Plugin lifecycle の WHY)
- `SessionHost.Start` の `<remarks>` に「未注入モダリティは起動時に
  WARN 列挙する」1 文を追加。null Bridge → `Unavailable` の説明と並列に
  置く
- `LocomotionService` の class 冒頭 `<remarks>` に「Bridge 例外は Drive /
  Reset 両 RPC で Internal に翻訳」1 文を追加 (Wave 2 で Reset 側にも
  catch-and-translate が landed したため Drive 限定の暗黙前提が崩れた)
- Renderer 側 (`FrameSender`, `FrameCapture`) の docstring は
  spec-driven-implementer 段階で既に整合済 (buffer 再利用 / FrameId 試行
  ベースの WHY が両ファイルで matching)、cleanup pass で触らない判断

cleanup の網羅範囲:

- `/workspace/mod/src/ResoniteIO/ResoniteIOPlugin.cs`
  (`OnEngineReady` remarks 拡張)
- `/workspace/mod/src/ResoniteIO.Core/Session/SessionHost.cs`
  (`Start` remarks 拡張)
- `/workspace/mod/src/ResoniteIO.Core/Locomotion/LocomotionService.cs`
  (class remarks 拡張)
- 自身の memory の stale path 修正:
  `Core/Bridge/PushedFrameCameraBridge.cs` →
  `Core/Camera/PushedFrameCameraBridge.cs` (\[\[load-bearing-whys\]\]
  item 12) / `Core/Bridge/ILocomotionBridge.cs` →
  `Core/Locomotion/ILocomotionBridge.cs`
  (\[\[locomotion-cleanup-2026-05-19\]\] cleanup 一覧)

CLAUDE.md は既に Wave 1〜2 を反映済 (line 28 で modality 集約レイアウト、
line 29 で `SafeShutdown` 統合、line 35 で `.gitkeep` 撤去)。提案として
残せる微小な追記は **C# 側コーディング規約の「名前空間」行** に
"root namespace `ResoniteIO.Core` も cross-cutting utility (`UnixNanosClock`
等) を置く" を 1 文足すこと程度。

関連: \[\[load-bearing-whys\]\] / \[\[camera-v2-doc-landed-complete\]\] /
\[\[locomotion-cleanup-2026-05-19\]\]
