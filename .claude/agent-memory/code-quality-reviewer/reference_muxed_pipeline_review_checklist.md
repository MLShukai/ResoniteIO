---
name: muxed-pipeline-review-checklist
description: PyAV muxed (video+audio) 実装をレビューする際に必ず通すチェックリスト。flush 順序・共有 t0・header handshake・PTS 単調性・例外集約・resource leak の 7 観点。
metadata:
  type: reference
---

resonite-io の `_record_muxed` のような PyAV muxed pipeline をレビューするときに見るポイント。新しい muxed 実装 (Microphone+Camera 合成や録画 v2 など) が出てきたら、最低でも以下を確認する。

1. **flush MUST 順序** — `try/finally` ネストで「video flush → audio flush → close」が保証されているか。各段が独立した `finally` 内で守られているか (片方が例外を投げても他方が走るか)。cancel / BrokenPipeError 経路でも `container.close()` が必ず呼ばれるか。
2. **共有 t0** — video / audio pump が同じ `_MuxedState.t0_nanos` を anchor して PTS を計算しているか。両 pump のどちらが先に届いても t0 が一意に確定するか。asyncio 単一スレッドなので CAS 不要、と code 上に書かれているか。
3. **mp4 first-packet handshake** — mp4 muxer は first packet で stream metadata を凍結する。video 寸法 (`width`/`height`) が確定する前に audio packet が mux されると、video stream が 0×0 で固定され `avcodec_send_frame` が失敗する (`AVERROR_EXTERNAL`)。`asyncio.Event` で audio pump を gate しているか。matroska は許容するが mp4 は不可。詳細は \[\[pyav-mp4-video-dims-before-audio-mux\]\] (spec-driven-implementer 側 memory)。
4. **PTS 単調性 nudge と cumulative offset の整合** — `pts <= prev_seen` で `+1` nudge したとき、次回 PTS 計算の base (`sample_offset` など) が nudge 値に追従するか、しないなら「単調性は server-side で保証される」と code コメントで明示されているか。追従しないと nudge が連鎖して PTS が drift する可能性。
5. **`asyncio.wait(FIRST_COMPLETED) + cancel + gather` の組み立て** — done に複数 task が入った場合の例外集約戦略 (最初の非吸収例外を raise / `ExceptionGroup` で集約) が明確か。pending は cancel + `gather(..., return_exceptions=True)` で待機完了するか。外側 cancel は両 task を cancel → gather してから raise する形になっているか (= 仕様 §8.1 / `record.py::_record_muxed` のパターン)。
6. **BrokenPipeError / CancelledError の swallow 範囲** — pump 内で BrokenPipe を捕まえているか、それとも上位 `_run` の `try/except BrokenPipeError` で吸収する設計か。`container.close()` 自身が BrokenPipe を投げる可能性も outer catch で吸収できる位置に置かれているか。
7. **A/V sync 検証の許容 skew** — `start_time` 比較で許容する skew の値が spec 値より緩い場合、実測 (stress-run ≥5 回) を残したか。CI flake のリスクを評価したか。詳細は \[\[skew-tolerance-needs-evidence\]\]。

**How to apply:** PyAV / FFmpeg を使う muxed パイプラインのコードレビュー依頼があったらこのリストを開く。各観点について「該当する code 位置」「カバーする test」「不足があれば Should/Nice」を順に書き出すと網羅性が担保される。
