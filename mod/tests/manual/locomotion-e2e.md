# Locomotion end-to-end 検証

`LocomotionClient.drive(...)` を実 Resonite に流して、デスクトップ
操作の全 phase が engine に反映されることを動画 (mp4) で確認する手動
検証手順。e2e harness は [python/tests/e2e/locomotion.py](../../../python/tests/e2e/locomotion.py)
で Camera + Locomotion を asyncio で並走させ、1 本の MP4 に 8 phase を
収める。

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
設定された world の場合は Bridge が `LocomotionNotReadyException`
(= `FAILED_PRECONDITION`) を投げる。e2e harness は 120 s の retry budget
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
   できれば 18 s scenario が走り、終了後 mp4 を `python/tests/e2e/e2e_artifacts/locomotion_<timestamp>/capture.mp4`
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

`FrooxEngineLocomotionBridge` 自体は info ログを出さない (毎 tick 30 Hz で
書き込むためログが flooding する)。`Drive` RPC のエラーは `Locomotion`
service 側で 1 行のみ出る。

## 期待される動画 (8 phase 視覚チェックリスト)

`capture.mp4` を host 側プレイヤーで再生して以下を順に目視確認する。

| 秒      | コマンド                   | 画面上で見えるはずの挙動                                          |
| ------- | -------------------------- | ----------------------------------------------------------------- |
| 0-3 s   | `move_y=1.0`               | 通常速度で前進する (avatar が前方向に移動、velocity default=1.0)  |
| 3-5 s   | `move_y=1.0, velocity=2.0` | **明らかに速度が上がる** (前進 phase より距離が出る)              |
| 5-7 s   | `move_x=1.0`               | 右方向にストラフ (avatar が真横に並進、向きは変わらない)          |
| 7-9 s   | `LocomotionCmd()`          | 完全停止 (engine 既存 friction で速度が 0 に減衰)                 |
| 9-11 s  | `yaw_rate=0.5`             | カメラが右に旋回し続ける (周囲が左から右に流れる、cursor lock 要) |
| 11-13 s | `pitch_rate=0.5`           | カメラが見上げる方向に動く (空が見える方向; ±89° で engine clamp) |
| 13-14 s | `jump=True`                | ジャンプ (engine の edge detect 次第で 1 回 or 連続)              |
| 14-16 s | `crouch=1.0`               | しゃがむ (avatar の頭部高さが下がる、HeadInputs.Crouch=1)         |
| 16-18 s | `LocomotionCmd()`          | 静止 (cool-down)                                                  |

fast 前進 phase の距離が通常前進 phase と区別できない場合は下記
「fast 前進 phase で速度差が見えない」を参照。

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

各 field の semantics 正典は [proto/resonite_io/v1/locomotion.proto](../../../proto/resonite_io/v1/locomotion.proto)
(velocity 単位元 1.0 / pitch 符号反転責務 / jump OR-merge を含む)。
e2e 実行で押さえるべき側面は以下のみ:

- 30 Hz tick 連発で input を hold する設計 (`Analog3DAction.ExternalInput`
  は 1 frame consume + null reset)。停止は `LocomotionCmd()` を送り続けるか
  Drive ストリームを閉じる
- 連続ジャンプ抑止は v0 では client 側の責任 (OR-merge のため edge 検出は engine 任せ)
