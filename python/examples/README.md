# resoio examples

各モダリティの **最小 API 呼び出しサンプル** を 1 ファイル = 1 モダリティで
収録する。 `python/src/resoio/cli/` の production CLI や `python/tests/e2e/` の
回帰テストは "完全形" で重いため、ライブラリの呼び方を最短で把握したい場合は
こちらを読む。

## 前提

- ホスト側で Resonite が起動しており、`ResoniteIO` mod が load 済み
- mod が `~/.resonite-io/` 配下に UDS を bind 済み (初回環境構築は
  [`.claude/skills/setup-resonite-env/SKILL.md`](../../.claude/skills/setup-resonite-env/SKILL.md))
- 依存は dev container 内にすべて閉じている (`uv sync` 済み)

モダリティ固有の追加前提:

- `microphone_send.py` — Resonite Settings → Audio Input で "ResoniteIO" の
  virtual mic デバイスを選択しないと音は鳴らない (mod 起動後 1 回だけ)
- `locomotion_drive.py` — `SmoothLocomotionBase` が active な world (default
  Home Cloud は OK。Teleport / NoClip / NoLocomotion world は不可)
- `display_config.py` — Resonite が desktop mode で起動していること (VR mode
  では `ResolutionSettings` が異なる経路を通る)
- `world_browse.py` — cloud に login 済みで join 可能な公開セッションが見える
  こと (session list が空 = signed out / 空 cloud の場合は notice を print して
  安全に終了する)
- `context_menu_interact.py` — desktop の T-key radial menu が出せる状態
  (LocalUser / InteractionHandler が attach 済みの world にいること)
- `dash_navigate.py` — userspace の Esc dash が開ける状態 (engine boot 済み)。
  screen が少ない logged-out 状態でも開閉は可能だが navigation 先が減る
- `inventory_manage.py` — cloud に login 済み (inventory ops は実 cloud
  inventory を叩く)。書込先は自分で mkdir する `/Inventory/__resoio_example__`
  配下のみで、最後に rm -r で後片付けする
- `cursor_move.py` — Resonite が desktop mode で起動していること (cursor は
  desktop window 座標を操作する。カーソル自体は screenshot に写りにくいので、
  動いたことの可視確認は context menu を開く `tests/e2e/cursor.py` を参照)

## 実行

すべて引数なし。dev container 内で:

```bash
uv run python python/examples/connection_ping.py
uv run python python/examples/server_info.py
uv run python python/examples/camera_view.py
uv run python python/examples/speaker_record.py
uv run python python/examples/microphone_send.py
uv run python python/examples/locomotion_drive.py
uv run python python/examples/display_config.py
uv run python python/examples/grabber_grab.py
uv run python python/examples/world_browse.py
uv run python python/examples/context_menu_interact.py
uv run python python/examples/dash_navigate.py
uv run python python/examples/inventory_manage.py
uv run python python/examples/cursor_move.py
uv run python python/examples/auth_status.py
```

各 example の内容:

| File                       | やること                                                                                    |
| -------------------------- | ------------------------------------------------------------------------------------------- |
| `connection_ping.py`       | `Connection.Ping` を 1 回呼んで RTT と server timestamp を print                            |
| `server_info.py`           | `Info.GetServerInfo` を 1 回呼んで mod/engine version・platform・Wine 判定を print          |
| `camera_view.py`           | 5 秒 streaming して fps と最終フレームの輝度統計を print                                    |
| `speaker_record.py`        | 5 秒 streaming して peak amplitude を print + `speaker_output.raw` に raw float32 LE で保存 |
| `microphone_send.py`       | 440 Hz / 3 秒 mono sine wave を生成し virtual mic に送信                                    |
| `locomotion_drive.py`      | 6 秒 scripted シナリオで forward → strafe → yaw → jump → neutral を流し、reset() で締める   |
| `display_config.py`        | 現在解像度 → 1024x768 apply → 元解像度に restore                                            |
| `grabber_grab.py`          | Mirror を inventory spawn → cursor 照準 → grab → release の positive pick-up サイクル       |
| `world_browse.py`          | session list → join → list_open_worlds → focus → leave (空 cloud は notice して終了)        |
| `context_menu_interact.py` | T-key radial を open → get_state → highlight(0) → invoke(first enabled) → close             |
| `dash_navigate.py`         | Esc dash を open → list_screens → set_screen(key) → get_tree → invoke(first) → close        |
| `inventory_manage.py`      | 一時 dir を mkdir → cp -r → mv → list で確認 → finally で rm -r 後片付け                    |
| `cursor_move.py`           | get_position → center(0.5,0.5) → move(0.25,0.25) → 元位置に restore                         |
| `auth_status.py`           | `Auth.Status` を 1 回呼んで login 状態 (signed-in user / session expiry) を print           |

