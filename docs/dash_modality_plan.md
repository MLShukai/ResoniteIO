# Dash モダリティ 設計 & 実装メモ(as-built)

> **ステータス: 実装済み(v1)。** ESC で開く userspace overlay (dash / RadiantDash) を取得・操作する `Dash` モダリティ。本ドキュメントは実装済みの設計を記録する。実機 behavioral 検証は e2e (`python/tests/e2e/dash.py`) を host-agent 経由で駆動して行う。

## Context

AI エージェントが Resonite の **ESC で開く dash(userspace overlay)メニューを取得・操作する** ための新モダリティ。既存 `ContextMenu` は `InteractionHandler` の radial メニューを `index` で操作するだけで、ESC の dash は開けず、dash 内 UI を列挙できなかった。

旧 `pointer_modality_plan.md` は **pixel 座標専用の Pointer** を計画していたが、前提依存(dash open/close + UI introspection)が未解決で、dash UI が言語ごとに localize されるため表示テキスト/ピクセル頼みの指定は脆かった。本モダリティはこれらを **単一 `Dash` モダリティ** に統合し、**言語非依存の `ref_id`(engine `Slot.ReferenceID`)+ `locale_key`(`LocaleStringDriver.Key`)を主軸**に据えた。これにより「開く → 網羅的に取得 → 言語非依存 ID で操作 → 効果確認 → 閉じる」の閉ループが localize/解像度に左右されず成立する。

## スコープと決定事項

| 項目       | 決定                                                                                                                                                                                    |
| ---------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 分割       | **単一 `Dash` モダリティ**(open/close + introspection + interaction を 1 service に統合)。ContextMenu とは別系統で共存                                                                  |
| 指定の主軸 | **identifier(ref_id + locale_key)単独**。表示テキスト/座標には依存しない                                                                                                                |
| v1 RPC     | `Open` / `Close` / `GetState` + `GetTree`(introspect)+ `Invoke` + `Highlight` + `Scroll` + `ListScreens` + `SetScreen`(全て ref_id / key ベース)                                        |
| 画面遷移   | **言語非依存 key / ref_id で screen(下部タブ)を列挙・切替**。表示テキストや pixel タブ位置に依存しない。`SetScreen` は open 状態を変えない                                              |
| CLI        | **閲覧+選択に絞る**: `resoio dash` = `open`/`close`/`state`/`tree`/`invoke`/`screens`/`set-screen`。`highlight`/`scroll` は `DashClient` Python API と e2e のみ                         |
| pixel 操作 | **実装しない**。ref_id 直接操作で UI 操作が完結するため、旧 Pointer 案(pixel `Move`/`Click`/`RightClick`)は不要と判断。Camera ピクセル直指しの要求が将来出たときのみ contingency 再検討 |

## proto(`proto/resonite_io/v1/dash.proto`)

`service Dash` の 9 unary RPC。要点:

- `DashState { bool is_open; float open_lerp; }` — Open/Close/GetState が返す。
- `DashElement { string ref_id; string type; string slot_name; string locale_key; string label; bool enabled; bool interactable; DashRect rect; string parent_ref_id; int32 depth; }` — introspection の 1 ノード。`ref_id` / `locale_key` が言語非依存の主キー。
- `DashRect { float x,y,width,height; bool is_screen_space; }` — `is_screen_space=false` は canvas 空間(screen pixel 逆投影は未実装)。
- `DashTree { repeated DashElement elements; int32 screen_width; int32 screen_height; }` — `GetTree` が返す。
- `DashActionResult { bool ok; bool found; string ref_id; string detail; }` — Invoke/Highlight/Scroll/SetScreen が返す軽量結果。tree 全体は `GetTree` で明示再取得する(Invoke / SetScreen 後に UI が総入れ替えになり得るため)。
- `DashScreen { string ref_id; string key; string name; string label; bool is_current; bool enabled; }` — 下部タブ 1 screen。`key`(`LocaleStringDriver.Key`、例 `Dash.Screens.Worlds`)/ `ref_id`(screen slot `ReferenceID`)が言語非依存の主キー。
- `DashScreenList { repeated DashScreen screens; }` — `ListScreens` が返す。`is_current==true` は高々 1 件。
- `DashSetScreenRequest { string ref_id; string key; }` — `SetScreen` の入力。`ref_id` 非空ならそれで exact 指定、空なら `key` で解決。両空はクライアントの引数ミスとして `InvalidArgument`(bridge を起動しない)。

