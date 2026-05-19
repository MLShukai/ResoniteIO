# Locomotion end-to-end 検証

`LocomotionClient.drive(...)` を実 Resonite に流して、デスクトップ
操作の全 phase が engine に反映されることを動画 (mp4) で確認する手動
検証手順。e2e harness は [python/tests/e2e/locomotion.py](../../../python/tests/e2e/locomotion.py)
で Camera + Locomotion を asyncio で並走させ、1 本の MP4 に 9 phase
(うち最後の 1 つは `LocomotionClient.reset()` の検証 phase) を収める。

## 前提

- [load-verification.md](load-verification.md) と
  [camera-v2-e2e.md](camera-v2-e2e.md) の前提条件すべて
- Gale プロファイルに 6 plugin install 済み (`just check-gale` 全 ✓):
  BepisLoader / BepInExResoniteShim / BepisResoniteWrapper /
  BepInExRenderer / RenderiteHook / InterprocessLib
- Steam Launch Options に `WINEDLLOVERRIDES="winhttp=n,b" %command%`
- host で `just host-agent` daemon が GUI session の端末で起動している
  (`DISPLAY` / `WAYLAND_DISPLAY` 必須)
- container 内で `cd python && uv sync` 済み

## World の前提

通常起動直後の home world でも walk locomotion (`SmoothLocomotionBase`
派生の active module) が入っているので、**特に world 切替は不要**で
e2e は素通る (確認: 2026-05-19 ユーザー報告)。

active module が `Teleport` / `NoClip` / `GrabWorld` などの非 walk 系に
設定された world の場合は Bridge が今 tick の write を skip する
(SetState / Reset は no-op 相当)。e2e harness は 120 s の retry budget
を持っているので、その間に locomotion mode を Walk に切り替える
(Userspace dash → Settings → Locomotion など) か、別の walk 可能 world に
join し直せばよい。

## マウス cursor lock について

window focus を Resonite に置き、画面上で右クリックしてマウス cursor lock
を有効にすると engine の `IsCursorLocked` が `true` になり Look.Active
も `true` に切り替わる。cursor unlock 状態だと yaw/pitch は engine 側で
skip され画面上動かないが、Drive RPC 自体は成功するため harness は assert
を fail させない (= 動画上で視点が固まって見える)。

cursor lock 状態は手動 e2e の "見た目で動く" 条件であり、harness が判定
できる class ではない (engine 内部状態のため)。

## 手順

container 内 shell から:

```sh
just deploy-mod                         # build + engine/renderer deploy
```

別ターミナルで:

```sh
just log                                # tail -F BepInEx LogOutput
```

container 内 shell に戻って e2e 実行:

```sh
just e2e-test locomotion
```

実行直後 host で:

1. Resonite が起動するのを待つ (Gale 経由、初回 load に数十秒〜)
2. home world が load し終わって avatar が地面に立つのを待つ (通常起動
   後の home world は walk locomotion が active なので切替不要)
3. Resonite window に focus を置き、画面上で右クリック → マウス cursor lock
4. e2e harness が 120 s の retry budget 内に Locomotion bridge を ready 検出
   できれば 20 s scenario が走り、終了後 mp4 を `python/tests/e2e/e2e_artifacts/locomotion_<timestamp>/capture.mp4`
   に書き出して PASS する

非 walk world (Teleport / NoClip 等が active な world) で動作させたい場合は
上記「World の前提」の通り 120 s 内に Walk module へ切り替える。

## 期待される engine log

`just log` で以下が時系列に出る:

```text
[Info   :ResoniteIO] Engine ready — starting Session gRPC host
[Info   :ResoniteIO] SessionHost listening on /home/<user>/.resonite-io/resonite-<pid>.sock
[Info   :ResoniteIO] Focused world: <home world name> / LocalUser: <UserName>
```

`FrooxEngineLocomotionBridge` 自体は info ログを出さない (engine update
tick ごとに `ExternalInput` を書き換える hot path なため、logging すると
flooding する)。`Drive` RPC のエラーは `Locomotion` service 側で 1 行のみ
出る。

## 期待される動画 (9 phase 視覚チェックリスト)

`capture.mp4` を host 側プレイヤーで再生して以下を順に目視確認する。

| 秒      | コマンド                                  | 画面上で見えるはずの挙動                                            |
| ------- | ----------------------------------------- | ------------------------------------------------------------------- |
| 0-3 s   | `move_y=1.0`                              | 通常速度で前進する (avatar が前方向に移動、velocity default=1.0)    |
| 3-5 s   | `move_y=1.0, velocity=2.0`                | **明らかに速度が上がる** (前進 phase より距離が出る)                |
| 5-7 s   | `move_x=1.0`                              | 右方向にストラフ (avatar が真横に並進、向きは変わらない)            |
| 7-9 s   | `LocomotionCmd()`                         | 完全停止 (engine 既存 friction で速度が 0 に減衰)                   |
| 9-11 s  | `yaw_rate=0.5`                            | カメラが右に旋回し続ける (周囲が左から右に流れる、cursor lock 要)   |
| 11-13 s | `pitch_rate=0.5`                          | カメラが **見上げる** 方向に動く (空が見える、pitch + = up)         |
| 13-14 s | `jump=True`                               | ジャンプ (Bridge が consume-once pulse 化、tick あたり 1 回)        |
| 14-16 s | `crouch=1.0`                              | しゃがむ (avatar の頭部高さが下がる、HeadInputs.Crouch=1)           |
| 16-19 s | `move_y=1.0` (pre-reset)                  | 再び通常速度で前進 (stateful repeater が `move_y` を保持)           |
| 19.0 s  | `LocomotionClient.reset()` (parallel RPC) | **同一 tick で前進が止まる** (全 state 中立化、jump pending も消失) |
| 19-20 s | `LocomotionCmd()` (post-reset idle)       | 静止 (reset 後 1 s の余韻、avatar が neutral を維持)                |

