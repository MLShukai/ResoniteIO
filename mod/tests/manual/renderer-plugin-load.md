# Renderer plugin load 検証

`ResoniteIO.Renderer.dll` (BepInEx 5、Wine + Unity Mono 上で動く plugin) が
`Renderite.Renderer.exe` 起動時に正しく load され、OverlayCamera への
CommandBuffer attach と InterprocessLib queue 接続が完了するかを Gale 経由起動で
確認する手動 smoke test。

実装計画上の対応:

- v2 = Camera Renderite framebuffer 直取り経路の Wave 5 / E1 で実機検証した内容
  をそのまま手順書化したもの
- 自動化できない (Wine プロセス + Unity が動かない container 内では検証不能)

## 前提

- engine 側 mod が deploy 済み (load-verification.md の手順 1〜2 と同じ手順)

- renderer 側 plugin が deploy 済み:
  `gale/Renderer/BepInEx/plugins/ResoniteIO.Renderer/` 直下に

  - `ResoniteIO.Renderer.dll`
  - `ResoniteIO.Renderer.pdb`
  - `ResoniteIO.RendererShared.dll`

  の 3 ファイル (csproj の PostBuild Target が deploy するので
  `just deploy-mod` 内 (mod-build) で副産物として配置される)

- Gale プロファイルに以下 6 plugin が install 済み (`just check-gale` で確認):

  - `ResoniteModding-BepisLoader` (>=1.5.1)
  - `ResoniteModding-BepInExResoniteShim` (>=0.9.3)
  - `ResoniteModding-BepisResoniteWrapper` (>=1.0.2)
  - `ResoniteModding-BepInExRenderer` (>=5.4) — Renderer 側 BepInEx 5
  - `ResoniteModding-RenderiteHook` (>=1.1.1) — engine → Renderer doorstop inject
  - `Nytra-InterprocessLib` (>=3.0.0) — 共有メモリ queue

- **Steam Launch Options** に
  `WINEDLLOVERRIDES="winhttp=n,b" %command%` が設定済み
  (Renderer 側 BepInEx を inject するための doorstop hook を Wine に
  優先 load させる唯一の経路。host_agent.py 経由の env 渡しは Steam が
  sanitize するため不可)

## 手順

1. **Renderer 側 BepInEx ログ追従用ターミナルを開く** (host 側)

   ```sh
   tail -F gale/Renderer/BepInEx/LogOutput.log
   ```

   ファイルがまだ無ければ「No such file」になるが、Renderer プロセスが
   起動して BepInEx Preloader が走った時点で生成され `tail -F` が自動追従する。

2. **engine 側 BepInEx ログ追従用ターミナルも別途開いておく**

   ```sh
   just log
   ```

   こちらは engine 側 `gale/BepInEx/LogOutput.log` を追う。Renderer の
   spawn 自体は engine の `RenderSystem` が起動するため、engine 側 log で
   "Renderer process started" 系の行を見て Renderer ログを観測するタイミングを
   合わせる。

3. **Gale から Resonite を起動**

   container 内 shell から:

   ```sh
   just resonite-start
   ```

   または host 側 Gale GUI で `<repo>/gale` プロファイルを選んで `Launch Profile`。

## 期待される Renderer 側ログ

`gale/Renderer/BepInEx/LogOutput.log` に以下 3 行 (順序固定) が出ること:

```text
[Info   :ResoniteIO.Renderer] [ResoniteIO.Renderer] Awake (version 0.1.0)
[Info   :ResoniteIO.Renderer] [ResoniteIO.Renderer] FrameSender attached: owner=net.mlshukai.resonite-io.camera queue=resonite-io-camera-frames capacity=33554432
[Info   :ResoniteIO.Renderer] [ResoniteIO.Renderer] attached CommandBuffer to camera name=OverlayCamera depth=50 size=1118x651
```

各行の意味:

- **`Awake`**: `Plugin.cs` の `Awake()` が呼ばれた = BepInEx 5 が plugin を load 完了
- **`FrameSender attached`**: `FrameSender.cs` で `InterprocessLib.Messenger` が
  `isAuthority: false`, queue capacity 32 MiB で engine 側 queue に attach 成功。
  `capacity=33554432` は 32 * 1024 * 1024 = 32 MiB
