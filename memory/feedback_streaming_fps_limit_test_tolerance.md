---
name: streaming-fps-limit-test-tolerance
description: streaming RPC の fps_limit pacing テストは「+1 edge frame + 1 boundary slip」を許容する上限で書く
metadata:
  type: feedback
---

`CameraService.StreamFrames` のような pacing 制御付き server streaming で
「fps_limit が効いているか」を時間窓 N 秒で受信フレーム数 X で検証する場合、
理論期待値 `fps × N` だけでなく **`+2 ぶんの上限スラック`** を見込むこと。

**Why:** 実装上の理由 2 つ:

1. **初回フレームは pacing 0**: ループの 1 周目は `Stopwatch.Restart()` →
   `Capture` → `Write` → `Delay(target - elapsed)` の順で進むため、最初の
   frame は即時送信され、その後 100ms 間隔 (10 fps の例) で出る。`fps × N`
   を超える 1 frame ぶん上振れする。
2. **Client 側 stopwatch boundary**: client の `Stopwatch.StartNew()` は
   call 確立直後 (= 最初の frame 受信前) から動き始めるため、windowSeconds
   boundary 上で +1 frame の slip がありうる。

Step 3 で `expectedMax = 6` (理論値 5 + 1 edge) で書いた assertion が実機で 7
を観測し fail した (commit 過程で `8` に緩和)。

**How to apply:** server-streaming の rate-limit テストでは:

- 上限: `(int)Math.Ceiling(fps * windowSeconds) + 2` を最低限の上限値として
  採用する。これより厳しい assertion は flaky になる。
- 下限: 「何か届く」程度の `>= 1` で十分。低速 CI で下振れ防止。
- 真の rate 検証 (= pacing が works) は別軸で測る (例: fps=0 の uncapped と
  比較して有意に少ないことを確認)、時間窓のみで pacing 厳密性を測ろうとしない。

「pacing 完璧」をテストで保証しようとしないこと。本テストの目的は **「全力で
ループしているわけではない」** ことの sanity check に留める。

## 関連

- \[\[core-mod-layering\]\]: Service 層は Bridge から切り離されているため、Bridge
  実装 (Fake / FrooxEngine) の capture 速度差が pacing テストに影響する。
  Fake は ~0ms、FrooxEngine は数 ms〜十数 ms。テストは Fake 前提で書く。
