# Camera v2 end-to-end 検証

Camera v2 (Renderite framebuffer 直取り経路) を Python `CameraClient`
から end-to-end で叩き、fps と payload を測定する手動検証手順。
E1 で実際に走らせたフローをそのまま文書化したもの。

## 前提

- [load-verification.md](load-verification.md) (engine 側 mod load) と
  [renderer-plugin-load.md](renderer-plugin-load.md) (renderer 側 plugin load)
  の手順が両方 pass している
- Gale プロファイルに 6 plugin install 済み (`just check-gale` 全 ✓)
- Steam Launch Options に `WINEDLLOVERRIDES="winhttp=n,b" %command%`
- host で `just host-agent` daemon が起動している (別ターミナル):
  - 初回は `scripts/.venv` を `uv venv` で作って
    `scripts/requirements.txt` の `mss` 等を解決する。冪等
  - GUI session (DISPLAY / WAYLAND_DISPLAY 必須) で実行する必要あり
- container 内 shell で作業する (`just container-shell`)

## 手順

container 内 shell から:

```sh
just deploy-mod                                  # build + engine/renderer deploy
just resonite-start                              # host 経由で Gale → Resonite 起動
```

別ターミナル (container 内でも host でも OK) で:

```sh
just log                                         # engine 側 BepInEx LogOutput を tail -F
```

engine 側 log に以下が出るのを確認:

```text
[Info   :ResoniteIO] Engine ready — starting Session gRPC host
[Info   :ResoniteIO] [ResoniteIO] RendererFrameInterprocessReceiver listening: ...
[Info   :ResoniteIO] SessionHost listening on /home/<user>/.resonite-io/resonite-<pid>.sock
```

そのうえで e2e harness を回す:

```sh
just e2e-camera-v2 --frames=120 --output-dir=tmp/e2e-run-N
```

完了後:

```sh
cat tmp/e2e-run-N/report.json
just resonite-stop                               # 後始末
```

## 出力物 (E1 実測の例)

`tmp/e2e-run-N/` 配下に以下が生成される:

- **`report.json`**: 集計結果 (下記参照)
- **`screenshot.png`**: host monitor 1 (primary) の full desktop capture。
  約 1 MB。e2e harness が `mss` (host) で取って network 経由で container に
  転送する経路。`monitor`/`bbox` 引数で別ディスプレイ / 切り出しも可能
- **`frame_sample.bin`**: 最終 `CameraFrame` の raw RGBA を simple frame layout
  で dump (`[u32 LE width][u32 LE height][rgba bytes...]`)。サイズは
  `8 + width * height * 4` bytes (E1 で 1118×651 RGBA8 ≒ 2.91 MB の pixel に
  8 byte header を足した値)

`report.json` の例 (E1 実測):

```json
{
  "fps": 30.08,
  "frame_count": 120,
  "elapsed_sec": 3.99,
  "thresholds": {"fps": 55, "mse": null},
  "errors": ["camera fps 30.08 < threshold 55.0"],
  "ok": false,
  "screenshot_path": ".../tmp/e2e-run-N/screenshot.png",
  "frame_sample_path": ".../tmp/e2e-run-N/frame_sample.bin"
}
```

## 判定基準

`scripts/e2e_camera_v2.py` の合格条件 (`FPS_THRESHOLD = 55.0`):

- `screenshot_ok == true` かつ `camera_fps >= 55.0` のとき `ok=true`
- `--skip-camera` 指定時は screenshot のみ取得し `ok` は screenshot 成功のみで判定

**ただし foreground fps cap (default 30) の制約**により、現時点では `ok=false`
が想定挙動。これは Plan §risk / user 合意済みで、`max_fps_foreground` を上げる
PR (knowledge `/home/dev/.claude/plans/camera-v2-shortest-route-knowledge.md`
§3.4 の reflection 経路) は別途扱う。

実用判定としては:

- `fps` が 25〜30 fps の range にある (engine `Application.targetFrameRate=30`
  に張り付いている)
- `frame_count` が指定 `--frames` 値に到達 (= queue から正しく pull できている)
- `errors` 配列に `frame stream timeout` / `bridge faulted` 等の致命系が無い

を満たせば v2 path 全体は functional と判断する。

## 想定される失敗モードと診断

### `errors: ["frame stream timeout"]` / 取得 frame 数が 0

Receiver が frame を受け取れていない状態。順に確認:

1. `ls -la /home/$USER/.resonite-io/` で `resonite-<pid>.sock` が存在するか
   (engine 側 SessionHost は bind したか)
2. engine 側 log に `RendererFrameInterprocessReceiver listening` が出ているか
   (Wave 3 C6 の Receiver が Start 済みか)
3. renderer 側 log で `FrameSender attached` + `attached CommandBuffer` が
   出ているか ([renderer-plugin-load.md](renderer-plugin-load.md) で個別検証可)
4. owner / queue 名が両側で完全一致しているか (`net.mlshukai.resonite-io.camera`
   / `resonite-io-camera-frames`、本来コンパイル時定数なのでズレることは無い
   が renderer 側 plugin の古いビルドが残っていると起こりうる →
   `just deploy-mod` で再 deploy)

### fps が極端に低い (e.g. 1〜5fps)

- `AsyncGPUReadback` が drop-on-busy で全フレーム skip されている可能性。
  Wine + Vulkan / OpenGL backend で readback が異常遅延する場合あり
- renderer 側 log を verbose に: `gale/Renderer/BepInEx/config/BepInEx.cfg`
  で `[Logging.Console] LogLevels = All`、`[Logging.Disk] LogLevels = All` に
  変更して `OnReadback returned error` 系の warning を探す
- engine 側 receiver の `RejectedCount` (public property) を上げて取ると
  validation reject が多発しているか確認できる (frame size mismatch
  → renderer 側 RGBA buffer 長と FrameHeader.PayloadLength のズレ)

### `errors: ["bridge faulted: ..."]`

`CameraService.StreamFrames` が `Bridge.CaptureAsync` で予期外例外を受けた状態。
`bridge faulted: <内部例外メッセージ>` で原因が出る。多くは `Channel` の
ChannelClosedException = `PushedFrameCameraBridge` が Dispose 済み (= mod が
shutdown 中)。Resonite を再起動して再試行。

### screenshot が真っ黒 / sample frame が真っ黒

- `screenshot.png` が真っ黒 → host_agent screenshot path の問題で v2 path とは
  独立した issue。`just resonite-screenshot output=tmp/black.png` 単体で
  再現するか確認
- `frame_sample.bin` から復元した RGBA が真っ黒 → renderer 側 OverlayCamera が
  実際に何も描画していない可能性 (loading screen 等のタイミング)。
  Resonite で何か world を読み込んでから e2e を回す

## v1 からの regression check

v1 (`FrooxEngineCameraBridge`) は本 commit 群 (Wave 5 C11) で削除済み。
v1 → v2 切替に伴う UDS / Session / Camera の API 表面は変わっていないため、
[load-verification.md](load-verification.md) の SessionHost 起動・Focused
world log の手順は v2 でも引き続き有効。`just log` 観測の対象が増えただけ。
