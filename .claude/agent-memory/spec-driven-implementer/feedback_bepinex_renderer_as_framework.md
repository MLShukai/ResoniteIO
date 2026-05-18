---
name: bepinex-renderer-as-framework
description: ResoniteModding-BepInExRenderer は plugin dir を作らず Renderer/BepInEx/core/ 配下に framework を deploy する。check-gale は BepInEx.Preloader.dll で確認する
metadata:
  type: feedback
---

`ResoniteModding-BepInExRenderer` package は Thunderstore 上は plugin として
配布されているが、**Gale install 後の disk 上は plugin dir を持たない**。代わりに
`$GALE_ROOT/Renderer/BepInEx/core/` 配下に BepInEx 5 framework 一式
(`BepInEx.dll`, `BepInEx.Preloader.dll`, `0Harmony.dll`, `Mono.Cecil.dll`, ...) を展開する。

**Why:** BepInExRenderer 自体が Renderer 側 (Wine + Unity Mono) で動く BepInEx 5
そのもの。engine 側 BepInEx 6 とは別 framework なので、`BepInEx/plugins/` 以下
ではなく `Renderer/BepInEx/core/` という別系統に置く設計になっている。
RenderiteHook (engine 側 plugin) が起動時に doorstop files
(`winhttp.dll` / `doorstop_config.ini`) を copy + Renderer プロセス起動 cmdline に
`--doorstop-target-assembly Z:/.../gale/Renderer/BepInEx/core/BepInEx.Preloader.dll`
を inject する。

**How to apply:** `just check-gale` で BepInExRenderer の install を検証する際は
`$GALE_ROOT/BepInEx/plugins/ResoniteModding-BepInExRenderer*/...` を glob しない
(必ず空振りする)。代わりに `$GALE_ROOT/Renderer/BepInEx/core/BepInEx.Preloader.dll`
の存在を確認すればよい (これが BepInExRenderer の deploy 物の中核)。
詳細は \[\[bepinex-renderer-as-framework\]\] と \[\[camera-v2-shared-netstandard\]\]
の組み合わせで Camera v2 の Renderer 側 plugin load 経路全体を理解できる。
