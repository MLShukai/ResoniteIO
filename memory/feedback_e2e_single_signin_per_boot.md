---
name: feedback_e2e_single_signin_per_boot
description: e2e safety 制約 — (1) sign-in は boot ごとに確実に通らないので sign-in 必須シナリオは 1 file = 1 test に畳む、(2) 実 cloud に不可逆・対外的な副作用 (friend 申請/承認/拒否・ban 等) を出す操作は e2e で撃たず read-only に限定する。
metadata:
  type: feedback
---

## Sign-in は 1 boot に畳む

`python/tests/e2e/conftest.py` の `resonite_session` fixture は function-scoped で、test ごとに `just resonite-stop` → `resonite-launch` で Resonite を再起動する。ここで **連続した 2 回目以降の boot は cloud sign-in が確実には通らない**。実測では 2 番目の test が 120s の readiness poll の間ずっと `Not signed in to a Resonite account` のままだった (SIGKILL 停止 → 即再起動で saved session の再認証が走らない/cloud 側にセッションが残る等が原因と推測)。

**Why:** Dash のような sign-in 不要なモダリティ (UserspaceRadiantDash は login 前から存在) は複数 test を並べても落ちないが、Inventory / World など `engine.Cloud.CurrentUserID` を要するモダリティは boot ごとに sign-in が要る。1 file に sign-in 必須の test を 2 つ並べると 2 つ目が `FAILED_PRECONDITION` (= `*NotReadyException`) で readiness timeout する。

**How to apply:** sign-in を要する e2e は **1 file = 1 test** に畳み、1 boot / 1 sign-in 内で全シナリオ (cloud ops + 視覚検証 + spawn 等) を回す。readiness timeout を伸ばしても 2 回目は sign-in 自体が来ないので無駄。Inventory e2e (`test_folder_lifecycle_and_spawn`) は cloud ops + spawn + link + dash 視覚検証を 1 test に統合してこれを回避している。

## 不可逆な cloud write を撃たない

live Resonite に対して走らせる e2e は、**実 cloud アカウントに不可逆かつ対外的な副作用を出す操作を実行してはいけない**。Contact modality でいえば `add` (friend 申請) / `accept` (承認) / `remove` (削除・拒否) がこれに当たる。これらは相手ユーザーに通知が飛び、cloud 状態を書き換え、テスト内で完全には元に戻せない (add→remove の対称ペアでも相手側に申請履歴・通知が残りうる)。owner から「e2e でフレンドを送るのは非常に危険」と明示フィードバックがあった (2026-06-15)。

**How to apply:** 状態変化系 RPC は **fake bridge を使う integration test** (C# Kestrel in-process / Python grpclib round-trip) で網羅し、請求引数・例外翻訳・戻り値を検証する。e2e ファイルでは read-only 経路 (list / search / get) だけを駆動し、write 系は呼ばない旨をファイル冒頭コメントに明記する。Contact に限らず cloud / 対外副作用を持つ全モダリティ (Session の ban/kick を本番 session で撃つ、Inventory の対外共有等) に一般化する。判断に迷う副作用は「相手や cloud に通知が飛ぶ/取り消せないか?」で線を引く。

関連: \[\[feedback_codex_drives_e2e_verification\]\] / \[\[feedback_record_save_await_upload_task\]\]
