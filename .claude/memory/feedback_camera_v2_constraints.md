---
name: camera-v2-constraints
description: Camera v2 (Renderite framebuffer 直取り) の確定アーキ・Wine sandbox 制約・InterprocessLib / OverlayCamera / Settings API の落とし穴を 1 本に集約
metadata:
  type: feedback
---

Camera v2 (`Renderite.Renderer.exe` の framebuffer を **OverlayCamera +
CommandBuffer + AsyncGPUReadback** で取り出し InterprocessLib 共有メモリ queue
経由で engine 側 Mod に流す経路) の確定知見を 1 本にまとめる。v1
(`Camera.RenderToBitmap` 経由、30fps 固定) は HEAD `ff44bf8` で削除済み。

agent-memory (`spec-driven-implementer/feedback_*.md`) には実装フェーズで
個別に判明した低レイヤの fact を残してあり、本 memo は **その上に立つ
project-wide overview**: 「v2 経路を追加 / 改修するときに最初に読む 1 本」
として機能させる目的。詳細は本文中の `[[<name>]]` リンク先を見ること。

## 1. 確定アーキ

```text
Python (host or container)
  CameraClient ──▶ UDS (~/.resonite-io/resonite-<pid>.sock)
                    │ gRPC
                    ▼
              ResoniteIO.dll (engine 側 Mod、Linux .NET 10、BepInEx 6)
                CameraService.StreamFrames
                  └─◀ PushedFrameCameraBridge.CaptureAsync
                        │ Channel<CameraFrame>(capacity=1, DropOldest)
                        ▲
                        │ Push()
                        ▼
                RendererFrameInterprocessReceiver
                  Messenger (isAuthority=true, owner=net.mlshukai.resonite-io.camera,
                             queue=resonite-io-camera-frames, capacity=32 MiB)
                    ▲
                    │ InterprocessLib (Cloudtoid 共有メモリ queue)
                    ▼
              ResoniteIO.Renderer.dll (renderer 側 plugin、Wine + Unity Mono、BepInEx 5)
                FrameSender.Send(FrameHeader + RGBA bytes)
                  ▲
                  │ AsyncGPUReadback.Request(RT, RGBA32, OnReadback)
                  │
                FrameCapture
                  CommandBuffer.Blit(BuiltinRenderTextureType.CurrentActive, RT)
                  @ OverlayCamera (max depth=50, targetTexture=null)
                  @ CameraEvent.AfterEverything
```

engine 側 csproj (`ResoniteIO.csproj`) と renderer 側 csproj
(`ResoniteIO.Renderer.csproj`) が `ResoniteIO.RendererShared` (netstandard2.0、
依存ゼロ + `System.Memory` polyfill) を共有して `FrameHeader` (40 bytes LE
binary) と `IpcSocketPaths` 定数を bit-exact に揃える。

**How to apply:** Camera v2 周辺をいじるときは「engine ↔ renderer ↔ Python
の 3 段すべてで同じ概念モデルが成立しているか」を本図で照合する。新規
モダリティ (Audio / Locomotion / Manipulation) で renderer process 側に
触れる必要が出たら同じ pipeline (RendererShared + InterprocessLib +
BepInEx 5 plugin) を再利用する。

## 2. Wine sandbox 内 Mono の socket 制約

Renderer プロセスは Wine 内で動くため:

- **AF_UNIX socket は不可** — `AddressFamilyNotSupported (NativeError 10047)`。
  UDS 経由で renderer ↔ engine を直結する案は捨てる
- **TCP loopback は可** だが今回は採用しない。InterprocessLib (Cloudtoid
  共有メモリ queue) の方が latency 低 + Resonite ecosystem (Renderite
  本体が既に Cloudtoid を使う) との整合が良い
- `$HOME` 配下のパスは pressure-vessel sandbox を通る、
  `$XDG_RUNTIME_DIR` (`/run/user/<uid>`) は通らない
  (\[\[pressure-vessel-paths\]\])

**Why:** Wine Mono の `Socket(AF_UNIX, ...)` は実装が無く throw する。Wine
WineHQ の roadmap でも対応予定なし。pressure-vessel の filesystem 共有経路
は別 reference `reference_pressure_vessel_paths.md` を参照。

**How to apply:** renderer プロセスから engine 側に何か送る経路を
新規追加する場合、まず Wine 制約に当たる前提で InterprocessLib (またはそれと
等価な共有メモリ機構) を第一選択にする。UDS / domain socket 系の API を見たら
ためらわず除外する。

## 3. Steam Launch Options が WINEDLLOVERRIDES の唯一の経路

Renderer 側 BepInEx (BepInExRenderer 5.4+) を起動させる doorstop hook 版
`winhttp.dll` を Wine に load させるには:

