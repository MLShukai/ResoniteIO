# Locomotion drive CLI (`resoio locomotion drive`) 実機検証

Python CLI `resoio locomotion drive` で人が手で WASD ドライブできることを
実機 Resonite で受け入れる手動検証手順。`drive` は対話的に keypress を
読み取り、state 変化があったとき `LocomotionClient.drive(...)` に
`LocomotionCmd` を流す subcommand。

field semantics の正典は
[`proto/resonite_io/v1/locomotion.proto`](../../../proto/resonite_io/v1/locomotion.proto)、
engine 側落とし穴の正典は
[`feedback_locomotion_external_input.md`](../../../.claude/memory/feedback_locomotion_external_input.md)
にあり、本 doc は実機チェックリストに集中する。

## 重要な前置き

- mod 側 Bridge は stateful repeater (proto / memory 参照)。CLI は state
  変化時に 1 回送るだけで avatar が動き続ける
- pitch は Bridge で符号反転しない → 矢印 ↑ が見上げ。逆挙動を観測したら
  pitch fix の regression を疑う
- velocity の単位元は 1.0。`--sprint X` で sprint toggle (`t`) 時の倍率を
  指定 (default 2.0)
- home world `Userspace` は NoLocomotion のため Bridge は常に
  `FAILED_PRECONDITION` を返す。**Cloud Home 等 SmoothLocomotion が
  active な world に切替えてから** CLI を起動すること
- マウス cursor lock は yaw / pitch が画面上で visible になる条件。
  「focus は CLI ターミナル、ただし操作直前に Resonite window で
  右クリック → cursor lock → CLI に戻る」のように立ち上げる
- **graceful 終了 (`q` / EOF) は CLI 側で `LocomotionClient.reset()` を
  1 回呼んで neutral に戻す**。これに対し **Ctrl-C kill / UDS 切断
  (ungraceful)** は mod 側 Bridge の disconnect 検知で全 state を自動 reset

## 前提

- [load-verification.md](load-verification.md) と
  [locomotion-e2e.md](locomotion-e2e.md) の前提条件すべて
- Steam Launch Options に `WINEDLLOVERRIDES="winhttp=n,b" %command%`
- host で `just host-agent` daemon が GUI session の端末で起動している
- container 内で `cd python && uv sync` 済み
- `just deploy-mod` で最新の `ResoniteIO.dll` が gale プロファイルに
  配置済み
- host 側 Resonite が起動済み (`just resonite-status` で `running: true`)
  かつ walk-capable world に入っている (Cloud Home 等。`Userspace` のまま
  だと bridge ready 待機が必ず timeout する)

## キーバインド一覧

| Key            | 効果                                                                          |
| -------------- | ----------------------------------------------------------------------------- |
| `w` / `s`      | `move_y` ±1 toggle (排他)。1 回押すと前進 / 後退が継続、もう一度で停止        |
| `a` / `d`      | `move_x` ±1 toggle (同上)                                                     |
| `←` / `→`      | `yaw_rate` ±`--look-rate` toggle (排他、継続旋回)                             |
| `↑` / `↓`      | `pitch_rate` ±`--look-rate` toggle (排他、↑ = 見上げ)                         |
| `Space`        | jump: `jump=True` を 1 回送る (Bridge 側 consume-once pulse)                  |
| `t`            | sprint toggle: `velocity` を 1.0 ⇄ `--sprint` 値で切替                        |
| `c`            | crouch toggle: `0.0` ⇄ `1.0`                                                  |
| `x` または `0` | stop all: 全 state を default (neutral) へ即リセット                          |
| `?`            | help を stderr に再表示                                                       |
| `q` / EOF      | graceful 終了: 終了直前に `LocomotionClient.reset()` で全 state を neutral 化 |
| `Ctrl-C`       | ungraceful kill: UDS 切断 → mod 側 disconnect 検知で全 state 自動 reset       |

設計理由:

- Shift 単独 keypress は termios で取れないため sprint は `t` toggle 化
  (Shift+W 同時押し検出は採用しない)
- 矢印キーは ANSI escape sequence (`ESC [ A/B/C/D`)。SSH 越し / xterm 系
  terminal の標準動作に依存
- `q` 終了優先 (yaw 左は `←` のみ提供)。`[` 等のフォールバックは無し

