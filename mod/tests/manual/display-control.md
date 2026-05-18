# Display 制御 (DisplayClient) 実機検証

Python `DisplayClient.apply(...)` / `DisplayClient.get()` の挙動を実機で
確認する手動検証手順。

## 重要な前置き

`FrooxEngineDisplayBridge` は engine 公式 API 経由のため
**`max_fps` は `MaximumBackgroundFramerate` (= background fps cap) にしかマップされない**。
foreground fps を上げる経路は engine `RenderSystem._messagingHost` への
reflection 経由でしか不可能 (camera-v2-constraints §9)。本 Bridge は連動で
`LimitFramerateWhenUnfocused=true` を書くので、`apply(max_fps=120.0)` 後に
**Resonite window から focus を外す** (Alt-Tab 等) と engine が renderer に
`DesktopConfig { maximumBackgroundFramerate=120 }` を送って反映される。
foreground 状態では `Application.targetFrameRate=30` のまま。

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
- 即時には fps は変わらない (foreground 中なので `MaximumBackgroundFramerate` は休眠)
- **Alt-Tab で focus を外す** と Resonite が background となり engine が renderer に
  `DesktopConfig { maximumBackgroundFramerate=120 }` を送って `Application.targetFrameRate=120`
  に切り替わる (VSync 有効なら monitor refresh rate で律速)

### `get()`

- `width` / `height`: `ResolutionSettings.CurrentTargetResolution`
- `max_fps`: `DesktopRenderSettings.MaximumBackgroundFramerate`
- `apply` 後の `get` は更新後の値を返す (engine 書き込みは `RunSynchronously`
  で engine thread に dispatch されるため `apply` return 時点で確定)

## 0 = "変更しない" の動作確認

`apply` の任意フィールドを 0 で渡すと engine 側はそのフィールドを skip する
(proto3 default value セマンティクス):

```python
# max_fps だけ更新、resolution は据え置き
info = await client.apply(max_fps=60.0)
# → info.width / info.height は変わらず、max_fps だけ 60.0
```

## トラブルシュート

### `RpcException: Status.Unavailable, "Display bridge is not configured."`

`SessionHost` に `IDisplayBridge` が注入されていない。`Engine ready` 以降に
`Failed to start Session gRPC host:` 等のエラーが engine 側 log (`just log`) に
出ていないか確認。

### `RpcException: Status.FailedPrecondition, "ResolutionSettings is not yet active"`

engine 起動直後で `Settings.GetActiveSetting<T>()` がまだ null。world load 完了
まで数秒待ってから再試行 (`FailedPrecondition` は client retry 可能の signal)。

### Resolution は変わるが fps cap が反映されない (Alt-Tab しても)

- `LimitFramerateWhenUnfocused` が `true` になっているか `client.get()` で確認
  (false だと engine が `DesktopConfig.maximumBackgroundFramerate=null` で送る)
- renderer 側 (`Renderite.Unity.RenderingManager`) の `_maxBackgroundFPS` 反映は
  decompile で確認

## VR モード時の挙動 (未検証)

VR mode では `ResolutionSettings.CurrentTargetResolution` が
`WindowResolution` / `FullscreenResolution` のどちらを返すかが `Fullscreen.Value`
で分岐する。VR HMD 解像度は別系統 (`VRRenderSettings` 等) なので
`apply(width=..., height=...)` では変わらないはず。
