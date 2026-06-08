---
name: resonite-status-before-asking
description: e2e / 実機検証の可否をユーザーに問う前に必ず just resonite-status を実行する
metadata:
  type: feedback
---

e2e / 実機検証をするか、Resonite の起動状態に関わる問いかけをユーザーにする前に、**必ず `just resonite-status` を先に実行**してから尋ねる (または起動して進める)。

**Why:** host-agent は基本的に常駐稼働している。「host-agent 立ち上げてくれますか?」「Resonite 起動していますか?」と毎回聞くのはユーザーにとって冗長で、同じやりとりの繰り返しになる。`just resonite-status` で running 状態は機械的に判定できる。

**How to apply:**

- e2e を回す流れに入ったら、まず `just resonite-status` を実行する。
- `running: true` なら既存インスタンスでそのまま進める (または必要に応じて stop→start)。
- `running: false` なら `just deploy-mod` → `just resonite-start` で起動して進める。host-agent の有無を問い直さない (status が ok を返している時点で host-agent は動いている)。
- 関連: \[\[feedback_codex_drives_e2e_verification\]\] (Codex が host-agent bridge 経由で e2e を完結させる方針)。
