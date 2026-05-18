# Display 制御 (DisplayClient) 実機検証

Python `DisplayClient.apply(...)` / `DisplayClient.get()` の挙動を実機で
確認する手動検証手順。

## 重要な前置き

`FrooxEngineDisplayBridge` は engine 公式 API
(`Settings.UpdateActiveSetting<DesktopRenderSettings>` /
`Settings.UpdateActiveSetting<ResolutionSettings>`) を経由するため、
**`max_fps` は engine 側で `MaximumBackgroundFramerate` (= window が
background のときの fps cap) にしかマップされない**。

- foreground fps を 60 / 120 に上げる経路は engine `RenderSystem` の private
  `_messagingHost` への reflection 経由でしか実現できない
  (knowledge `/home/dev/.claude/plans/camera-v2-shortest-route-knowledge.md`
  §3.4 で max_fps_foreground=120 を実現した path)
- 本 Bridge では `LimitFramerateWhenUnfocused=true` を連動で書くので、
  `apply(max_fps=120.0)` 後に **Resonite window から focus を外す**
  (Alt-Tab で別ウィンドウに移動するなど) と engine が renderer に
  `DesktopConfig { maximumBackgroundFramerate=120 }` を送る
- foreground 状態 (Resonite が active window) では `Application.targetFrameRate=30`
  (engine default) のまま。これは Plan §risk と user 合意の状態であり、
  必要なら別 PR で `_messagingHost` 直叩き path を追加する前提

## 前提

- [load-verification.md](load-verification.md) と
  [camera-v2-e2e.md](camera-v2-e2e.md) の前提条件すべて
- container 内で `cd python && uv sync` 済み (DisplayClient を import できる
  状態)

## 手順

container 内 shell で Resonite 起動状態 (`just resonite-start` 済み):

```sh
just container-shell
cd python
uv run python - <<'PY'
import asyncio
from resoio import DisplayClient


async def main():
    async with DisplayClient() as client:
        # 0) 現状を取得
        before = await client.get()
        print("before:", before)

        # 1) Resolution を 1280x720 に変える
        after_res = await client.apply(width=1280, height=720)
        print("after resolution apply:", after_res)

        # 2) Background fps cap を 120 に上げる
        after_fps = await client.apply(max_fps=120.0)
        print("after fps apply:", after_fps)

        # 3) 改めて現状を取得
        current = await client.get()
        print("current:", current)


asyncio.run(main())
PY
```

## 期待される挙動

### Resolution apply (`apply(width=1280, height=720)`)

- engine 側 log (`just log`) に Bridge からの info log が 1 行出る:
  ```text
  [Info   :ResoniteIO] [ResoniteIO] Display.Apply: resolution → 1280x720
  ```
- Resonite window が即 1280×720 にリサイズされる
  (fullscreen mode 中だとリサイズが visible に反映されない可能性、
  windowed mode 推奨)
- 返値 `DisplayInfo` の `width=1280, height=720` が反映され、`max_fps` は
  変更前の値を保つ (proto3 `0 = 変更しない` セマンティクス)

### Background fps apply (`apply(max_fps=120.0)`)

- engine 側 log:
  ```text
  [Info   :ResoniteIO] [ResoniteIO] Display.Apply: max_fps (background) → 120
  ```
- 即時には fps は変わらない (foreground 中なので `MaximumBackgroundFramerate`
  は休眠状態)
- **Alt-Tab で別ウィンドウに focus を移す** と Resonite が background となり
  engine が renderer に `DesktopConfig { maximumBackgroundFramerate=120, vSync=true }` を送る → renderer の `Application.targetFrameRate=120` に
  切り替わる (VSync 有効なら monitor refresh rate で律速)

### `get()`

- 現状の engine snapshot を返す:
  - `width` / `height`: `ResolutionSettings.CurrentTargetResolution`
  - `max_fps`: `DesktopRenderSettings.MaximumBackgroundFramerate`
- `apply` を呼んだ後の `get` は変更後の値を返す (engine への書き込みは
  `Settings.UpdateActiveSetting` が `RunSynchronously` 経由で engine thread
  に dispatch するため、`apply` が return した時点で snapshot は更新済み)

## 0 = "変更しない" の動作確認

`apply` の任意のフィールドを 0 で渡すと engine 側は当該フィールドを skip する:

```python
# max_fps だけ更新、resolution は据え置き
info = await client.apply(max_fps=60.0)
# → info.width / info.height は変わらず、max_fps だけ 60.0
```

これは proto3 default value セマンティクス。Python `DisplayClient` は 0 を raw
に server に forward し、server-side Bridge (`FrooxEngineDisplayBridge`) が
`config.Width != 0` の `if` block 全体を skip する。

## トラブルシュート

### `RpcException: Status.Unavailable, "Display bridge is not configured."`

`SessionHost` に `IDisplayBridge` が注入されていない。Wave 4 / C8 で
`ResoniteIOPlugin.OnEngineReady` が `FrooxEngineDisplayBridge` を構築するよう
配線したが、engine 起動順序の race で `Engine.Current` がまだ初期化されて
おらず例外が出ると Bridge 構築が skip される可能性。engine 側 log
(`just log`) で `Engine ready` 以降に `Failed to start Session gRPC host:`
等のエラーが出ていないか確認。

### `RpcException: Status.FailedPrecondition, "ResolutionSettings is not yet active"`

engine 起動直後で `Settings.GetActiveSetting<T>()` がまだ null を返す
状態。world load 完了まで数秒待ってから `apply` / `get` を再試行する
(`FailedPrecondition` は client retry 可能の signal)。

### Resolution は変わるが fps cap が反映されない (Alt-Tab しても)

- engine 側 log で `OnDesktopRenderSettingsChanged` 由来の Renderite 側 command
  送出ログを探す (engine の `RenderSystem` 内 log)
- `LimitFramerateWhenUnfocused` が `true` になっているか `client.get()` で
  確認 (false だと engine が `DesktopConfig.maximumBackgroundFramerate=null`
  で送る、`OnDesktopRenderSettingsChanged` の decompile を参照)
- renderer 側 (`Renderite.Unity.RenderingManager`) で `_maxBackgroundFPS`
  反映を確認するには decompile を参照する

## VR モード時の挙動 (未検証 / 観察事項)

VR mode で `apply()` を呼ぶケースは E1 では検証していない。observe-only:

- `ResolutionSettings` には `WindowResolution` と `FullscreenResolution` が
  別 field で存在し、現在のモードに応じて `CurrentTargetResolution` が
  どちらを返すかが分岐する (`Fullscreen.Value` で切替)
- VR mode で `apply(width=..., height=...)` を呼ぶと desktop window 解像度
  のみ変わり、VR HMD のレンダリング解像度は別系統 (`VRRenderSettings` 等
  別 setting) なので変わらないはず
- 検証 TODO は Plan §後続 で扱う
