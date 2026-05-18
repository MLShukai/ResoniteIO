---
name: camera-v2-doc-landed-complete
description: Camera v2 (Wave 1–5) で landed した public API は spec-driven-implementer 段階で WHY 観点の docstring が揃い、Wave 6 C13 で no-op 判定 → Wave 6 C14 で逆方向の trim pass を実施した記録
metadata:
  type: project
---

Wave 6 C13 (2026-05-18) で「不足は無い」と判定したが、その直後の Wave 6 C14
で user から **逆方向の要求** (Wave 1–5 段階で多めに書かれた docstring /
コメントを cleanup する) が来た。本 memo は両方の判断履歴を残す。

## C13 → C14 の経緯

- **C13**: spec-driven-implementer + code-quality-reviewer のサイクルで WHY が
  既に landed していたため空 commit
- **C14**: 「WHAT 説明」「PR description 系記述」「memory file との重複」「段落
  XML doc」を surgical に削った。trim 対象は load-bearing WHY (項目 1–14、
  \[\[load-bearing-whys\]\]) を残し、それ以外の冗長部分のみ

## C14 で適用した trim 方針

1. **WHAT 説明削除**: 「frame の幅 (pixel)」「全フィールドを指定して header
   を構築する」「2 つの header が同値か」等、識別子から自明な記述は削除
2. **PR description 系削除**: 「Wave 3 で追加」「C8 で実装」「C5 仕様」
   「Wave 5 / E1 で実機検証」「v1 (...) は本 commit 群で削除済み」など
3. **memory file との重複圧縮**: `feedback_camera_v2_constraints.md` に詳細が
   ある背景説明 (foreground fps 制御の reflection 経路、knowledge §3.4 への
   参照など) は `camera-v2-constraints §N` への 1 行 ref に圧縮
4. **段落 XML doc 圧縮**: 3 段落の `<remarks>` を 1〜2 段落の単一 block に
5. **manual docs 圧縮**: 「実装計画上の対応」「v1 からの regression check」
   「行ごとの詳細解説」は削除し、診断 step は箇条書きで濃縮

## C14 で残した load-bearing WHY (例)

- `FrameHeader.cs` の byte layout 表 (両プロセス bit-exact 契約)
- `IpcSocketPaths.cs` の "engine authority + drift = silent failure" 警告
- `PushedFrameCameraBridge.cs` の "cap=1 / DropOldest, width/height ignored,
  drop silent / 毎フレーム log 出さない"
- `FrameSender.cs` / `RendererFrameInterprocessReceiver.cs` の "Messenger.OnFailure
  は static event、Dispose で -= しないと leak"
- `FrooxEngineDisplayBridge.cs` の "MaxFps は engine 公式 API の都合で背景時 fps
  cap にしかマップしない" (camera-v2-constraints §9 へ ref)
- `Plugin.cs` (Renderer) の "engine 側 BepInEx 6 と異なり Renderer は BepInEx 5"
- `FrameCapture.cs` の "max depth = Overlay を選ぶ + drop-on-busy"
- `ResoniteIOPlugin.cs` の Google.Protobuf early-resolution hazard + ProcessExit 順
- `host_agent.py` の `WINEDLLOVERRIDES` Launch Options 必須性 (manual docs)

## 教訓 (今後の判断ガイド)

- C13 の判定基準「WHY 観点で十分」と C14 の判定基準「冗長」は別軸:
  - **C13 = WHY の不足を埋める** (足し方向)
  - **C14 = WHAT / PR description / 段落超過を削る** (引き方向)
- どちらも触ったあとは「load-bearing WHY が消えていないか」を最後に再確認
- 「memory file が長文 WHY を引き受ける」前提なら、各ファイル内の docstring は
  1〜3 段落で十分。あふれたら memory file 側に押し出す

関連: \[\[load-bearing-whys\]\] (どの WHY を絶対削るな) /
\[\[camera-v2-constraints\]\] (project-wide memo の本体)
