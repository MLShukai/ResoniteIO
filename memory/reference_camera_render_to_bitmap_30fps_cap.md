---
name: camera-render-to-bitmap-30fps-cap
description: Resonite Camera.RenderToBitmap が ~31ms/call の hard cap で、640×480 RGBA8 の Camera streaming は ~30fps が自然上限
metadata:
  type: reference
---

> **Retired (2026-05-18)**: v1 `Camera.RenderToBitmap` 経路は Camera v2 移行 (HEAD `ff44bf8`、`FrooxEngineCameraBridge` 削除) で廃止された。後継アーキ・制約は [feedback_camera_v2_constraints.md](feedback_camera_v2_constraints.md) を参照。本ファイルは v1 時代の root cause 分析として歴史的に残置する。

`Camera.World.Render.RenderToBitmap()` (`FrooxEngineCameraBridge.CaptureAsync`
で呼ぶ engine 内 readback API) は **640×480 RGBA8 で p50 ~31ms / p95 ~32ms** で
安定し、これ以上速くならない。30fps streaming の natural cap はここ。

実測値 (Step 1 instrumentation で確認、2026-05-17):

- `b.render_to_bitmap` p50=31.0ms, p95=32.5ms, max=33.3ms (n=60×複数 window)
- `b.flip_copy` (ToTopLeftOriginRgba) p50=0.1–0.3ms ≈ 誤差
- `b.ensure_camera / ensure_buffer / dispose_buffer` ≈ 0ms (fast path)
- Service 側 `t.write` (gRPC UDS) ≈ 2ms, `t.map_proto` (ByteString.CopyFrom 含) ≈ 0.1ms
- `t.iter` (1 frame の全所要) p50=33.3ms = **正確に 30fps の周期**

含意:

- 30fps 要求で 30.0fps 出る。pacing `Task.Delay` は capture が周期超なので待ち時間 0
- 60fps 要求でも上限 30fps (RenderToBitmap が間に合わない)
- 高速化を狙うなら engine 側の render schedule / Renderite IPC に踏み込まないと無理
- pipeline 化 / latest-wins drop / UnsafeWrap zero-copy 等の "送信側" 最適化は
  capture が支配的な現状では効果ない (write+map で 2ms = budget の 7%)

過去の "30fps 要求で 25fps しか出ない" 報告は **本セッションでは再現せず**。
おそらく当時の Resonite state / world 負荷 / 他クライアント由来。再現したら
まず `[camera-metrics]` instrumentation を一時的に入れて支配区間を再確認すること
(Step 1 で作った scaffolding は branch
`feature/20260517/camera-perf-instrumentation` の reset 前 commit に残っていた
`00743e9` から復元可能)。

\[\[protobuf-3-11-4-in-resonite\]\] も参照。送信側で UnsafeWrap を入れたくなった
ときは Resonite 同梱 Protobuf の制約を先に確認すること。
