---
name: microphone-engine-tap
description: Microphone (Python → Resonite) は FrooxEngine.AudioInput 派生クラスを AudioSystem.RegisterAudioInput で登録する経路で完結する。Resonite UI で virtual device を default mic に選択すれば voice broadcast まで engine 側で自動。Opus encode は engine 側自動 (Bridge 不要)。
metadata:
  type: feedback
---

Microphone modality (Python → Resonite) は **`FrooxEngine.AudioInput` 派生クラスを `AudioSystem.RegisterAudioInput` で登録する経路で完結する**。Renderer plugin / Opus encoder の自前実装は **不要**。Resonite 側の voice broadcast 経路 (`UserAudioStream<MonoSample>` → `OpusStream<MonoSample>`) が自動で他ユーザーへ配信する。

**Why:**

- Speaker (Resonite → Python) は Engine が既に呼ぶ `AudioOutputDriver.AudioFrameRendered` を Postfix で受身的に tap できたが、Microphone は逆方向 = engine に push する側のため Postfix tap では駆動 timing を制御できない (decompile `CSCoreAudioInputDriver.Capture_DataAvailable` 経路を見て確認、\[\[speaker-engine-tap\]\] と非対称)
- `AudioInput` 派生 + `RegisterAudioInput` は Resonite native の正規 API で、CSCore / SoundFlow / SteamVoice driver が同じパターンを採用している (decompile 3 ファイル横断確認)
- `UserAudioStream<MonoSample>` が `AudioSystem.AudioInputs[DefaultAudioInputIndex].NewFilteredSamples` を subscribe しており、virtual device を default に設定すれば voice として broadcast されることが decompile で保証されている

**How to apply:**

- 新規 modality で「engine が定期 callback してくれない方向 (= push 方向)」を扱うときは、engine の **正規 device 登録 API** (RegisterX 系) を最初に探す。Postfix は engine 側が既に呼ぶ method の wrap であり、push 方向には向かない
- Speaker / Microphone 実装パターンの差は \[\[speaker-engine-tap\]\] と本ファイルを並読すること

______________________________________________________________________

## Microphone tap の実装パス (Step 7 確定事項)

**結論: `AudioInput` 派生 + `AudioSystem.RegisterAudioInput` + `WriteSamples<MonoSample>(Span<MonoSample>, ref double position, ref MonoSample lastSample)` 経由で push**。

調査経路と落とし穴:

1. **`AudioInput` ctor は 5 引数**: `name`, `deviceId`, `InputInterface`, `AudioInputType.CaptureDevice`, `bool isDefault`。decompile `FrooxEngine.AudioInput.cs` で signature 確定。`isDefault=true` にすると登録時に default mic を上書きしてしまうため **`isDefault: false`** で登録し、Resonite UI (Settings → Audio Input) で手動切替させる方針が安全。

2. **`AudioSystem.RegisterAudioInput` は存在するが `UnregisterAudioInput` は存在しない**: decompile `FrooxEngine.AudioSystem.cs` を確認すると `AudioInputs` は `List<AudioInput>` (public、line 177)、`_audioInputDeviceIDs` は private `HashSet<string>`。**Dispose 経路は `AudioInputs.Remove(audioInput)` の best-effort のみ**で、`_audioInputDeviceIDs` には device ID が残留する。mod re-load 時に `UniLog.Warning("AudioInput with ID '...' already registered")` が 1 行出るが機能影響なし。

3. **format は固定: 48 kHz / Mono / float32 LE**: `Engine.AudioSystem.SampleRate` (decompile 確認、48000 Hz hard-coded) と一致させれば AudioInput 内の resample コードパスは 1:1 で抜ける (厳密には `S != StereoSample` の場合 `CopySamples<MonoSample, StereoSample>` が呼ばれるが `invResampleRate=1f` で実質コピー)。**Stereo 入力にしない理由**: voice broadcast 経路 `UserAudioStream<MonoSample>` は mono 専用 (decompile `CommonAvatarBuilder.cs:1762`)。Stereo にすると engine 内で down-mix される無駄が発生。

4. **`MonoSample` 型は `Elements.Assets.dll` にある**: `Elements.Core.dll` ではない。csproj に `<Reference Include="Elements.Assets">` + `<HintPath>$(ResonitePath)/Elements.Assets.dll</HintPath>` + `<Private>false</Private>` を追加する必要がある。`Span<float>` → `Span<MonoSample>` は `MemoryMarshal.Cast<float, MonoSample>(span)` で zero-copy reinterpret (`MonoSample` は `[StructLayout(LayoutKind.Sequential)] struct { readonly float Value }` で float 1 個分の memory layout が一致するため安全、decompile `Elements.Assets/MonoSample.cs` で確認)。

