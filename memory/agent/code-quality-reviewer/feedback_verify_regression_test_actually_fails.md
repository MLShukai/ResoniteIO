---
name: verify-regression-test-actually-fails
description: 回帰テストがバグを本当に再現しているか、レビュー時に「修正を実際に外して fail することを再現確認する」プロセスを必ず通す。implementer の報告だけを信用しない。
metadata:
  type: feedback
---

回帰テスト (regression test) を含む commit をレビューするとき、**実装側を一行ずつ revert して回帰テストが本当に fail するか自分で再現する**。implementer の「stash で確認した」report を rubber stamp しない。

**Why:** record-cli の 0.6 commit (`038cad5`) で発覚した実例 —
`test_record_muxed_stdout_broken_pipe_clean_exit` は「`_suppress_teardown_errors` を外すと cascade traceback で fail する」と主張していたが、実際に suppression を外しても (a) pump-level の `BrokenPipeError` は `_record_muxed` 内 `for t in done: if isinstance(exc, BrokenPipeError): continue` で既に吸収され、(b) teardown 中の `_suppress_teardown_errors` 3 回呼び出しは **どれも例外を raise しなかった** (PyAV 17 では container.close() が再度 stdout に書こうとしないため)。つまり test は suppression を一切 exercise しておらず、修正の有無に関わらず常に pass する dead test。「implementer が stash で確認した」と書かれていた手順が実際とズレていた可能性が高い。

**How to apply:**

1. レビュー対象 commit に regression test と claim される test が含まれていたら、まず該当 test と修正コードの対応関係を読む
2. 修正の中核ステートメント (e.g. `time_base = Fraction(1, 90_000)`、`except (X, Y): pass`) を `# DISABLED:` で潰すか body を no-op にする
3. その test だけを `pytest -x` で走らせて **本当に fail することを目で確認**
4. fail しないなら次のいずれか:
   - test が別の path を validate しているだけで本来の bug を catch していない (= test の強度不足、Should/Must 級指摘)
   - 修正自体が dead code 化している可能性 (= 修正の正当性を再評価)
5. fail することを確認したら git checkout でファイルを戻して通常 review を続行
6. ファイル戻し忘れに注意 — pytest が green に戻ることを最終確認してから報告を書く

**実例で再現できた regression:** `_record_muxed` の `v_stream.codec_context.time_base = Fraction(1, 90_000)` を `# DISABLED:` 化 → `test_record_muxed_mp4_duration_matches_real_time` が `video duration 1083.4s` で fail (期待 `< 2.0`)。これは規定通り bug を捕まえている。一方で suppression 削除では fail せず ⇒ 強度不足を Should 級で指摘。

**Don't:** 単に「implementer の言うとおり stash で確認した」と書かれた commit message を信用して probe を省略する。1〜2 分で済む。
