---
name: speaker-engine-tap
description: Speaker (Resonite → Python) は Engine 側 AudioOutputDriver.AudioFrameRendered を HarmonyLib Postfix で tap する経路で完結 (Renderer plugin 不要)。Audio は方向別に Speaker/Microphone modality に分割する設計。
metadata:
  type: feedback
---

Audio modality は **方向別に分割** し、Resonite → Python は `Speaker` service、Python → Resonite は `Microphone` service として **別 proto service** に切る。**音声系を双方向 1 service にしない**。Step 5 で Speaker のみ実装し Microphone は将来 Step 7 へ。

**Why:**

- 各方向で sample format / device 選択 / latency 要件が独立に進化する (Speaker は engine final mix、Microphone は user voice input + Opus encode で別系統)
- bidi-stream は client 実装複雑度が server-stream の数倍になり、片方しか使わないユースケースに過剰
- 将来 mic を実装しない選択肢を残せる
- proto level で `Audio` 共有 service を切ってしまうと、片方の breaking change で両方が影響を受ける

**How to apply:**

- 新規 modality も「双方向」と感じたら **方向別に分割**する選択肢を最初に検討 (例: 触覚なら Resonite → Python の haptic readback と Python → Resonite の force feedback を別 service に分けるか議論)
- 音声 message は generic な `AudioFrame` 命名にして将来 Microphone proto から import 再利用できる余地を残した (commit `ef3db96`)

______________________________________________________________________

## Speaker tap の実装パス (Step 5 確定事項)

**結論: `AudioOutputDriver.AudioFrameRendered(float[] buffer, double dspTime)` (protected) を HarmonyLib Postfix で patch する経路で完結する。Renderer plugin は不要**。

調査経路と落とし穴:

1. **`AudioOutputDriver.RenderAudio` プロパティ (Action?) には直接代入してはいけない** — get/set で `AudioSystem` が `defaultAudioOutput.RenderAudio = RenderAudio` と direct assign しているため、上書き subscribe すると engine が壊れる (event ではない)。`+=` 演算子でも内部的に getter 経由なのでセマンティクス曖昧。**HarmonyLib Postfix 一択**。

2. **`VideoTextureAudioWriter`/`Reader` ペアは video export 専用** — Cloudtoid.Interprocess queue ベースで一見 audio IPC に流用できそうだが、Unity 側で final mix を queue に接続している hook は無く、流用には Renderer plugin の新設が必要。**不採用** (Camera v2 の Renderer plugin と同等のコストを払うことになる)。

3. **対象 driver は `Engine.Current.AudioSystem.PrimaryOutput` のみ** — `StreamingOutput` (camera audio output) は無視。`PrimaryOutput` は base class `AudioDeviceOutput` 型なので Awwdio.dll を csproj から Reference 追加する必要がある (`Private=False` で同梱せず Resonite ランタイムから解決)。

4. **派生 type (`CSCoreAudioOutputDriver` / `SoundFlowAudioOutputDriver` 等) でも base method を patch すれば effective** — HarmonyLib は base method の patch を派生 instance にも適用する。原理上は OK だが JIT inlining / HarmonyX の virtual method 経路で稀に取り逃すので、初回 attach 時の log で必ず実機確認する。

5. **Postfix は static method 制約があるため `_singleton` static field 経由で対象 instance を判別**する — Postfix の signature は `void OnAudioFrameRenderedPostfix(AudioOutputDriver __instance, float[] buffer, double dspTime)` で `__instance` を見て `_singleton._targetDriver` と `ReferenceEquals` で照合。複数 instance 想定なら static dictionary が必要だが mod 全体で 1 bridge 前提なので不要。

6. **`DefaultAudioOutputChanged` event を subscribe して device swap に追従** — engine 起動時に `PrimaryOutput.Device` がまだ null の場合 (Linux + SoundFlow 経路で稀に発生)、event 経由で後追い attach する。即時 attach と event 追従の両経路を実装。

## WASAPI thread から push される hot path 設計

`AudioFrameRendered` は **WASAPI audio callback thread** から呼ばれる。Bridge 側の制約:

- **Channel write は thread-safe**: `System.Threading.Channels.Channel<T>` は producer/consumer 任意スレッドから安全 (Locomotion で `ExternalInput` への任意スレッド write 安全性と同じカテゴリ)
- **アロケーション最小化**: per-WASAPI-buffer で呼ばれるため (typical ~21ms 周期)、ここで GC heap を叩くと audio glitch の原因。`PushedAudioFrameSpeakerBridge.Push` は `ReadOnlySpan<float>` を受け、`byte[]` 1 個と `ByteString.CopyFrom` 1 回のみ
- **Channel 容量 32 frame で DropWrite** — 容量超過時は **新しい frame を捨てて古いを残す** (DropOldest ではなく DropWrite)。理由: 古い順を残す方が短期的な連続性 (短い glitch) を保ちやすい。実機検証で評価する余地は残すが初期実装は DropWrite 固定
- **frame_id は `Interlocked.Increment` で 0 から monotonic 採番**、stream 開始ごとに振り直し (Camera と揃え)

## SafeShutdown 順序

`ResoniteIOPlugin.SafeShutdown` の dispose chain は **Locomotion → Speaker → SessionBridge** の順:

- Locomotion を最初に止めて user input (ExternalInput) の継続注入を停止
- Speaker は WASAPI thread が in-flight 中の可能性があるため次 (Harmony unpatch + Channel complete で in-flight Postfix は早期 return する)
- SessionBridge は engine bridging の最後 (gRPC server 自体を止めるのは別 dispose chain なので、本順序は engine 側 bridges の解除順)

## 関連

- proto: [proto/resonite_io/v1/speaker.proto](proto/resonite_io/v1/speaker.proto)
- Core: [mod/src/ResoniteIO.Core/Speaker/](mod/src/ResoniteIO.Core/Speaker/)
- Mod: [mod/src/ResoniteIO/Bridge/FrooxEngineSpeakerBridge.cs](mod/src/ResoniteIO/Bridge/FrooxEngineSpeakerBridge.cs)
- Python: [python/src/resoio/speaker.py](python/src/resoio/speaker.py), [python/src/resoio/cli/record.py](python/src/resoio/cli/record.py)
- 関連 memory: \[\[bridge-iface-uses-core-poco\]\] (Bridge IF が Core POCO `AudioFrame` を返す設計の根拠)
- decompile: [decompiled/FrooxEngine/FrooxEngine/AudioOutputDriver.cs](decompiled/FrooxEngine/FrooxEngine/AudioOutputDriver.cs), [decompiled/FrooxEngine/FrooxEngine/AudioSystem.cs](decompiled/FrooxEngine/FrooxEngine/AudioSystem.cs)