- **`attached CommandBuffer`**: `FrameCapture.EnsureCommandBufferAttached()` が
  `Camera.allCameras` から `targetTexture==null && enabled` かつ最大 `depth` の
  camera を見つけ、`CameraEvent.AfterEverything` で `BuiltinRenderTextureType.CurrentActive`
  を中間 `RenderTexture` に Blit する CommandBuffer を attach 完了。
  `size` は実機の window resolution に依存 (上は E1 検証時の値)

`Awake` は plugin load 直後に出る。`FrameSender attached` も `Awake` の中で
構築されるので即連続する。`attached CommandBuffer` は最初の `Update` tick で
`Camera.allCameras` が空でない (Renderite が camera を構築済み) になった時点
で出るため、起動完了まで 1〜2 秒のラグがある。

## 期待される engine 側ログ (補助確認)

`just log` 側でも以下が観測できる (renderer 側 log と時間的に並行):

```text
[Info   :ResoniteIO] [ResoniteIO] RendererFrameInterprocessReceiver listening: owner=net.mlshukai.resonite-io.camera queue=resonite-io-camera-frames capacity=33554432
```

これは engine 側 Receiver (Wave 3 C6) が `isAuthority: true` で同じ queue を
作って renderer 側からの push を待ち受けている状態。renderer 側 `FrameSender attached` と組合せると **同じ owner / queue / capacity** が両側で一致して
いることが確認できる (一致しないと silent failure で frame が届かないので
ここでの再 grep が大事)。

## トラブルシュート

### Renderer 側 BepInEx ログが空 / `gale/Renderer/BepInEx/LogOutput.log` が生成されない

最大の落とし穴: **Steam Launch Options の `WINEDLLOVERRIDES` 漏れ**。

- Wine は system 同梱 `winhttp.dll` を優先するため、RenderiteHook が deploy
  した hook 版 `winhttp.dll` (= doorstop) が読まれない
- 結果として Renderer 側 BepInEx Preloader が起動せず、`ResoniteIO.Renderer.dll`
  も load されない (= Renderer 側ログが空のまま)
- Steam で Resonite Properties → Launch Options に
  `WINEDLLOVERRIDES="winhttp=n,b" %command%` が設定されているか確認
- `/proc/<pid>/environ` で env を見ても **Steam が sanitize するため見えない**
  ので、Launch Options が真の根拠

### `Awake` ログは出るが `attached CommandBuffer` が出ない

`Camera.allCameras` から条件に合う camera が見つからない状態:

- 起動直後 (1〜2 秒) は Renderite が camera 構築前なので発生する。`Update`
  tick で再試行されるので 5 秒も待てば出るはず
- **15 秒以上経っても出ない** なら Renderite の camera 構造が変わった可能性。
  `just decompile` で `Renderite.Unity` の `CameraController` / `CameraManager`
  を再確認 (knowledge `/home/dev/.claude/plans/camera-v2-shortest-route-knowledge.md`
  §3.4 にスナップショット時の挙動メモあり)
- Camera target は `targetTexture == null && enabled == true && depth = max`。
  Renderite v2 系で OverlayCamera の depth (現状 50) が変わると拾えない

### `FrameSender attached` が出ない

`InterprocessLib.Unity.dll` が load できていない:

- Gale で `Nytra-InterprocessLib` が install されているか確認
  (`gale/Renderer/BepInEx/plugins/Nytra-InterprocessLib/InterprocessLib.BepInEx/InterprocessLib.Unity.dll`
  が存在するか)
- `ResoniteIO.Renderer.csproj` の HintPath
  `$(GalePath)Renderer/BepInEx/plugins/Nytra-InterprocessLib/InterprocessLib.BepInEx/InterprocessLib.Unity.dll`
  と上記の実 path が一致しているか
- 不一致なら Gale install 後の path が変わっている。`just check-gale`
  を更新するのも合わせて検討

### `Awake` も出ない (Renderer 側 BepInEx 自体は起動している)

- `gale/Renderer/BepInEx/plugins/ResoniteIO.Renderer/ResoniteIO.Renderer.dll`
  が存在するか確認
- 存在するなら BepInEx 5 が plugin の load に失敗している。Renderer 側
  `LogOutput.log` 冒頭の Preloader log に `Could not load plugin '.../ResoniteIO.Renderer.dll'` 系のエラーが出ているはず。typical な原因:
  - `BaseUnityPlugin` の参照解決失敗 (`BepInEx.dll` HintPath ずれ)
  - `Renderite.Shared` / `UnityEngine.CoreModule` の version skew (Resonite
    update 後)
  - net472 polyfill (System.Memory) の解決失敗