```text
WINEDLLOVERRIDES="winhttp=n,b" %command%
```

を Steam で Resonite を選択 → Properties → Launch Options に **設定する以外の
経路は無い**。

- `host_agent.py` から env 経由で渡しても **Steam が sanitize する** ため
  通らない (実証済み)
- `/proc/<pid>/environ` で確認しても env に乗らないため debug 困難。root
  cause が "Launch Options が空" だと気付くまでに時間がかかる
- Wine は system 同梱の `winhttp.dll` を優先する仕様。override しない限り
  RenderiteHook が deploy した hook 版が読まれず、renderer 側 BepInEx が
  永遠に起動せず Camera v2 全体が silent fail する

**Why:** Steam の sanitize policy は env を proton-fixed のものに上書き
するため。Launch Options だけが Steam → Proton → Wine への明示的な
DLL override 引数として通る。

**How to apply:**

- README / CLAUDE.md / `just init` の手順表示で **Launch Options 必須** を
  人間に伝える (commit `cf05254` で実施済み)
- Renderer 側 BepInEx ログ (`gale/Renderer/BepInEx/LogOutput.log`) が空 /
  生成されない症状を見たら 99% Launch Options を疑う
- `mod/tests/manual/renderer-plugin-load.md` のトラブルシュートが正式 reference

## 4. `IDisplayTextureSource.UnityTexture` は外部 desktop 取り込み用 (誤解しない)

Renderite に `IDisplayTextureSource` 系の API があり `UnityTexture` プロパティが
ある (`Display.TryGetDisplayTexture(0)`) が、**これは uDesktopDuplication
経由の外部 desktop 取り込み用**で Renderite 自身の screen 出力では無い。

- Wine では uDesktopDuplication が動かず、`UnityTexture` は **常に null**
- Renderite 自身の screen 出力は `CameraManager.cs` で別 path: `ScreenCamera`
  (depth=0) と `OverlayCamera` (depth=50) が screen 直描画する
- 同一の誤解で 4 時間消費した実績あり (knowledge §3.4 / §5)

**Why:** API 名 (`DisplayTexture`) から「window framebuffer の texture」と
誤解しがちだが、実体は **外部 monitor の uDD capture target**。Resonite が
WhiteRabbit 等の外部 desktop を取り込んで world 内に表示する機能の裏側。

**How to apply:** Renderite 側で screen capture が要るときは **必ず
`CommandBuffer.Blit(BuiltinRenderTextureType.CurrentActive, RT)` 経由**で
攻める。`IDisplayTextureSource` / `Display.TryGetDisplayTexture` には行か
ない。

## 5. OverlayCamera 選択 (max depth, targetTexture=null)

Renderer process には screen 直描画する camera が複数あり、capture すべきは
**最後に描画される = max depth の camera**:

- `ScreenCamera` (depth=0) — メインシーン
- `OverlayCamera` (depth=50) — UI / overlay (最後に描画される、UI 含む
  final framebuffer)

選択条件 (`FrameCapture.EnsureCommandBufferAttached`):

```csharp
foreach (var cam in Camera.allCameras) {
    if (!cam.enabled) continue;
    if (cam.targetTexture != null) continue;  // off-screen camera は除外
    if (cam.depth > maxDepth) { maxDepth = cam.depth; target = cam; }
}
```

`CameraEvent.AfterEverything` で `Blit(CurrentActive, RT)` を入れて
post-rendering の framebuffer を中間 RenderTexture (RGBA32) にコピーする。

**Why:** `CameraRenderable` (Renderite の通常 camera 描画 path) は
`camera.enabled = camera.targetTexture != null && update.enabled`
(`CameraManager.cs:105`) のため **off-screen 専用**。screen 直描画 camera
は別 path で動き、`targetTexture==null` でフィルタする必要がある。

**How to apply:** Renderite が major version up して camera depth が変わったら
本ロジックも追従する。E1 観測値 = `name=OverlayCamera depth=50 size=1118x651`。

## 6. InterprocessLib (Nytra) の constraint 集

- **namespace は `InterprocessLib`** — DLL 名 `InterprocessLib.FrooxEngine.dll`
  (engine 側) / `InterprocessLib.Unity.dll` (renderer 側) と異なる。`using InterprocessLib;` で `Messenger` 型を参照する
- `Messenger.ReceiveValueArray<byte>` の callback は
  **`Action<byte[]?>`** (fresh allocate、nullable)。`byte[]` で受けると
  CS8622 で TreatWarningsAsErrors が蹴る。詳細は
  \[\[interprocesslib-callback-signature\]\] (agent-memory)