エージェントは UI 要素は `GetTree → Invoke(ref_id) → GetTree`、画面は `ListScreens → SetScreen(key/ref_id) → GetTree` でループする。

## engine マッピング(as-built / decompiled 準拠)

`mod/src/ResoniteIO/Bridge/FrooxEngineDashBridge.cs`。全操作は `World.RunSynchronously` + `TaskCompletionSource` で engine thread に marshal(ContextMenu と同型)。dash は `Userspace.UserspaceWorld` → `GetGloballyRegisteredComponent<UserspaceRadiantDash>()` で解決(未準備は `DashNotReadyException` → `FailedPrecondition`)。

| RPC          | engine 経路                                                                                              | 確度        |
| ------------ | -------------------------------------------------------------------------------------------------------- | ----------- |
| Open/Close   | `UserspaceRadiantDash.Open = true/false`(setter は `BlockOpenClose` で抑止され得る)                      | 確実        |
| GetState     | `dash.Open` / `dash.OpenLerp`                                                                            | 確実        |
| GetTree      | `Dash.CurrentScreen.Target.ScreenRoot`(fallback `VisualsRoot`)から `RectTransform` 持ち Slot を DFS 列挙 | best-effort |
| → ref_id     | `Slot.ReferenceID.ToString()`                                                                            | 確実        |
| → locale_key | `FrooxEngine.LocaleHelper.GetLocalizedDriver(text.Content)?.Key.Value`(無ければ空)                       | best-effort |
| → rect       | `RectTransform.ComputeGlobalComputeRect()`(canvas 空間、`is_screen_space=false`)                         | best-effort |
| Invoke       | RefID 解決 → `Button.SimulatePress(0.1f, ButtonEventData(button, canvasGlobalPoint, …))`                 | best-effort |
| Highlight    | RefID 解決 → `InteractionElement.IsHovering.Value = true`                                                | best-effort |
| Scroll       | RefID 解決 → `ScrollRect.NormalizedPosition.Value += (dx,dy)`(`MathX.Clamp01`)                           | best-effort |
| ListScreens  | `RadiantDash.Screens` を直接列挙(dash が閉じていても screen 構成は存在するので列挙可)                    | 確実        |
| SetScreen    | screen 解決 → `RadiantDash.CurrentScreen.Target = screen`(代入は同期反映)                                | 確実        |
| → screen key | `LocaleHelper.GetLocalizedDriver(screen.Label)?.Key.Value`                                               | best-effort |

RefID は `RefID.TryParse` + `World.ReferenceController.GetObjectOrNull`。解決失敗・型不一致は **例外でなく** `DashActionResult{found/ok=false, detail}` で返す。

**未確定(spike / e2e で確認)**: ① canvas 空間 rect → screen pixel 逆投影(操作は ref_id 経由で座標非依存なので未対応でもブロックしない。grounding 用に将来 `is_screen_space=true` 化)。② `SimulatePress` の dash overlay UI への実効性。③ locale key の取得範囲(2 言語で実測)。

## screen 列挙・遷移(ListScreens / SetScreen)

dash 下部タブ(Worlds / Inventory / Settings / Contacts …)は `RadiantDashScreen` 単位で、`GetTree` の UI 要素列挙とは別軸の「画面切替」操作。`Invoke(ref_id)` でタブ Button を叩く経路もあり得たが、**screen 自体を言語非依存 `key`(`LocaleStringDriver.Key`、例 `Dash.Screens.Worlds`)/ `ref_id` で列挙・指定する専用 RPC** を切り出した。これにより localize された表示テキストや、解像度依存の pixel タブ位置に頼らず「現在 screen を知り、別 screen へ移る」が成立する。

設計意図と engine 機構:

