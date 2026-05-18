---
name: camera-v2-doc-landed-complete
description: Camera v2 (Wave 1–5) で landed した public API は spec-driven-implementer 段階で WHY 観点の docstring が既に揃っており、Wave 6 C13 では追加 docstring 不要 (空 commit) と判断した記録
metadata:
  type: project
---

Wave 6 C13 (2026-05-18) で Camera v2 関連 public surface の docstring
整備パスを走らせた結果、**対象 11 ファイル全てが既に WHY 観点で十分**
で no-op (空 commit) と判定した。

対象ファイル (すべて触らず判定):

- `mod/src/ResoniteIO.RendererShared/{FrameHeader,IpcSocketPaths}.cs`
  — byte layout / queue 同期 const の WHY を class-level XML doc に
  記述済み
- `mod/src/ResoniteIO.Core/Bridge/PushedFrameCameraBridge.cs` — cap=1
  - DropOldest / width/height ignore / drop silent の WHY が remarks
    に揃う
- `mod/src/ResoniteIO.Core/Display/{IDisplayBridge,DisplayService}.cs`
  — proto3 zero = "leave unchanged" / optional DI / FailedPrecondition
  翻訳の WHY あり
- `mod/src/ResoniteIO/Bridge/{RendererFrameInterprocessReceiver,FrooxEngineDisplayBridge}.cs`
  — Messenger static event Dispose 必須 / 背景 fps cap 制約の WHY あり
- `mod/src/ResoniteIO.Renderer/{Plugin,FrameCapture,FrameSender}.cs` —
  BepInEx 5/6 差分 / OverlayCamera 選択 / drop-on-busy の WHY あり
- `python/src/resoio/display.py` — Camera v2 pairing / proto3 default /
  context manager の WHY あり
- `scripts/{host_agent,resonite_cli,e2e_camera_v2}.py` — protocol /
  Usage / Report schema を module docstring に完備

**Why:** Wave 1–5 で spec-driven-implementer → code-quality-reviewer の
サイクルが回っており、landed 前に reviewer 段階で WHY が拾われていた。
さらに `.claude/memory/feedback_camera_v2_constraints.md` (Wave 6 landed)
が長文 WHY を引き受けるので、各ファイル側は class/method docstring
レベルの簡潔な WHY + memo への暗黙参照で足りる構造。

**How to apply:** 「camera v2 まわりの docstring 整備」と言われたとき
は、まず本 list のファイルが既に十分であることを前提に判断する。新規
ファイル (Audio / Locomotion / Manipulation 等) を docstring 整備する
際は、本 camera v2 set を good-template として参照する。Wave 1–5 並み
の reviewer pass が landed 前に入っているなら、後追いの docstring agent
は no-op になりうる前提で動く。

関連: \[\[load-bearing-whys\]\] (どの WHY を絶対削るなを記載) /
\[\[camera-v2-constraints\]\] (project-wide memo の本体)