## 基本受け入れ手順 (container 内)

container 内 shell から実行する場合:

```sh
just container-shell
resoio locomotion drive
```

期待:

- stderr に help (キー一覧 + `?` で再表示) と "ready" 相当のメッセージが
  出る
- Bridge ready 待機が完走する (Cloud Home 等なら数秒)。`Userspace` のまま
  起動した場合は最大 120 s で `TimeoutError` を出して abort

起動直後にステータス行 (`move_y=0 move_x=0 ... velocity=1.0 ...` 相当) が
stderr に `\r` で表示され、key 押下に応じて更新されることを確認 (CLI は
event-driven 化されており、何も押さなければ status 行も静止する)。

### 個別キーチェック

各キーを 1 つずつ叩き、Resonite 画面で挙動が見えることを確認する。
キーを押さずに数秒放置しても avatar の current state (= 前回押した状態)
が engine 側で持続することも併せて確認する (stateful repeater の証拠)。

- **`w` 1 回押下 → 前進が継続** (押し続け不要)、もう一度 `w` で停止
- `s` 後退、`a` 左 strafe、`d` 右 strafe (いずれも toggle)
- **矢印 ↑ で視点が上向き** (pitch fix の regression catch)、↓ で下向き、
  ← / → で yaw 旋回 (Resonite window 側で cursor lock 必須)
- `t` で sprint on (`velocity=2.0`)、目視で歩幅 / 移動距離が変わる
- `Space` で **1 回だけ** ジャンプ (consume-once pulse)
- `c` で crouch on/off、avatar の頭部高さが下がる
- `x` または `0` で全停止
- `?` で help が stderr に再表示される

### 終了

`q` (または EOF) で graceful 終了 → CLI は `LocomotionClient.reset()`
を 1 回呼んでから exit する。avatar が neutral に戻ることを目視確認
(`w` で前進継続中に `q` → 前進が止まる)。stdout に `DriveSummary`
相当の 1 行が出る。**`received_count` は state 変化時にだけ
インクリメントされる**ので 1 桁から数十程度でも pass。

**`Ctrl-C` で kill** → UDS 切断 → mod 側 disconnect 検知で全 state が
自動 reset され、avatar が neutral に戻ることを目視確認。`q` と
`Ctrl-C` のどちらでも最終的に avatar が止まれば pass。

## SSH 経由の確認

別ホストから container にぶら下がる経路:

```sh
ssh -t user@host docker compose exec dev resoio locomotion drive
```

`ssh -t` の `-t` で pty を強制確保することがポイント (これが無いと
termios raw mode で fail する)。

期待:

- 起動時に stderr の help が SSH 越しに見える
- WASD / 矢印 / `Space` / `t` / `c` / `x` / `?` がすべてローカル実行
  時と同じ挙動になる
- `q` で正常終了し、stdout に `DriveSummary` 1 行
- `Ctrl-C` でも abort 可能で、shell に exit 130 で戻る

## `--no-wait` (Bridge ready 待機 skip) 確認

`--no-wait` を付けると Bridge ready retry を skip して即 drive ストリームを
開く。`Userspace` でも CLI 起動自体は成功するが、drive 開始直後に
`FAILED_PRECONDITION` (`Locomotion bridge is not ready`) で abort する
ことを確認 (異常系の早期エラー経路):

```sh
# Userspace に戻ってから:
resoio locomotion drive --no-wait
# → 1 秒以内に "FAILED_PRECONDITION" 系エラーで非 0 exit
```

## エッジケース

### `--sprint 3.0` (sprint 倍率上げ)

```sh
resoio locomotion drive --sprint 3.0
```

`w` 前進 → `t` で sprint on で目視確認、default `--sprint 2.0` 時より
明らかに速い (engine 側 `_maxMagnitude` の clamp に当たる可能性は
[locomotion-e2e.md](locomotion-e2e.md) §トラブルシュート「fast 前進
phase で速度差が見えない」を参照)。

### `--look-rate 180.0` (旋回 / 見上げ速度を default の 2 倍)

```sh
resoio locomotion drive --look-rate 180.0
```

← / → / ↑ / ↓ の旋回速度が default (90 deg/s) の 2 倍 (180 deg/s) になる
ことを目視確認 (cursor lock 必須)。default 90 deg/s は engine の
`MouseSettings.MouseLookSpeed` default (100) に近い水準。

