# Microphone (FrooxEngineMicrophoneBridge) 検証

`FrooxEngineMicrophoneBridge` が `FrooxEngine.AudioInput` 派生 virtual
device を `AudioSystem.RegisterAudioInput` で登録し、Python 側
`MicrophoneClient` / `resoio mic` から音声を流し込めることを実機で確認する
手動検証手順。

実装計画上の対応:

- [resonite_io_plan.md](../../../resonite_io_plan.md) Step 7 (Microphone) の
  「Resonite に入って virtual mic を default に切替 → Python から WAV
  / 正弦波を流して voice として聞こえるか確認する」相当
- 自動化できない: Resonite ローカル UI 操作 (Audio Input device 切替) と、
  他ユーザーで voice として聞こえることの耳確認が必要なため
- [.claude/memory/feedback_microphone_engine_tap.md](../../../.claude/memory/feedback_microphone_engine_tap.md)
  に音声経路の確定事項を集約

## 前提

- [load-verification.md](load-verification.md) の前提条件すべて
- Gale プロファイルに必須 6 plugin install 済み (`just check-gale` 全 ✓)
- Steam Launch Options に `WINEDLLOVERRIDES="winhttp=n,b" %command%`
- host で `just host-agent` daemon が GUI session の端末で起動している
  (`DISPLAY` / `WAYLAND_DISPLAY` 必須)
- container 内で `cd python && uv sync` 済み
- **voice 配信確認用に Resonite アカウント 2 つ** (本人 + リスナー) を用意する
  か、本人の avatar microphone settings で self-monitor を有効化する経路を
  使う。完全ソロ確認なら mic mute/unmute トグルで自分の波形可視化機能 (もしあれば)
  を使うのも代替

## 手順

container 内 shell から:

```sh
just deploy-mod                # build + plugin deploy
just resonite-start            # host 経由で Gale → Resonite 起動
```

別ターミナル (container or host) で:

```sh
just log                       # tail -F BepInEx LogOutput
```

engine 側 log に以下が時系列で出ることを確認:

```text
[Info   :ResoniteIO] Engine ready — starting Session gRPC host
[Info   :ResoniteIO] Microphone Bridge: registered virtual AudioInput 'ResoniteIOMicrophone' (id=resoio-mic-virtual, sampleRate=48000)
[Info   :ResoniteIO] SessionHost listening on /home/<user>/.resonite-io/resonite-<pid>.sock
```

(log 文言は実装による微差あり。要点は **registered virtual AudioInput** の
行が出ること。)

Resonite GUI で:

1. ESC → Settings → **Audio Input** タブを開く
2. ドロップダウンに **ResoniteIOMicrophone** が出ていることを確認 (isDefault=false
   で登録しているので automatic 選択はされない)
3. 選択して反映 (apply)

`just log` に以下が出るか観察 (engine 側 device 切替経路):

```text
[Info   :ResoniteIO] Microphone Bridge: device selected as default by Resonite UI
```

(同 log は engine 側 event 経路に依存するため出ないこともある。
出ない場合は `_audioInputDeviceIDs` の昇格を engine 側 log で確認する。)

## CLI 送信検証

container 内 shell から fixture 正弦波を送信:

```sh
# Phase 6 で commit 済みの 440 Hz / 48 kHz / mono / float32 / 5 秒 WAV を送信
uv run --project python resoio mic \
  -i python/tests/e2e/fixtures/sine_440hz_5s_mono_48k.wav
```

CLI stderr 最後の行に summary が出ることを確認:

```text
received_frames=234 received_samples=239616 dropped_frames=0 unix_nanos=<...>
```

判定基準:

- exit code 0
- `received_frames` が WAV 長から chunk size 1024 で割り切った値 (5 秒 = 234
  chunks、余り 384 samples は CLI 側で drop)
- `dropped_frames=0` (Bridge ring buffer がオーバーフローしていない)

stdin pipe 経路:

```sh
cat python/tests/e2e/fixtures/sine_440hz_5s_mono_48k.wav \
  | uv run --project python resoio mic -i -
```

