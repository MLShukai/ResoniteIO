---
name: dash-overlay-vs-contextmenu
description: Dash (ESC userspace overlay) は ContextMenu (radial) とは別系統のモダリティ。dash 解決は Userspace.UserspaceWorld 経由、UI 要素は言語非依存の RefID + LocaleStringDriver.Key で識別する。
metadata:
  type: feedback
---

Resonite の **UI 操作系には 2 系統** あり、別モダリティとして実装する。混同しない。

- **`ContextMenu`** — `T`/握り操作で開く radial メニュー。`LocalUser` の `InteractionHandler` 配下。要素は `index`(ArcLayout 子順)で指定。private `OpenContextMenu(MenuOptions.Default)` を reflection 起動。
- **`Dash`** — **ESC で開く userspace overlay**(RadiantDash)。`FocusedWorld` ではなく **`FrooxEngine.Userspace.UserspaceWorld`** 配下に globally-registered された `UserspaceRadiantDash` を扱う。`dash.Open`(bool)で開閉、reflection 不要。

**Why:** dash は `FocusedWorld`(在席ワールド)ではなく userspace world にあるため、ContextMenu の `WorldManager.FocusedWorld` 経路では到達できない。新しい UI/overlay 操作を足すときに最初に間違えやすいポイント。

**How to apply:**

- **言語非依存の UI identifier** が要件のときの主軸は **`Slot.ReferenceID`(`RefID`)+ `LocaleString` の locale key**。表示テキスト(localize 済み)や pixel 座標で要素を指定しない。
  - locale key は `FrooxEngine.LocaleHelper.GetLocalizedDriver(text.Content)?.Key.Value`。**`Text.LocaleContent` は setter 専用で getter が無い** ため、key の読み出しは driver 経由が唯一の経路。
  - RefID 解決は `RefID.TryParse` + `World.ReferenceController.GetObjectOrNull(in refid)`(`Parse` は throw するので避ける)。
- engine API の正確な呼び出し形は [\[reference-dash-uix-engine-api\]](agents/spec-driven-implementer/reference_dash_uix_engine_api.md) に集約(`decompiled/` 由来、Resonite version で drift し得るので再 grep 推奨)。
- 設計全体・proto・v2 は `docs/dash_modality_plan.md` を正典とする。
- **pixel 直指し操作(旧 Pointer 案)は不採用**。ref_id 直接操作で UI 操作が完結するため未実装。canvas→screen 逆投影が必要になったときのみ `DashRect.is_screen_space` とセットで再検討する。