### Resonite を CLI 起動後に kill

CLI が drive 中に host で `just resonite-stop` を叩く:

```sh
# container 内:
resoio locomotion drive
# (別 shell で) just resonite-stop
```

期待: CLI が `Resonite gone` 相当の RPC エラー (`Unavailable` /
`Cancelled` のどちらか) を catch し、tty を raw mode から復元してから
非 0 で exit。**tty の echo が壊れたまま shell に戻らない** ことが
critical な pass 条件。

## Pass 判定

すべて満たせば pass:

- [ ] WASD / 矢印 / `Space` / `t` / `c` / `x` / `?` の各キー効果が engine
  で目視確認できる
- [ ] `w` 1 回押下で前進が **継続** する (押し続け不要)、もう一度押すと
  停止 (stateful repeater が機能している証拠)
- [ ] 矢印 ↑ で視点が **上向き**、↓ で **下向き** に動く (pitch 符号
  反転解除 fix の regression catch)
- [ ] `d` 1 回押下 → 5 秒間、avatar が **真横 (画面右)** にだけ進み、
  前後方向に visible なドリフトが出ない (strafe-drift fix の regression
  catch、`feedback_locomotion_external_input.md` §8。HFR ベースだった
  旧実装では `d` 中に ~9% 前方ドリフトが見えていた)。`a` で左方向も同様
- [ ] 視点を下向きに ~30° pitch down してから `d` を押下 → 水平方向に
  strafe を維持し、avatar が地面に沈んだり浮いたりしない (pitch sink
  が GroundTraction 分岐で零化されていることの確認)
- [ ] `Space` 1 押下で jump が 1 回だけ発生する (連打で連続 jump)
- [ ] sprint toggle (`t`) で歩幅 / 移動距離が明確に変わる
- [ ] `q` で graceful 終了 → CLI 側の明示 reset で avatar が neutral
  に戻る
- [ ] `Ctrl-C` で kill → mod 側 disconnect 検知で avatar が neutral に
  戻る
- [ ] CLI 終了後 (`q` / `Ctrl-C` / Resonite kill いずれの経路でも)、tty
  が正常状態に戻る (`echo foo` が動く、改行が崩れない、`stty sane`
  不要)
- [ ] SSH 越しでも上記操作がすべて同じく可能
- [ ] `Userspace` で `--no-wait` 起動時に即 `FAILED_PRECONDITION` で
  abort する

## トラブルシュート

### CLI 起動時に termios エラー / `inappropriate ioctl for device`

stdin が tty ではない。`ssh` 越しなら `-t` を付け直す。`docker compose exec` 越しなら `-it` (justfile では `just container-shell` が `-it` を
明示しているのでそちらを使う)。

### Bridge ready 待機が常に timeout する (120 s)

[locomotion-e2e.md](locomotion-e2e.md) §トラブルシュート
「`TimeoutError: Locomotion bridge did not become ready in 120s`」と同じ
原因 (`Userspace` 等の NoLocomotion world)。Cloud Home に join 直し。
急ぐ場合は `--no-wait` で skip して abort されることを観測してから world
切替。

### yaw / pitch phase で画面が動かない (移動 phase は動いている)

cursor lock が外れている。Resonite window に focus を戻し、画面上で
右クリック → cursor lock を再有効化してから CLI ターミナルに focus を
戻す。

### `Space` 連打で 1 回しか jump しない

Bridge consume-once + キーリピート間隔が engine tick (60 Hz = 16 ms) より
短くなると同じ engine tick 内に複数届いて 1 pulse に圧縮される可能性が
ある。少し間隔を空けて押し直す。

### `q` を押しても終了しない

CLI が `q` を yaw 左にバインドしていないことを確認 (本仕様では `q` =
exit のみ、yaw 左は `←`)。それでも終了しない場合は `Ctrl-C` で abort
して bug を [load-verification.md](load-verification.md) と同じ要領で
issue 化。

### 終了後に tty が壊れた (echo が効かない、改行が崩れる)

CLI の `_raw_tty` context manager が `tcsetattr` で元に戻せていない
critical な regression。応急処置として `stty sane` を実行。再現手順を
issue 化。
