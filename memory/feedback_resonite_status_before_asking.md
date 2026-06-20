---
name: resonite-status-before-asking
description: e2e / 実機検証の可否をユーザーに問う前に必ず pgrep -af Renderite.Renderer.exe で起動状態を確認する
metadata:
  type: feedback
---

e2e / 実機検証をするか、Resonite の起動状態に関わる問いかけをユーザーにする前に、**必ず `pgrep -af Renderite.Renderer.exe` を先に実行**して起動状態を確認してから尋ねる (または起動して進める)。

**Why:** Resonite は devcontainer 内で `just resonite-launch` 起動でき、状態は renderer プロセスの有無 (`pgrep -af Renderite.Renderer.exe`) で機械的に判定できる。「Resonite 起動していますか?」「立ち上げてくれますか?」と毎回聞くのはユーザーにとって冗長で、同じやりとりの繰り返しになる。

**How to apply:**

- e2e を回す流れに入ったら、まず `pgrep -af Renderite.Renderer.exe` を実行する。
- renderer プロセスがあれば既存インスタンスでそのまま進める (または必要に応じて `just resonite-stop`→`just resonite-launch`)。
- 起動していなければ `just deploy-mod` → `just resonite-launch` で起動して進める。起動の可否を問い直さない (container 内で完結する)。
- 関連: \[\[feedback_codex_drives_e2e_verification\]\] (Codex が container 内で e2e を完結させる方針)。
