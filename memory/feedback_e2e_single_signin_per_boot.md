---
name: feedback_e2e_single_signin_per_boot
description: e2e の resonite_session fixture は test ごとに Resonite を再起動するが、連続 restart の 2 回目は cloud sign-in が確実に通らない。サインインを要する e2e シナリオは 1 file = 1 test に畳んで 1 boot / 1 sign-in に閉じる。
metadata:
  type: feedback
---

`python/tests/e2e/conftest.py` の `resonite_session` fixture は function-scoped で、test ごとに `just resonite-stop` → `resonite-start` で Resonite を再起動する。ここで **連続した 2 回目以降の boot は cloud sign-in が確実には通らない**。実測では 2 番目の test が 120s の readiness poll の間ずっと `Not signed in to a Resonite account` のままだった (fixture の SIGKILL 停止 → 即再起動で saved session の再認証が走らない/cloud 側にセッションが残る等が原因と推測)。

**Why:** Dash のような sign-in 不要なモダリティ (UserspaceRadiantDash は login 前から存在) は複数 test を並べても落ちないが、Inventory / World など `engine.Cloud.CurrentUserID` を要するモダリティは boot ごとに sign-in が要る。1 file に sign-in 必須の test を 2 つ並べると 2 つ目が `FAILED_PRECONDITION` (= `*NotReadyException`) で readiness timeout する。

**How to apply:** sign-in を要する e2e は **1 file = 1 test** に畳み、1 boot / 1 sign-in 内で全シナリオ (cloud ops + 視覚検証 + spawn 等) を回す。readiness timeout を伸ばしても 2 回目は sign-in 自体が来ないので無駄。複数 boot がどうしても要るなら test 間に十分な間隔を置くか、fixture を session-scoped 化する設計を別途検討する (現状の function-scoped clean-slate 方針とトレードオフ)。Inventory e2e (`test_folder_lifecycle_and_spawn`) は cloud ops + spawn + link + dash 視覚検証を 1 test に統合してこれを回避している。

関連: \[\[feedback_codex_drives_e2e_verification\]\] / \[\[feedback_resonite_status_before_asking\]\] / \[\[feedback_record_save_await_upload_task\]\]
