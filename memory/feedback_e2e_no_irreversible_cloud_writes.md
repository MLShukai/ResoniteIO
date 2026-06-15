---
name: feedback_e2e_no_irreversible_cloud_writes
description: e2e テストは実 cloud に不可逆・対外的な副作用を出す操作 (フレンドリクエストの送信/承認/拒否、ban 等) を絶対に実行しない。状態変化系は fake bridge の integration test でのみ検証し、e2e は read-only 経路に限定する。
metadata:
  type: feedback
---

live Resonite に対して走らせる e2e (`python/tests/e2e/*.py`, `@pytest.mark.e2e`) は、**実 cloud アカウントに不可逆かつ対外的な副作用を出す操作を実行してはいけない**。Contact modality でいえば `add` (フレンドリクエスト送信) / `accept` (承認) / `remove` (削除・拒否) がこれに当たる。これらは相手ユーザーに通知が飛び、cloud 状態を書き換え、テスト内で完全には元に戻せない (add→remove の「対称ペア」でも相手側には申請履歴・通知が残りうる)。owner から「e2e でフレンドを送るのは非常に危険」と明示フィードバックがあった (2026-06-15)。

**Why:** e2e は本番 cloud と本物のアカウントを使う。read (一覧/検索/単一取得) は冪等で安全だが、write (友達申請・承認・拒否・ban・kick 相当) は他者を巻き込む外部送信であり、CI / 自動 e2e で無人実行すると spam・誤申請・関係破壊を招く。テストの「後始末で戻せる」想定は cloud の対外通知には通用しない。

**How to apply:** 状態変化系 RPC は **fake bridge を使う integration test** (C# Kestrel in-process round-trip / Python grpclib round-trip) で網羅し、そこで請求引数・例外翻訳・戻り値を検証する。e2e ファイルでは read-only 経路 (list / search / get) だけを駆動し、write 系は呼ばない旨をファイル冒頭コメントに明記する。これは Contact に限らず、将来 cloud / 対外副作用を持つ全モダリティ (例: Session の ban/kick を本番 session で撃つ、Inventory の対外共有等) に一般化して適用する。判断に迷う副作用は「相手や cloud に通知が飛ぶ/取り消せないか?」で線を引く。

関連: \[\[feedback_codex_drives_e2e_verification\]\] / \[\[feedback_e2e_single_signin_per_boot\]\] / \[\[feedback_resonite_status_before_asking\]\]