`pitch_rate` phase で「見下げる」が観測された場合は Bridge の符号反転
解除 fix の regression を疑う
(`.claude/memory/feedback_locomotion_external_input.md` §2 参照)。

fast 前進 phase の距離が通常前進 phase と区別できない場合は下記
「fast 前進 phase で速度差が見えない」を参照。

## Reset RPC 検証 phase の補足

19.0 s の `Reset` は **drive() で busy な primary client とは別の
LocomotionClient** で発火する (drive と同時 unary RPC)。手順上の意図:

- **graceful close (`CompleteAsync`) では state を維持** することを別途
  確認したい場合は、e2e harness とは独立に Python REPL で
  `async with LocomotionClient() as c: await c.drive(<short generator>)`
  を回し、stream を CompleteAsync した直後の avatar が前回 state を
  保ったままになることを目視する。e2e は `_SCENARIO_DURATION_S` 経過で
  generator 終了 → graceful close するため、20 s 末で avatar が
  neutral を保ったまま停止していれば pass (graceful 経路の検証も兼ねる)
- **ungraceful disconnect (UDS 切断 / Ctrl-C) で Bridge が全 reset**
  することを確認したい場合は、e2e harness を実行中に container 側
  pytest プロセスを `Ctrl-C` で kill する → avatar が即 neutral に
  戻ることを目視。e2e は assert しないので録画上もこの挙動だけで判定する

## トラブルシュート

### `TimeoutError: Locomotion bridge did not become ready in 120s`

`LocomotionController.ActiveModule` が `SmoothLocomotionBase` の派生で
ない (Teleport / NoClip / GrabWorld / NoLocomotion 等)。walk 可能 world
に切り替え、avatar が地面に立っている状態 (walk module active) を確認
してから再実行。

### `RpcException: Status.Unavailable, "Locomotion bridge is not configured."`

`SessionHost` に `ILocomotionBridge` が注入されていない。`just log` で
`Engine ready` 以降に `Failed to start Session gRPC host:` 等のエラーが
出ていないか、`deploy-mod` で最新の DLL が gale プロファイルに配置されて
いるかを確認。

### yaw / pitch phase で画面が動かない (移動 phase は動いている)

マウス cursor lock が外れている。Resonite window に focus を戻し、画面上で
右クリックして cursor lock を再有効化。`Drive` RPC は成功し続けるため
harness は PASS するが、動画では旋回・見上げが visible にならない。

### `pitch_rate=0.5` で見下げる方向に動く (期待: 見上げる)

Bridge が pitch 符号を反転している可能性。Bridge は `+command.PitchRate`
を素のまま渡す設計なので、`-command.PitchRate` への rollback が無いか
git log と `.claude/memory/feedback_locomotion_external_input.md` §2 で
確認する。

### Reset phase (19-20 s) で avatar が止まらない

19.0 s の Reset RPC が届いていない、もしくは Bridge が無視している。
`just log` で reset 時刻あたりに warning が出ていないか、e2e の標準
出力に `Reset RPC raised (ignored, scenario continues):` が出ていないか
確認 (出ていれば RPC エラー内容で原因を切り分け)。Reset が成功した
場合は標準出力に `Reset RPC fired @ ~19.0s: move=..., look=..., ...` が
出る。

### Camera phase は 30 fps 出るが mp4 が真っ黒

Renderite framebuffer 経路に問題あり (Locomotion 固有ではない)。
[camera-v2-e2e.md](camera-v2-e2e.md) の "screenshot が真っ黒" 節を参照。

### fast 前進 phase で速度差が見えない

`Move.magnitude > 1` で `_maxMagnitude` 経由の normalize に当たっている
可能性 (plan §既知リスク #6)。client 側で
`LocomotionCmd(move_y=1.0, velocity=3.0)` 等で倍率をさらに上げて試す
(server 側 build やり直し不要、proto 設計上の余白)。

### VR mode で yaw / pitch が動かない

`FirstPersonTargettingController` が VR mode では active にならない設計
(desktop 専用)。Bridge は silent skip するため Drive 自体は成功するが、
yaw / pitch は engine に届かない。desktop mode に切り替えて再実行。

## v0 の仕様

各 field の semantics 正典は
[proto/resonite_io/v1/locomotion.proto](../../../proto/resonite_io/v1/locomotion.proto)、
engine 側落とし穴の正典は
[`feedback_locomotion_external_input.md`](../../../.claude/memory/feedback_locomotion_external_input.md)。
e2e で実機検証する側面は以下に集約される:

- stateful repeater (proto / memory §1, §6)
- graceful close = state 維持、ungraceful disconnect = 全 reset (memory §6)
- jump は consume-once pulse (proto / memory §7)
