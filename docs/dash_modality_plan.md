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
| v1 RPC     | `Open` / `Close` / `GetState` + `GetTree`(introspect)+ `Invoke` + `Highlight` + `Scroll`(全て ref_id ベース)                                                                            |
| CLI        | **閲覧+選択に絞る**: `resoio dash` = `open`/`close`/`state`/`tree`/`invoke`。`highlight`/`scroll` は `DashClient` Python API と e2e のみ                                                |
| pixel 操作 | **実装しない**。ref_id 直接操作で UI 操作が完結するため、旧 Pointer 案(pixel `Move`/`Click`/`RightClick`)は不要と判断。Camera ピクセル直指しの要求が将来出たときのみ contingency 再検討 |

## proto(`proto/resonite_io/v1/dash.proto`)

`service Dash` の 7 unary RPC。要点:

- `DashState { bool is_open; float open_lerp; }` — Open/Close/GetState が返す。
- `DashElement { string ref_id; string type; string slot_name; string locale_key; string label; bool enabled; bool interactable; DashRect rect; string parent_ref_id; int32 depth; }` — introspection の 1 ノード。`ref_id` / `locale_key` が言語非依存の主キー。
- `DashRect { float x,y,width,height; bool is_screen_space; }` — `is_screen_space=false` は canvas 空間(screen pixel 逆投影は未実装)。
- `DashTree { repeated DashElement elements; int32 screen_width; int32 screen_height; }` — `GetTree` が返す。
- `DashActionResult { bool ok; bool found; string ref_id; string detail; }` — Invoke/Highlight/Scroll が返す軽量結果。tree 全体は `GetTree` で明示再取得する(Invoke 後に UI が総入れ替えになり得るため)。

エージェントは `GetTree → Invoke(ref_id) → GetTree` でループする。

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

RefID は `RefID.TryParse` + `World.ReferenceController.GetObjectOrNull`。解決失敗・型不一致は **例外でなく** `DashActionResult{found/ok=false, detail}` で返す。

**未確定(spike / e2e で確認)**: ① canvas 空間 rect → screen pixel 逆投影(操作は ref_id 経由で座標非依存なので未対応でもブロックしない。grounding 用に将来 `is_screen_space=true` 化)。② `SimulatePress` の dash overlay UI への実効性。③ locale key の取得範囲(2 言語で実測)。

## レイヤー(ContextMenu をミラー)

- proto: `proto/resonite_io/v1/dash.proto`
- C# Core: `mod/src/ResoniteIO.Core/Dash/{IDashBridge,DashService}.cs`(IF は POCO snapshot を返す。Service は optional DI + 例外翻訳 NotReady→FailedPrecondition / Argument→InvalidArgument / null→Unavailable)
- C# Mod: `mod/src/ResoniteIO/Bridge/FrooxEngineDashBridge.cs` + `ResoniteIOPlugin.cs`(OnEngineReady 生成 / SessionHost.Start 配線 / SafeShutdown null 化)
- SessionHost: `dashBridge` を末尾 optional 引数 + `MapGrpcService<DashService>()`
- Python: `python/src/resoio/dash.py`(`DashClient` + dataclass 群)+ `__init__` 公開
- CLI: `python/src/resoio/cli/dash.py`(`resoio dash`)
- 契約ピン: `ApiContractTests.cs` / `test_proto_contract.py` / `test_api_contract.py`

## 検証

- 単体/結合: `just run`(format → gen-proto → build → test → type)全 green。Core は Kestrel in-process gRPC + 実 UDS round-trip(`DashServiceTests`)、Python は grpclib in-process(`test_dash.py` / CLI `test_dash.py`)。3rd-party / engine 表面 mock 禁止、自前 ABC の Fake のみ。
- e2e(`python/tests/e2e/dash.py`、host-agent 経由で Claude 自動駆動): `just deploy-mod` → `just resonite-start` → open(close→open→close→open の対称 4 step)→ `get_tree`(各要素に `ref_id`、一部に `locale_key`、snapshot 間で安定)→ `invoke`/`highlight` を ref_id で実行 → screenshot で効果確認 → close。`require_host_agent` autouse fixture で host-agent 不在時は skip。

## v2 / 将来(未実装)

- **pixel 直指し操作**: ref_id 直接操作で UI 操作が完結するため未実装。Camera screenshot のピクセルを直接指す用途が出たときのみ、`DashRect` の screen-space 逆投影 spike とセットで再検討する。
- **screen pixel rect**: introspection の grounding 用に canvas→screen 逆投影を解ければ `is_screen_space=true` で返す。
- **言語切替の同一性検証**: e2e で Resonite の locale を切り替え、同一要素の `ref_id`/`locale_key` 不変・`label` のみ変化を直接確認(現状は snapshot 間安定までを自動検証、locale 切替は manual follow-up)。