- **`queueCapacity: 32 MiB`** が必須 — default 1 MiB だと RGBA8 frame
  (1118×651 ≒ 2.9 MiB) が乗らない。定数 `IpcSocketPaths.QueueCapacityBytes`
  で engine / renderer 両側を bit-exact に揃える
- engine 側は **`isAuthority=true`** で先に queue を作る。renderer は
  `isAuthority=false` で attach する側 (Resonite engine は renderer process
  より先に起動する保証あり)
- **`Messenger.OnFailure` / `OnWarning` / `OnDebug` / `OnShutdown` は static
  event** → 必ず Dispose で `-=` する。subscribe しっぱなしだと
  `Messenger` インスタンスが GC されずメモリリーク

**Why:** Cloudtoid (=InterprocessLib の内部実装) は shared memory ring queue
を使うので、両側で queue 名 / owner / capacity が完全一致しないと silent
failure する (renderer が send しても engine が受け取れない、ログにも出
にくい)。`Messenger` の static event 設計は cross-process broker 用途で本来
妥当だが、subscribe leak は分かりにくい。

**How to apply:** 新規 message id を加える時は `IpcSocketPaths` に const を
増やすだけで両側が同期する。`Messenger` を構築する全クラスで
subscribe/Dispose を必ず対で書く (\[\[interprocesslib-callback-signature\]\] 参照)。

## 7. AsyncGPUReadback の drop-on-busy

`FrameCapture.TryCapture` に `_inFlight` flag を入れて、前回 readback が
完了していなければ次フレームは **黙って捨てる**:

```csharp
public void TryCapture() {
    EnsureCommandBufferAttached();
    if (_captureRT == null) return;
    if (_inFlight) return;                 // ◀── drop-on-busy
    _inFlight = true;
    AsyncGPUReadback.Request(_captureRT, 0, TextureFormat.RGBA32, OnReadback);
}
```

`OnReadback` の `finally` で `_inFlight = false` に戻す。

**Why:** AsyncGPUReadback はバックグラウンドで GPU pipeline と非同期に走り、
readback request が滞留すると Unity 内部 queue が膨らんで OOM / 描画詰まり
を起こす。前段 producer (Unity rendering) が consumer (engine 側 Channel) と
fps mismatch するときも latest-wins で破綻させない方針。engine 側
`PushedFrameCameraBridge` も `Channel.CreateBounded(1, DropOldest)` で
2 段目 latest-wins を効かせている (drop 2 段構え)。

**How to apply:** GPU readback / IPC が絡む producer-consumer は **必ず 2
段の latest-wins**: (a) producer 側 drop-on-busy (b) consumer 側 bounded
channel + DropOldest。再現性確認は xunit で
`PushedFrameCameraBridgeTests` の `Push_twice_then_capture_returns_latest`
が代表。

## 8. graphicsUVStartsAtTop=True (Direct3D11 in Wine)

Wine の D3D11 backend では Unity の `SystemInfo.graphicsUVStartsAtTop`
が **True** を返す → renderer 側 RGBA bytes は既に top-left origin で、
**Y flip は不要**。

- OpenGL backend (`Application.targetFrameRate=-1` 系で稀に有効) では
  False になる可能性。その場合は renderer 側で row reverse copy が
  必要 (1118×651 で約 0.5ms)
- E1 (2026-05-18) は D3D11 (Steam Proton default) で実機検証、Y flip 不要を
  確認

**Why:** Vulkan / Metal / OpenGL は通常 bottom-left origin、D3D11 は
top-left origin で Unity がプラットフォーム別に flip 補正する。Resonite は
proto `CameraFrame` で **常に top-left origin** (row 0 = 画像上端、
`camera.proto` に明記) という契約なので、Y flip が必要かどうかは
graphics API 依存。

**How to apply:** OpenGL backend で実機検証する PR が来たら、renderer
`FrameCapture.OnReadback` に `if (!SystemInfo.graphicsUVStartsAtTop) { row reverse... }` を入れる。default は D3D11 = no-flip。

## 9. FrooxEngine Settings API は static class

`DesktopRenderSettings` / `ResolutionSettings` 等の `SettingComponent<T>` に
アクセスする canonical API は **静的 `FrooxEngine.Settings`** クラス:

```csharp
T? Settings.GetActiveSetting<T>() where T : SettingComponent<T>, new()
bool Settings.UpdateActiveSetting<T>(Action<T> update) where T : SettingComponent<T>, new()
```

- `Engine.Current.GetCoreSetting<T>()` は **存在しない** (ChatGPT 等が
  示唆しがちだが嘘)
- `Settings.UpdateActiveSetting` は内部で `setting.RunSynchronously(...)`
  を呼ぶため **書き込みは engine update tick 上で適用される** — Bridge 側で
  別途 engine thread dispatch を組まなくて良い
