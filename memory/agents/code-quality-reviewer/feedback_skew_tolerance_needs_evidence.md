---
name: skew-tolerance-needs-evidence
description: spec が定めた量的閾値 (A/V sync skew など) を実装で広げる場合、実測値を docstring か memory に 1 行残す。根拠なしで緩めると後続 step で議論が再発する。
metadata:
  type: feedback
---

spec で initial value として与えられた quantitative threshold (e.g. A/V sync 100 ms、frame interval tolerance) を実装側で広げる (e.g. 100 ms → 300 ms) 場合、必ず実測値と margin の根拠を残す。

**Why:** spec の Open Questions は「実装時に CI で安定する値を測って固定」と書かれていることが多い。実装側で広げたまま実測を残さないと、(1) 後続 step で「なぜこの値?」を再調査するコストが発生し、(2) CI が flaky 化したときに「閾値を緩める / 実装を直す」の判断軸が失われる。

**実例:** record-cli 0.5 commit (`a6b9d76`) の `test_record_muxed_audio_av_sync_t0_shared` は spec §10.3 / §11.5 の 100 ms を 300 ms に拡げた。コメントは "PyAV AAC priming + mp4 start_time rounding" としか書かれておらず、clean run の実測 skew は記録されなかった。レビューで Should 級として実測値の追記を要求。

**How to apply:** レビュー対象に "tolerance / threshold / skew / margin" のような語が含まれる assert が出てきたら、spec 値と差があるかを確認。差があるなら以下のいずれかを要求する:

- test の docstring に「実測 ≈X ms、margin Yx で Z ms」を 1 行追加
- `memory/feedback_<feature>_tolerance.md` を新設して MEMORY.md にリンク
- commit message に reasoning を残す (最低限)

「margin が広がっていること自体」は問題ではなく、「広げた根拠が残らないこと」が問題。