## FAILED_PRECONDITION について

Resonite cold-boot 中 (UDS は bound 済みだが engine の `LocalUser` /
`FocusedWorld` がまだ attach されていない期間) は、各 bridge が
`grpclib.exceptions.GRPCError(status=Status.FAILED_PRECONDITION)` を返す。

各 example は `wait_for_ready()` という小さな inline retry helper を持ち、
1〜2 秒間隔で 60〜120 秒間 retry する。production レベルで同じことを
やりたい場合は、より厳密な実装例として `python/tests/e2e/*.py` の
`wait_for_*_ready()` 系を参照。

## 出力 artifact

- `speaker_output.raw` — `speaker_record.py` が生成する raw float32 LE stereo
  (48 kHz)。再生は `ffplay`:

  ```bash
  ffplay -f f32le -ar 48000 -ac 2 speaker_output.raw
  ```

## production reference

examples では「最短コード」を優先しているため、以下は意図的に削っている:

- argparse / CLI flag 群 (引数は module-level constant で固定)
- Signal handler (Ctrl+C は asyncio の default 挙動に委ねる)
- Per-frame 詳細ログ
- WAV / MP4 header / muxing (raw float32 / 統計 print のみ)
- TTY 制御 (Locomotion は scripted シナリオのみ、対話操作なし)
- 厳密な error 分類 (FAILED_PRECONDITION 以外の status はそのまま投げる)

完全形が必要な場合は対応する CLI / e2e を参照:

| Example                    | CLI                                                         | E2E                                                                     |
| -------------------------- | ----------------------------------------------------------- | ----------------------------------------------------------------------- |
| `connection_ping.py`       | [`cli/ping.py`](../src/resoio/cli/ping.py)                  | [`tests/e2e/connection.py`](../tests/e2e/connection.py)                 |
| `server_info.py`           | [`cli/info.py`](../src/resoio/cli/info.py)                  | -                                                                       |
| `camera_view.py`           | [`cli/record.py`](../src/resoio/cli/record.py) (video 経路) | [`tests/e2e/camera_stream.py`](../tests/e2e/camera_stream.py)           |
| `speaker_record.py`        | [`cli/record.py`](../src/resoio/cli/record.py) (audio 経路) | [`tests/e2e/speaker_record.py`](../tests/e2e/speaker_record.py)         |
| `microphone_send.py`       | [`cli/mic.py`](../src/resoio/cli/mic.py)                    | [`tests/e2e/mic_send.py`](../tests/e2e/mic_send.py)                     |
| `locomotion_drive.py`      | [`cli/drive.py`](../src/resoio/cli/drive.py)                | [`tests/e2e/locomotion.py`](../tests/e2e/locomotion.py)                 |
| `display_config.py`        | [`cli/display.py`](../src/resoio/cli/display.py)            | [`tests/e2e/display_resolution.py`](../tests/e2e/display_resolution.py) |
| `grabber_grab.py`          | [`cli/grab.py`](../src/resoio/cli/grab.py)                  | [`tests/e2e/grabber.py`](../tests/e2e/grabber.py)                       |
| `world_browse.py`          | [`cli/world.py`](../src/resoio/cli/world.py)                | [`tests/e2e/world.py`](../tests/e2e/world.py)                           |
| `context_menu_interact.py` | [`cli/context_menu.py`](../src/resoio/cli/context_menu.py)  | [`tests/e2e/context_menu.py`](../tests/e2e/context_menu.py)             |
| `dash_navigate.py`         | [`cli/dash.py`](../src/resoio/cli/dash.py)                  | [`tests/e2e/dash.py`](../tests/e2e/dash.py)                             |
| `inventory_manage.py`      | [`cli/inventory.py`](../src/resoio/cli/inventory.py)        | [`tests/e2e/inventory.py`](../tests/e2e/inventory.py)                   |
| `cursor_move.py`           | [`cli/cursor.py`](../src/resoio/cli/cursor.py)              | [`tests/e2e/cursor.py`](../tests/e2e/cursor.py)                         |
| `auth_status.py`           | [`cli/auth.py`](../src/resoio/cli/auth.py)                  | [`tests/e2e/auth.py`](../tests/e2e/auth.py)                             |