- 設定型の実フィールドは decompile を直接見る:
  - 解像度は `ResolutionSettings.CurrentTargetResolution` / `CurrentCommitedResolution`
  - 背景 fps cap は `DesktopRenderSettings.MaximumBackgroundFramerate`
  - `DesktopRenderSettings` には `Width/Height/MaxFps` は **無い** (誤解
    注意)
- **foreground fps は engine 公式 API では制御できない**:
  `RenderSystem.OnDesktopRenderSettingsChanged` は `DesktopConfig.maximumForegroundFramerate`
  を `null` のまま renderer に送る。foreground fps を 60/120 に上げるには
  reflection で private `RenderSystem._messagingHost.SendCommand(new DesktopConfig {...})` を直接叩くしかない (knowledge §3.4)
- 詳細は \[\[frooxengine-settings-api\]\] (agent-memory)

**Why:** Resonite は SettingComponent を `RunSynchronously` で同期書き込み
できる API として `Settings` static class に集約している。Bridge から
直接 `setting.Field.Value = ...` を書くと engine thread 非同期になる
リスクがあるが、`UpdateActiveSetting` ラッパー経由なら必ず engine tick で
適用される。

**How to apply:**

- 新規 setting-write Bridge を書くときは
  `Settings.UpdateActiveSetting<TSetting>(s => { s.Field.Value = ...; })`
- 設定型の実フィールド名は decompile 直見が一次資料。`.claude/plans/` の
  ChatGPT 提案 API 名は鵜呑みにしない
- foreground fps PR を書く時は `_messagingHost` reflection 経路を採用、
  別 PR で扱う

## 10. net472 + netstandard2.0 polyfill

`ResoniteIO.Renderer` (net472、Unity Mono 互換) と `ResoniteIO.RendererShared`
(netstandard2.0、engine ↔ renderer 共有) の build には:

- `Microsoft.NETFramework.ReferenceAssemblies` NuGet — container 内で
  net472 reference pack 解決 (host に Mono / .NET Framework targeting pack を
  入れる必要なし、`PrivateAssets="all"` で deploy に乗らない)
- `System.Memory` NuGet — netstandard2.0 で `Span<T>` / `BinaryPrimitives`
  を使うための polyfill (Renderer プロセス側 `Renderite.Renderer_Data/Managed/`
  に同名 DLL が既に同梱されているため、deploy には乗せない)
- `DateTime.UnixEpoch` は netstandard2.0 / net472 に **無い**。literal const
  `621_355_968_000_000_000L` (= 1970-01-01T00:00:00Z の `DateTime.Ticks`)
  で `(DateTimeOffset.UtcNow.UtcTicks - unixEpochTicks) * 100L` を計算
- 詳細は \[\[netstandard20-polyfills\]\] (agent-memory)

**Why:** netstandard2.0 / net472 は .NET 10 SDK に標準同梱されない BCL surface
が多い。NuGet polyfill で吸収するのが最もクリーン (Mono 依存・別 SDK 導入を
回避)。

**How to apply:** 新規 netstandard2.0 / net472 ライブラリを足す際は最初から
`System.Memory` + `Microsoft.NETFramework.ReferenceAssemblies` を入れる前提で
csproj を組む。`HashCode.Combine` も netstandard2.0 では使えないので手組み
hash を用意する。

## 11. E1 実機実測値 (2026-05-18)

Resonite を Gale 経由起動、container 内から `just e2e-camera-v2 --frames=120`
で:

| 項目                                     | 実測値                                             |
| ---------------------------------------- | -------------------------------------------------- |
| fps                                      | **30.08** (5 sec、120 frames、Resonite foreground) |
| frame size                               | 1118×651 RGBA8 = 2,911,272 bytes                   |
| `Application.targetFrameRate` (renderer) | 30 (engine default、foreground 時)                 |
| InterprocessLib queue capacity           | 33,554,432 bytes = 32 MiB                          |
| Capture target                           | `OverlayCamera`, depth=50, targetTexture=null      |

knowledge `/home/dev/.claude/plans/camera-v2-shortest-route-knowledge.md` §6 の
v2 native fps=59.55 (background + max_fps=120) との差分は
`Application.targetFrameRate=30` の engine デフォルト + foreground fps cap
制約由来 (\[\[#9-frooxengine-settings-api-は-static-class\]\] 参照)。

**How to apply:** 60fps native を出すには reflection 経由
`_messagingHost` direct send で `DesktopConfig.maximumForegroundFramerate=120`
を書く別 PR が必要。現状の E1 観測値は v2 path 全体が functional であることを
示す pass 基準であり、fps の絶対値は v2 アーキ自体の問題では無い (foreground
cap 制約は v1/v2 共通の engine 公式 API 制約)。