- **列挙(`ListScreens`)**: `RadiantDash.Screens` を直接列挙し、各 `RadiantDashScreen` を `DashScreen{ref_id, key, name, label, is_current, enabled}` に写す。`is_current` は `RadiantDash.CurrentScreen.Target` 一致、`enabled` は `screen.ScreenEnabled`(ログアウト中の Contacts 等は false)。dash が閉じていても screen 構成は存在するため、open を要求せず列挙できる。
- **遷移(`SetScreen`)**: `ref_id` 非空ならそれで exact 解決、空なら `key` で解決し、`RadiantDash.CurrentScreen.Target = screen` を **直接代入**。これは engine 自身の `RadiantDashButton.Pressed` と同一経路で、`SimulatePress` でタブ Button を叩く経路は採らない(言語非依存 key で解決した screen を確実かつ同期的に切替でき、Button の hit-test / interactable gating に左右されないため)。**open 状態は変えない**(別 screen が選ばれるだけで、表示反映は次の `GetTree` で取れる)。
- **所属保証**: screen 解決は `World.ReferenceController` ではなく `Screens` を直接列挙する。任意 RefID の Slot を screen と取り違えて代入する事故を防ぐため。
- **soft-fail**: `ref_id` / `key` 両空はクライアントの引数ミスとして Service 層で `InvalidArgument`(bridge を起動しない)。一致 screen が無いときは例外でなく `DashActionResult{found/ok=false, detail="screen not found"}`。disabled screen は代入自体がブロックされないため遷移は成立扱い(`ok=true`)とし `detail="screen disabled"` を載せる。

**e2e で実証済み(`python/tests/e2e/dash.py`)**: `list_screens` が 11 screen を列挙、`set_screen` で Worlds / Inventory / Settings へ遷移し、遷移後 `list_screens` の `is_current` が指定 screen に移ること、遷移後 `get_tree` が当該 screen の UI を描画することを screenshot で確認。

## レイヤー(ContextMenu をミラー)

- proto: `proto/resonite_io/v1/dash.proto`
- C# Core: `mod/src/ResoniteIO.Core/Dash/{IDashBridge,DashService}.cs`(IF は POCO snapshot を返す。Service は optional DI + 例外翻訳 NotReady→FailedPrecondition / Argument→InvalidArgument / null→Unavailable)
- C# Mod: `mod/src/ResoniteIO/Bridge/FrooxEngineDashBridge.cs` + `ResoniteIOPlugin.cs`(OnEngineReady 生成 / SessionHost.Start 配線 / SafeShutdown null 化)
- SessionHost: `dashBridge` を末尾 optional 引数 + `MapGrpcService<DashService>()`
- Python: `python/src/resoio/dash.py`(`DashClient` + dataclass 群)+ `__init__` 公開
- CLI: `python/src/resoio/cli/dash.py`(`resoio dash`、action に `screens` / `set-screen` を含む)
- 契約ピン: `ApiContractTests.cs` / `test_proto_contract.py` / `test_api_contract.py`

## 検証

- 単体/結合: `just run`(format → gen-proto → build → test → type)全 green。Core は Kestrel in-process gRPC + 実 UDS round-trip(`DashServiceTests`)、Python は grpclib in-process(`test_dash.py` / CLI `test_dash.py`)。3rd-party / engine 表面 mock 禁止、自前 ABC の Fake のみ。
- e2e(`python/tests/e2e/dash.py`、host-agent 経由で Claude 自動駆動): `just deploy-mod` → `just resonite-start` → open(close→open→close→open の対称 4 step)→ `get_tree`(各要素に `ref_id`、一部に `locale_key`、snapshot 間で安定)→ `invoke`/`highlight` を ref_id で実行 → `list_screens`(11 screen)→ `set_screen` で Worlds / Inventory / Settings へ遷移し `is_current` 移動と別画面描画を確認 → screenshot で効果確認 → close。`require_host_agent` autouse fixture で host-agent 不在時は skip。

## v2 / 将来(未実装)

- **pixel 直指し操作**: ref_id 直接操作で UI 操作が完結するため未実装。Camera screenshot のピクセルを直接指す用途が出たときのみ、`DashRect` の screen-space 逆投影 spike とセットで再検討する。
- **screen pixel rect**: introspection の grounding 用に canvas→screen 逆投影を解ければ `is_screen_space=true` で返す。
- **言語切替の同一性検証**: e2e で Resonite の locale を切り替え、同一要素の `ref_id`/`locale_key` 不変・`label` のみ変化を直接確認(現状は snapshot 間安定までを自動検証、locale 切替は manual follow-up)。
