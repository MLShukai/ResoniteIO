---
name: locomotion-cleanup-2026-05-19
description: Locomotion stateful-化 (15-commit branch) 後の cleanup で削った冗長コメント / 残した load-bearing コメント / 触ったメモファイルの記録
metadata:
  type: project
---

2026-05-19 に `feature/20260519/locomotion-stateful` ブランチ完了後、
locomotion 周辺の docstring / コメントを一度 trim した記録。

**Why:** 15 コミットの間に複数 agent (spec-driven-implementer 並列実装 +
code-quality-reviewer) が同じ概念 (stateful repeater / 30Hz keep-alive
廃止 / pitch 符号反転解除 / consume-once jump / Reset 全 false 展開)
を proto / Bridge IF / Service / Bridge / CLI / e2e / manual docs に
何度も書き重ねていた。今回 proto を一次正典に据えて他は短く参照する
形に整理した。

**How to apply:**

- 今後 locomotion を改修する際は proto file (`proto/resonite_io/v1/locomotion.proto`)
  と `.claude/memory/feedback_locomotion_external_input.md` を真値として、
  Bridge / Service / Python / CLI / e2e doc のコメントは **参照 + 1 行
  要約** に留める。同じ説明を 2 箇所以上に書き直さない
- pitch 符号反転は **解除済**: Bridge は `+PitchRate` をそのまま渡す
  (\[\[load-bearing-whys\]\] item 16 を 2026-05-19 に更新済み)。`-PitchRate`
  への rollback は regression
- "Phase A/B" 等の実装フェーズ呼称はコードコメントから一掃した。
  agent-memory ではフェーズ語彙が残っているのは OK だが、配布物 (proto /
  Core / Mod / Python / docs / manual md) からは消す方針
- proto コメント変更だけでも `just gen-proto` の再生成が必要 (生成物に
  field doc が埋め込まれるため)。コメントのみの diff でも commit に
  `_generated/` の更新を含める

cleanup の網羅範囲:

- proto: `proto/resonite_io/v1/locomotion.proto` (トップレベル + field doc)
- C# Core: `mod/src/ResoniteIO.Core/Locomotion/ILocomotionBridge.cs`,
  `mod/src/ResoniteIO.Core/Locomotion/LocomotionService.cs`
- C# Mod: `mod/src/ResoniteIO/Bridge/FrooxEngineLocomotionBridge.cs`
- C# tests: `mod/tests/ResoniteIO.Core.Tests/Locomotion/*.cs`,
  `mod/tests/ResoniteIO.Core.Tests/Helpers/FakeLocomotionBridge.cs`
- Python: `python/src/resoio/locomotion.py`, `python/src/resoio/cli/locomotion.py`,
  `python/tests/resoio/{,cli/}test_locomotion.py`, `python/tests/e2e/locomotion.py`
- docs: `mod/tests/manual/locomotion-drive-cli.md`,
  `mod/tests/manual/locomotion-e2e.md`
- memory: `.claude/memory/feedback_locomotion_external_input.md`
  (§1+§2+§6+§8 を統合し §1〜§7 に再構成)

cleanup でほぼ手を入れなかったもの (現状で適切と判断):

- `python/tests/resoio/cli/test_locomotion.py` の `_KeyParser` 系テスト
  (関数名で意図が明確、docstring 無し or 1 行のまま)
- `python/src/resoio/cli/__init__.py` (locomotion 専用の追記なし)
- `python/src/resoio/__init__.py` (re-export 一覧のみ)

## Follow-up: 2026-05-19 move bug fix の cleanup

stateful 化 branch がさらに 5 commit 進み、`ApplyToEngine` の Move
書き込みが world-axis から `HeadFacingRotation` 経由の body-local 変換に
差し替わった (commit `334ccd9` 系)。実装直後はバグ修正の経緯を Bridge
コメントに 14 行ぶら下げていたが、cleanup で:

- Bridge 側コメントは「Move は body-relative。userRoot.HeadFacingRotation
  経由で Slot 系に変換する必要 (詳細は memory §8)」の 4 行に圧縮