WAV header 込みでも CLI は WAV/stdin 自動判別はせず、`-i -` は **raw float32
LE mono PCM** 想定なので、上記のように WAV header 付きで流すと header の
44 byte が pcm として解釈され冒頭にゴミ samples が混入する。ffmpeg で
header strip して流すなら:

```sh
ffmpeg -hide_banner -loglevel error \
  -i python/tests/e2e/fixtures/sine_440hz_5s_mono_48k.wav \
  -f f32le -ac 1 -ar 48000 - \
  | uv run --project python resoio mic -i -
```

## 音が実際に届いていることの最終確認

リスナーアカウント側で確認:

1. 同じ world にリスナー avatar をジョインさせる
2. 本人 (mod を載せている側) で `resoio mic -i ...` を実行
3. リスナーの耳元で **440 Hz の正弦波音** が聞こえる
4. リスナー側で voice volume meter (Resonite UI) が振れる

代替手段: Resonite の **音声録音 tool (MicrophoneTool)** を本人 avatar で
持ち、`AudioInput` の output を録音する。録音された WAV をホスト側で再生
して正弦波が入っているか耳確認。

無音 (CLI summary は正常だが voice が届かない) の場合の診断:

1. Resonite Settings → Audio Input が **ResoniteIOMicrophone に選択された
   ままか** 再確認 (world join 等で reset される可能性)
2. avatar の voice mute (自分の側で push-to-talk が要求されている等) を確認
3. `LocalForceMute` が engine 側で立っていないか確認:
   - RecordingVoiceMessage 中
   - World focus が外れている
4. `just log` で `Microphone Bridge: dropped N samples (ring buffer overflow)` が出ていないか確認 (engine tick が drain しきれていない =
   送信ペースが速すぎる、現状 1024 samples 送信ペースで起きないはず)

## 想定される失敗モードと診断

### `Microphone Bridge: AudioSystem.RegisterAudioInput failed: ...`

`Engine.Current.AudioSystem` が初期化されていない (engine ready 前) か、
`AudioInput` ctor signature が decompile 時点と変わっている可能性。Resonite
のバージョンを確認し、必要なら
[AudioInput.cs](../../../decompiled/FrooxEngine/FrooxEngine/AudioInput.cs) を
再生成して 5 引数 `(name, deviceId, InputInterface, AudioInputType, bool)`
のままか確認する。

### `Microphone Bridge: WriteSamples threw ...`

`MonoSample` 型解決失敗 ( `Elements.Assets.dll` reference が外れた)、または
WriteSamples の generic constraint 違反。csproj の `<Reference Include="Elements.Assets">` と `MemoryMarshal.Cast<float, MonoSample>` 経路
を確認。

### CLI: `bridge ready check failed (FAILED_PRECONDITION): ...`

`MicrophoneBridge` がまだ engine ready 前、または default focus world が
未確定。Resonite GUI が空 world に居る間は engine update tick が一部止まる
ことがあるので、いずれかの world (Userspace / Home World) に居る状態で
再送信する。

### Resonite 再起動後に `UniLog.Warning: AudioInput with ID 'resoio-mic-virtual' already registered`

`AudioSystem.UnregisterAudioInput` API が engine 側に存在しないため、
`AudioSystem._audioInputDeviceIDs` (private HashSet) に device ID が残留する
仕様。**機能影響なし**。Resonite を完全再起動すれば clear される。
詳細: [feedback_microphone_engine_tap.md](../../../.claude/memory/feedback_microphone_engine_tap.md)

### `Microphone Bridge: tick repeater stopped unexpectedly`

`World.RunInUpdates(0, TickStep)` の self-rescheduling が `_disposed=true`
で停止していないのに log が出る場合、world switch 中の transient な
boundWorld mismatch。次の `WorldFocused` event で再起動するため通常は
無視可。

## クリーンアップ

```sh
just resonite-stop             # container → host bridge 経由で Resonite を SIGTERM
```

`just log` で以下の dispose 順 log が出ることを確認:

```text
[Info   :ResoniteIO] Microphone Bridge disposed: tick repeater stopped, AudioInputs.Remove best-effort done
```

`_audioInputDeviceIDs` の残留は上記 trade-off の通り。Resonite 完全再起動で
clear される (`AppDomain.ProcessExit` でプロセス自体が落ちるため次回 launch
時は new engine instance)。