5. **`WriteSamples<S>` の generic constraint は `where S : unmanaged, IAudioSample<S>`**: `float[]` のまま渡せない。**`MonoSample` を経由する必要**。

6. **engine thread dispatch は必須**: `WriteSamples` 自体は `AudioInput` 内部の lock で thread-safe だが、`_position` / `_lastSample` の interpolation state を保持するため engine update thread で呼ぶのが正しい。**Locomotion pattern (`World.RunInUpdates(0, TickStep)` self-rescheduling repeater)** をそのまま流用 (\[\[locomotion-external-input\]\] と同じ書き方)。任意スレッドから push できる ring buffer を間に挟み、tick が drain する設計に倒した。

7. **HarmonyLib は不要**: Postfix patch は使わない。virtual device を **登録** すれば engine が `WriteSamples` を呼ぶサイドではなく、Mod 側 (Bridge) が能動的に `WriteSamples` を呼ぶ。Speaker と非対称。

8. **`DefaultAudioInput` 昇格は Resonite UI 操作に委ねる**: 起動時に自動的に default 化すると user の既存 mic 設定 (Razer SoundBlaster 等の物理 mic 選択) を壊す。Settings → Audio Input → "ResoniteIOMicrophone" を手動選択する手順を `mod/tests/manual/microphone-verification.md` に記録。Python 側から default 切替する RPC は **意図的に持たない** (Resonite native の audio device 制御を侵食しない方針)。

## Python push pace 設計

`MicrophoneClient.stream()` の caller (CLI mic.py) は **任意ペースで chunk を送れる**:

- Bridge 側 ring buffer は **2 秒分 (96,000 samples)** で overflow 時は古いものから drop (`_droppedSamples` カウントだけ、proto `dropped_frames` には未反映 = Phase 7 以降の hook)
- engine tick は 60〜200 Hz で `TickStep` を回し、tick あたり最大 **10 ms (480 samples)** を drain
- CLI は 1024 samples (≒ 21.3 ms) 単位で送るので「engine tick の drain ペース ≒ CLI 送信ペース」となる定常状態に落ち着く
- network burst で短時間に大量送信されても 2 秒分は緩衝、それ以上は drop で過去音を捨てる (RL/ロボティクス safety: latency 優先、データ完全性は劣後)

## SafeShutdown 順序

`ResoniteIOPlugin.SafeShutdown` の dispose chain は **receiver → camera → display → locomotion → microphone → speaker → sessionBridge** の順:

- Locomotion → Microphone の順は両方 engine state を mutate する系だが、Locomotion の ExternalInput reset を先に流して user input 経路を止めてから Microphone (audio input) を解除
- Microphone → Speaker の順は、Microphone (engine 側に push) を先に解除して engine update tick の repeater を止めてから、Speaker (Harmony unpatch) を解除する流れ
- Microphone Dispose は `AudioInputs.Remove` + ring buffer reset + repeater 停止 (Locomotion 同様 `_disposed` flag で next TickStep が自然終了)

## 関連

- proto: [proto/resonite_io/v1/microphone.proto](../../proto/resonite_io/v1/microphone.proto)
- Core: [mod/src/ResoniteIO.Core/Microphone/](../../mod/src/ResoniteIO.Core/Microphone/)
- Mod: [mod/src/ResoniteIO/Bridge/FrooxEngineMicrophoneBridge.cs](../../mod/src/ResoniteIO/Bridge/FrooxEngineMicrophoneBridge.cs)
- Python: [python/src/resoio/microphone.py](../../python/src/resoio/microphone.py), [python/src/resoio/cli/mic.py](../../python/src/resoio/cli/mic.py)
- 関連 memory: \[\[speaker-engine-tap\]\] (Speaker と非対称な理由、\[\[locomotion-external-input\]\] (engine thread dispatch pattern), \[\[core-mod-layering\]\] (Core/Mod 分離)
- decompile: [decompiled/FrooxEngine/FrooxEngine/AudioInput.cs](../../decompiled/FrooxEngine/FrooxEngine/AudioInput.cs), [decompiled/FrooxEngine/FrooxEngine/AudioSystem.cs](../../decompiled/FrooxEngine/FrooxEngine/AudioSystem.cs), [decompiled/FrooxEngine/FrooxEngine/UserAudioStream.cs](../../decompiled/FrooxEngine/FrooxEngine/UserAudioStream.cs), [decompiled/Elements.Assets/Elements.Assets/MonoSample.cs](../../decompiled/Elements.Assets/Elements.Assets/MonoSample.cs)
