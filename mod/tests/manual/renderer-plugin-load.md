# Renderer plugin load 検証

`ResoniteIO.Renderer.dll` (BepInEx 5、Wine + Unity Mono 上で動く plugin) が
`Renderite.Renderer.exe` 起動時に正しく load され、OverlayCamera への
CommandBuffer attach と InterprocessLib queue 接続が完了するかを Gale 経由起動で
確認する手動 smoke test (Wine + Unity が container では走らないため自動化不可)。

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

- **`Awake`**: BepInEx 5 が plugin を load 完了
- **`FrameSender attached`**: `InterprocessLib.Messenger` を `isAuthority: false`,
  queue capacity 32 MiB で engine 側 queue に attach 成功 (`capacity=33554432` = 32 MiB)
- **`attached CommandBuffer`**: `Camera.allCameras` から `targetTexture==null && enabled`
  かつ最大 `depth` の camera に `CameraEvent.AfterEverything` で CommandBuffer を attach
  完了。`size` は window resolution 依存 (上は E1 検証時の値)

`attached CommandBuffer` は最初の `Update` tick で `Camera.allCameras` が
非空になった時点で出るため、起動完了まで 1〜2 秒のラグがある。

## 期待される engine 側ログ (補助確認)

`just log` 側でも以下が観測できる (renderer 側 log と時間的に並行):

```text
[Info   :ResoniteIO] [ResoniteIO] RendererFrameInterprocessReceiver listening: owner=net.mlshukai.resonite-io.camera queue=resonite-io-camera-frames capacity=33554432
```

renderer 側 `FrameSender attached` と組合せて **owner / queue / capacity** が
両側で一致しているかを再確認する (drift があると silent failure で frame が届かない)。

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

- 起動直後 1〜2 秒は Renderite が camera 構築前なので発生する。5 秒待てば出るはず
- **15 秒以上待っても出ない** なら Renderite の camera 構造が変わった可能性。
  `just decompile` で `Renderite.Unity` の `CameraController` を再確認
- Camera target は `targetTexture == null && enabled == true && depth = max`

### `FrameSender attached` が出ない

`InterprocessLib.Unity.dll` を load できていない。Gale で `Nytra-InterprocessLib` が
install されており、`ResoniteIO.Renderer.csproj` の HintPath と
`gale/Renderer/BepInEx/plugins/Nytra-InterprocessLib/.../InterprocessLib.Unity.dll`
の実 path が一致しているかを確認。

### `Awake` も出ない (Renderer 側 BepInEx 自体は起動している)

`gale/Renderer/BepInEx/plugins/ResoniteIO.Renderer/ResoniteIO.Renderer.dll` の存在を
確認。存在するなら Renderer 側 `LogOutput.log` 冒頭の Preloader log に load 失敗
の原因 (`BaseUnityPlugin` 参照解決失敗 / `Renderite.Shared` version skew /
net472 polyfill 解決失敗 等) が出ているはず。
