# Camera v2 end-to-end 検証

Camera v2 (Renderite framebuffer 直取り経路) を Python `CameraClient` から
end-to-end で叩き、fps と payload を測定する手動検証手順。

## 前提

- [load-verification.md](load-verification.md) (engine 側 mod load) と
  [renderer-plugin-load.md](renderer-plugin-load.md) (renderer 側 plugin load)
  の手順が両方 pass している
- Gale プロファイルに 6 plugin install 済み (`just check-gale` 全 ✓)
- Steam Launch Options に `WINEDLLOVERRIDES="winhttp=n,b" %command%`
- host で `just host-agent` daemon が GUI session の端末で起動している
  (DISPLAY / WAYLAND_DISPLAY 必須)
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
- **`screenshot.png`**: host primary monitor の full desktop capture (約 1 MB)。
  `monitor` / `bbox` 引数で別ディスプレイ / 切り出しも可能
- **`frame_sample.bin`**: 最終 `CameraFrame` の raw RGBA を
  `[u32 LE width][u32 LE height][rgba bytes...]` 形式で dump

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
が想定挙動 (詳細は camera-v2-constraints §9 / display-control.md)。実用判定として:

- `fps` が 25〜30 fps の range にある (engine `Application.targetFrameRate=30` に張り付き)
- `frame_count` が `--frames` 値に到達 (queue から正しく pull できている)
- `errors` 配列に `frame stream timeout` / `bridge faulted` 等の致命系が無い

を満たせば v2 path 全体は functional と判断する。

## 想定される失敗モードと診断

### `errors: ["frame stream timeout"]` / 取得 frame 数が 0

Receiver が frame を受け取れていない。順に確認:

1. `ls -la /home/$USER/.resonite-io/` で `resonite-<pid>.sock` が存在するか
2. engine 側 log に `RendererFrameInterprocessReceiver listening` が出ているか
3. renderer 側 log で `FrameSender attached` + `attached CommandBuffer` が出ているか
   ([renderer-plugin-load.md](renderer-plugin-load.md) で個別検証可)
4. owner / queue 名が両側で一致しているか (古い plugin build が残っていると drift する → `just deploy-mod`)

### fps が極端に低い (e.g. 1〜5fps)

- `AsyncGPUReadback` が drop-on-busy で全フレーム skip されている可能性
  (Wine + Vulkan / OpenGL backend の readback 異常遅延)
- renderer 側 log を verbose にして (`gale/Renderer/BepInEx/config/BepInEx.cfg`
  で `LogLevels = All`) `OnReadback returned error` を探す
- engine 側 receiver の `RejectedCount` を見れば validation reject 多発が分かる
  (frame size mismatch → renderer の RGBA buffer 長と `FrameHeader.PayloadLength` のズレ)

### `errors: ["bridge faulted: ..."]`

`CameraService.StreamFrames` が `Bridge.CaptureAsync` で予期外例外を受けた状態。
多くは `ChannelClosedException` = mod shutdown 中。Resonite を再起動して再試行。

### screenshot が真っ黒 / sample frame が真っ黒

- `screenshot.png` が真っ黒 → host_agent screenshot path の独立 issue。
  `just resonite-screenshot output=tmp/black.png` 単体で再現するか確認
- `frame_sample.bin` の RGBA が真っ黒 → OverlayCamera が描画していない (loading
  screen 等)。何か world を読み込んでから e2e を回す