- `feedback_locomotion_external_input.md` に §8 を新設し、原因 +
  修正 + 定量検証 (V_B/V_D の 87.1°) + decompile path を集約
- `project_load_bearing_whys.md` に item 18 を追加 (この回転ロジックを
  次の trim で消さないよう boundary を引く)
- `[[locomotion-headfacing-body-relative]]` (spec-driven-implementer
  agent-memory) は計測 prototype の経緯メモとして残し、本 §8 から
  bracket link で参照する 2 層構成 (本体 = 正典、agent-memory = 経緯)

**How to apply:** 同じ手順で「実機検証で確定した修正の WHY」が Bridge
コメントに溜まったら、proto / memory feedback ファイルに移植してから
コメントを短縮する。Bridge コメントは「memory のどこに飛べばよいか」
を 1 文で示すだけに留める。

## Follow-up: 2026-05-19 final docstring polish

`docs(locomotion): proto コメントと公開 API の説明を最終化` で以下を反映:

- `LocomotionResetSummary` の "audit" 誤解修正: Summary は engine 側で
  実際に reset した保証ではなく Service の **canonicalize 後の request
  を echo するだけ**であることを proto / 生成物 / Python `ResetSummary`
  の docstring に明記。「実際に reset した」表現は誤解を招く
- proto の `Drive` / `Reset` RPC docstring を file header / `LocomotionCommand`
  への pointer に圧縮 (stateful repeater 規約の重複を排除)
- Python `LocomotionCmd.drive` / `LocomotionCmd.reset` / `DriveSummary` /
  `LocomotionCmd` も同様に module docstring と proto を一次正典として参照
  する形に短縮
- `LocomotionCmd` の jump 説明から「rising edge of a new `SetState`」
  表現を削除: Bridge コード上 `jump=True` の各 SetState は前回 tick で
  pulse 消費済みなら **再点火する**ため、Python docstring の「unchanged
  command は再点火しない」記述は事実と食い違っていた。proto の
  "consume-once pulse" 表現を一次正典として残し、Python は pointer のみ

**How to apply:** proto + 生成物 + 公開 API の WHY 説明が重複してきたら
**proto を一次正典に据え、他は file header / proto への pointer に
圧縮する**パターンを踏襲。`just gen-proto` は host で動かせない (uv が
必要) ため、proto を編集した commit には生成物の手動 mirror 更新を含める
ことができるが、container 内で実行できる環境では `just gen-proto`
再生成が確実。

## Follow-up: 2026-05-19 strafe-drift fix re-trim

strafe-drift fix の 3 commit (`1ce09ab` / `d2cf8ef` / `b4573b0`) で
`FrooxEngineLocomotionBridge.ApplyToEngine` の Move コメントが 12 行に
再膨張していたのを 5 行に再圧縮。memory §8 に LUVR-vs-HFR の選定理由 +
pitch sink no-op の根拠 + 定量検証 (9% 漏れ → 浮動小数雑音) を集約し、
Bridge 側は body-local 不変条件 1 文 + §8 ポインタ + 未準備時 skip-and-
retry 注記の構成にした。

**Why:** 修正直後の commit でバグ調査の生 reasoning が Bridge に降りた
ままになっており、memory §8 と同じ内容を 2 箇所に保持する状況だった。
"code = WHY at the point of change、memory = full background" のレイ
ヤリングに戻す再圧縮。

**How to apply:** バグ修正コミット直後は Bridge コメントが膨らみがち。
memory に §X を新設または更新したら、その commit のあとに Bridge コメ
ントを「不変条件 1 文 + memory § ポインタ」まで圧縮する pass を入れる
こと。今回は「`userRoot / World 未準備時は今 tick を skip` 注記は残す」
という user 指示を尊重した: null check 自体は自明だが「skip しても
repeater が次 tick で retry するので benign」という reasoning は call
site でしか読まれないため、その 1 文だけは残した。
