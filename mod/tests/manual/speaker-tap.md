# Speaker tap (FrooxEngineSpeakerBridge) 検証

`FrooxEngineSpeakerBridge` が engine 側 `AudioOutputDriver.AudioFrameRendered`
を HarmonyLib Postfix で tap し、WASAPI final mix を Python `SpeakerClient` /
`resoio record` 経由で取り出せることを実機で確認する手動検証手順。

実装計画上の対応:

- [resonite_io_plan.md](../../../resonite_io_plan.md) Step 5 (Speaker) の
  「実機で `resoio record` を起動 → 何らかの音 (BGM, UI sound) を鳴らして
  frame 受信を確認する」相当
- 自動化できない: WASAPI audio thread と FrooxEngine の `AudioSystem` 全体が
  立ち上がる必要があるため、`ResoniteIO.Tests` での単体 test 対象外

## 前提

- [load-verification.md](load-verification.md) の前提条件すべて
- Gale プロファイルに必須 6 plugin install 済み (`just check-gale` 全 ✓)
- Steam Launch Options に `WINEDLLOVERRIDES="winhttp=n,b" %command%`
- host で `just host-agent` daemon が GUI session の端末で起動している
  (`DISPLAY` / `WAYLAND_DISPLAY` 必須)
- container 内で `cd python && uv sync` 済み
- **Resonite が音を再生できるデスクトップ環境** (HMD 不要、デスクトップ起動可、
  ホストの audio output device が利用可能)

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
[Info   :ResoniteIO] Speaker Bridge: attached to AudioOutputDriver '<デバイス名>' (device='<id>', sampleRate=48000)
[Info   :ResoniteIO] Speaker Bridge: HarmonyLib Postfix attached to AudioOutputDriver.AudioFrameRendered
[Info   :ResoniteIO] SessionHost listening on /home/<user>/.resonite-io/resonite-<pid>.sock
```

`attached to AudioOutputDriver '...'` の行が出れば WASAPI driver が
`PrimaryOutput.Device` として既に登録されており tap target が定まっている。
`HarmonyLib Postfix attached` で実 patch が刺さった。

`PrimaryOutput.Device not ready at construction; deferring until DefaultAudioOutputChanged fires.` が出ている場合は audio device の初期化が
mod ロード時点で未完。Resonite のユーザー設定で audio output device を
切り替える (Settings → Audio Output) と `DefaultAudioOutputChanged` が
発火して以下が出るはず:

```text
[Info   :ResoniteIO] Speaker Bridge: re-attached to AudioOutputDriver '<新デバイス名>' (device='<id>')
```

## CLI 録音検証 (Wave 2 Stream D 完了後)

Wave 2 Stream D で `resoio record` CLI が landed したあとに、container 内
shell から:

```sh
# 5 秒録音して WAV ファイル化
uv run --project python resoio record -o /tmp/test.wav --duration 5

# 出力検証 (host 共有の /tmp/test.wav を host で読むか、container に ffprobe があれば container で)
ffprobe -hide_banner /tmp/test.wav
```

`ffprobe` 出力に以下が含まれることを確認:

```text
Stream #0:0: Audio: pcm_f32le, 48000 Hz, stereo, flt, 3072 kb/s
Duration: 00:00:05.0?, ...
```

判定基準:

- `pcm_f32le` (32-bit IEEE float LE) — 固定 format 通り
- `48000 Hz` — proto コメントの 48 kHz 通り
- `stereo` — `AudioFrame.ChannelCount = 2`
- Duration が ~5 秒 (誤差 ±0.2 秒は許容、WASAPI buffer の最後の chunk 取り回し誤差)
- ファイルサイズ ≒ 5 * 48000 * 2 * 4 = 1,920,000 bytes + 44 byte header

stdout pipe 経路:

```sh
uv run --project python resoio record -o - --duration 3 \
  | ffmpeg -hide_banner -loglevel error -y \
      -f f32le -ar 48000 -ac 2 -i - -t 3 /tmp/test.flac
ffprobe -hide_banner /tmp/test.flac
```

flac 側で stereo 48 kHz / Duration ~3 sec が確認できれば pipe 経路も通っている。

## 音が実際に録れていることの最終確認

Resonite で何らかの音 (UI クリック音、avatar BGM、world ambient) を鳴らした
うえで上の録音手順を実施し、生成された WAV / FLAC を host のメディア
プレイヤー (VLC / mpv / Resonite を流していたスピーカで再生) で再生して
**録音内容が Resonite の出力と一致** することを耳で確認する。

無音録音が出ている (`ffprobe` 上の format は正しいが波形が flat) 場合は:

1. Resonite 側 master volume が 0 ではないか確認 (engine の `IsMuted` プロパティ)
2. `PrimaryOutput.Volume` が 0 にセットされていないか確認 (decompile:
   `AudioSystem.OnAccessibilityChanged` で `_volumeSetting.ActualMasterVolume`
   が掛かる)
3. `just log` で `Speaker Bridge: re-attached` 行が出続けていないか
   (頻繁に device が切り替わると tap が遅延する可能性)

## 想定される失敗モードと診断

### `Speaker Bridge: AudioOutputDriver.AudioFrameRendered method not found`

HarmonyLib が target method を取得できなかった (decompile 時点と signature が
変わっている可能性)。Resonite のバージョンを確認し、必要なら
[AudioOutputDriver.cs](../../../decompiled/FrooxEngine/FrooxEngine/AudioOutputDriver.cs)
を再生成して signature `(float[], double)` のままか確認する。

### `Speaker Bridge: failed to apply Harmony patch: ...`

Harmony が他 mod と衝突しているか、JIT 制約に当たっている可能性。BepInEx
内に他の `0Harmony.dll` がロードされていないか確認 (Gale 同梱のが正)。
Resonite 再起動でしばしば解消する。

### `Speaker Bridge: PrimaryOutput.Device not ready at construction` のあと

無音

audio device 初期化に時間がかかるケース。Resonite Settings → Audio Output で
device を一度切り替えるか、`SpeakerService.StreamAudio` を retry すれば
`DefaultAudioOutputChanged` 経路で attach 完了する。

### gRPC client 側で stream が yield しないが engine log は正常

`SessionHost listening` までは出ているが `resoio record` が frame を受け
取れない場合:

1. `ls -la /home/$USER/.resonite-io/` で socket file 存在確認
2. `RESONITE_IO_SOCKET_DIR` を container 内 client が見れているか
   (container は `$HOME/.resonite-io` を host から bind 済み、CLAUDE.md
   §「実行環境の注意点」)
3. `python -c "import resoio; print(resoio.__version__)"` で client 側が
   resoio (本ブランチで生成) を見ているか確認

## クリーンアップ

```sh
just resonite-stop             # container → host bridge 経由で Resonite を SIGTERM
```

`just log` で以下の dispose 順 log が出ることを確認:

```text
[Info   :ResoniteIO] Speaker Bridge disposed: harmony unpatched, channel completed
```

UnpatchSelf で patch が外れているので、Resonite 内に残った engine 経路には
副作用が残らない (Gale 経由再起動で完全に元状態)。
