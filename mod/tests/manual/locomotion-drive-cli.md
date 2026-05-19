# Locomotion drive CLI (`resoio locomotion drive`) 実機検証

Python CLI `resoio locomotion drive` で人が手で WASD ドライブできることを
実機 Resonite で受け入れる手動検証手順。`drive` は対話的に keypress を
読み取り、30 Hz (default) で `LocomotionClient.drive(...)` に
`LocomotionCmd` を流し続ける subcommand。

実装の真値は本 doc を参照する (`feedback` ループ防止のため `docs` 側に
キーバインドや期待挙動を集約し、コード側はここを正典とする)。

## 重要な前置き

- `ExternalInput` は engine update tick で 1 frame consume + null reset
  されるため、CLI は静止中も含めて `--rate` Hz (default 30 Hz) で
  `LocomotionCmd` を送り続ける設計
- pitch は Bridge 側で符号反転済み → CLI / Python API は素直に
  「+ = 見上げ」(矢印 ↑ が見上げ)
- jump は engine 側 OR-merge / edge detect 無し。CLI は `Space` 1 押下に
  つき **次 1 tick だけ** `jump=True` を送る pulse 化で連続ジャンプを
  抑止する
- velocity の単位元は 1.0。`--sprint X` で sprint toggle (`t`) 時の倍率を
  指定 (default 2.0)
- home world `Userspace` は NoLocomotion のため Bridge は常に
  `FAILED_PRECONDITION` を返す。**Cloud Home 等 SmoothLocomotion が
  active な world に切替えてから** CLI を起動すること
  ([locomotion-e2e.md](locomotion-e2e.md) §World の前提と同じ)
- マウス cursor lock は yaw / pitch が画面上で visible になる条件。CLI
  と Resonite window のどちらに focus を置くかで挙動が変わるため、
  「focus は CLI ターミナル、ただし操作直前に Resonite window で
  右クリック → cursor lock → CLI に戻る」のように立ち上げる

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

| Key                    | 効果                                                             |
| ---------------------- | ---------------------------------------------------------------- |
| `w` / `s`              | `move_y` ±1 toggle (排他: `w` 押下中に `s` を押すと打ち消し)     |
| `a` / `d`              | `move_x` ±1 toggle (同上)                                        |
| `←` / `→`              | `yaw_rate` ±`--look-rate` toggle (排他)                          |
| `↑` / `↓`              | `pitch_rate` ±`--look-rate` toggle (排他、↑ = 見上げ)            |
| `Space`                | jump: 次 1 tick だけ `jump=True` を送るパルス (連続ジャンプ抑止) |
| `t`                    | sprint toggle: `velocity` を 1.0 ⇄ `--sprint` 値で切替           |
| `c`                    | crouch toggle: `0.0` ⇄ `1.0`                                     |
| `x` または `0`         | stop all: 全 state を default (neutral) へ即リセット             |
| `?`                    | help を stderr に再表示                                          |
| `q` / `Esc` / `Ctrl-C` | 終了。`DriveSummary` を stdout に 1 行出力                       |

設計理由:

- Shift 単独 keypress は termios で取れないため、sprint は `t` キーで
  toggle 化している (Shift+W 同時押し検出は採用しない)
- 矢印キーは ANSI escape sequence (`ESC [ A/B/C/D`)。CLI 側で 3 状態
  parser を実装する前提で、SSH 越し / xterm 系 terminal の標準動作に
  依存する
- `q` を yaw 左に使うか終了に使うか競合する場合、**終了優先で `q` = exit**。
  yaw 左は `←` のみ提供する (シンプル優先のため `[` 等のフォールバックは
  付けない)

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
stderr に `\r` で更新表示されることを確認。

### 個別キーチェック

各キーを 1 つずつ叩き、Resonite 画面で挙動が見えることを確認する。
全 phase の間 CLI は 30 Hz で送信を継続している (停止 phase でも
neutral cmd を送り続けている前提)。

- `w` で前進開始、もう一度 `w` で停止 (toggle)
- `s` で後退開始、`a` 左 strafe、`d` 右 strafe
- 矢印 ↑ で見上げ (pitch + = 見上げ)、↓ で見下げ、← / → で yaw 旋回
  (Resonite window 側で cursor lock 必須)
- `t` で sprint on (`velocity=2.0` 相当)、もう一度で off。目視で歩幅
  / 移動距離が変わることを確認
- `Space` で **1 回だけ** ジャンプ (押しっぱなしでも 1 jump、`Space`
  を離して再度押すと 2 回目の jump)
- `c` で crouch on/off、avatar の頭部高さが下がる
- `x` または `0` で全停止 (`move_x` / `move_y` / `yaw_rate` / `pitch_rate`
  / `sprint_on` / `crouch_on` を default に戻す)
- `?` で help が stderr に再表示される

### 終了

`q` で終了 → stdout に `DriveSummary` 相当の 1 行が出る
(例: `received_count=540 first_command_at=... last_command_at=...`)。
`received_count` は `(送信した tick 数) - (server 側で drop された数)` を
意味し、20 秒程度の操作で **300 以上** (30 Hz × 約 10 s 以上) になって
いれば pass。

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

### `--rate 60` (60 Hz 送信)

```sh
resoio locomotion drive --rate 60
```

20 秒程度操作して `q` で終了。`received_count` が 30 Hz 時より概ね
**2 倍** 近い値になっていることを確認 (network / scheduler の jitter で
完全 2 倍にはならない)。engine 側 fps と独立に CLI 送信レートだけ上がる
ことを確認。

### `--sprint 3.0` (sprint 倍率上げ)

```sh
resoio locomotion drive --sprint 3.0
```

`w` 前進 → `t` で sprint on で目視確認、default `--sprint 2.0` 時より
明らかに速い (engine 側 `_maxMagnitude` の clamp に当たる可能性は
[locomotion-e2e.md](locomotion-e2e.md) §トラブルシュート「fast 前進
phase で速度差が見えない」を参照)。

### `--look-rate 2.0` (旋回 / 見上げ速度倍)

```sh
resoio locomotion drive --look-rate 2.0
```

← / → / ↑ / ↓ の旋回 / 見上げ速度が default の 2 倍になることを目視確認
(cursor lock 必須)。

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
- [ ] `Space` 1 押下で jump が 1 回だけ発生する (連発で連続 jump、押し
  っぱなしで 1 jump)
- [ ] sprint toggle (`t`) で歩幅 / 移動距離が明確に変わる
- [ ] CLI 終了後 (`q` / `Ctrl-C` / Resonite kill いずれの経路でも)、tty
  が正常状態に戻る (`echo foo` が動く、改行が崩れない、`stty sane`
  不要)
- [ ] SSH 越しでも上記操作がすべて同じく可能
- [ ] `DriveSummary.received_count > 0` (実用上は 300 以上を目安)
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

連打のキーリピート間隔が `--rate` (default 30 Hz = 33 ms) より短いと、
2 回目の `Space` が 1 tick 内に複数届いて 1 pulse に圧縮されることが
ある。`--rate 60` で再試行。

### `q` を押しても終了しない

CLI が `q` を yaw 左にバインドしていないことを確認 (本仕様では `q` =
exit のみ、yaw 左は `←`)。それでも終了しない場合は `Ctrl-C` で abort
して bug を [load-verification.md](load-verification.md) と同じ要領で
issue 化。

### 終了後に tty が壊れた (echo が効かない、改行が崩れる)

CLI の `_raw_tty` context manager が `tcsetattr` で元に戻せていない
critical な regression。応急処置として `stty sane` を実行。再現手順を
issue 化。
