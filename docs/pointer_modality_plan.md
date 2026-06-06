# Pointer モダリティ 設計仕様 & 計画(将来計画 / 未着手)

> **ステータス: 将来計画。未着手。** 本ドキュメントは設計を確定して残すためのもので、実装はまだ行わない。
> **前提依存あり**: Pointer 単体では実機検証も実用も成立しない。下記「前提依存」を先に(または対で)整える必要がある。
> 着手順は **UI introspection + dash open/close → Pointer**。

## Context

resonite-io に、AI エージェントが **画面上の任意の UI を screen pixel 座標 (x,y) で直接操作する** ための新モダリティ **Pointer** を追加したい。

既存の ContextMenu モダリティ([`proto/resonite_io/v1/context_menu.proto`](../proto/resonite_io/v1/context_menu.proto))は `InteractionHandler` の radial メニューを **`index`(ArcLayout 子順)** で開閉 / Highlight / Invoke するもので、**画面の x,y 座標は扱わない**。Pointer はそれとは独立に、デスクトップのポインタのように「画面の (x,y) に移動して hover(= highlight)、click(= invoke)、右クリック、スクロール」を行う汎用 UI ポインタを提供する。Camera で撮ったスクリーンショット上のピクセルを指して、エージェントが世界内 UI を操作する閉ループを狙う。

実装パターンは ContextMenu がほぼテンプレートになる(状態を返す unary RPC + engine thread 同期マーシャル + optional bridge DI + `NotReady` → `FailedPrecondition` 翻訳)。

### ユーザー確定事項

| 項目     | 決定                                                                                                                                                   |
| -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| スコープ | **汎用 screen pointer 単独**(ContextMenu とは非連携の独立モダリティ)                                                                                   |
| 座標系   | **pixel 座標**(画面 / Camera 解像度に一致)                                                                                                             |
| v1 操作  | Move(= hover/highlight) + Click(= invoke) をコアに、**右クリック** と **スクロール** を追加。drag / hover 対象の読み取りは v1 対象外(前提依存欄も参照) |

## 前提依存(Pointer より先 / 対で必要)

Pointer に着手する前に解く必要がある、Pointer とは別関心の課題。**これらが無いと e2e 検証も実用も成立しない**。

1. **Dash(userspace overlay)メニューの open/close**

   - e2e で「操作対象の UI」を画面に出すには、デスクトップで **Esc で開く dash(userspace overlay menu)** を engine から開閉する手段が要る。
   - これは radial の ContextMenu(`InteractionHandler.OpenContextMenu`)とは別物で、`Userspace` overlay 側の世界。open/close の engine API(または reflection 経路)を decompile で特定する必要がある。
   - 位置づけ: 独立した小モダリティ(例 Dash の open/close)、もしくは検証用ユーティリティ。

2. **UI オブジェクト取得(introspection)**

   - (x,y) をクリックする Pointer は、「画面上に **どの UI 要素が・どの pixel 範囲に・どんなラベル / 種別で** あるか」を取得できないと、エージェントがどこを指せばよいか分からず実用にならない。
   - Canvas / Button / ScrollRect 等を列挙し、各要素の **screen-space rect + label + 種別 + 操作可否** を返す capability が Pointer と対になる(別モダリティ、もしくは Pointer の `GetState` / hover readback を拡張する形)。
   - これは v1 で外した「hover 対象の読み取り」と地続き。Pointer を実用にするなら結局必要になる。

3. **依存順**: dash open/close と UI introspection を先に(または同時に)整え、その上で Pointer の **e2e**(UI を出す → 要素位置を知る → そこを指す → 効いたか確認)が初めて意味を持つ。

## proto 仕様(`proto/resonite_io/v1/pointer.proto` を新規作成・将来)

座標は pixel、**origin = 画面左上 (0,0)、x 右、y 下**(スクリーンショット慣習)。engine 内部の Y 反転・ray 変換は Bridge が吸収する。RPC / メッセージ命名は ContextMenu に倣う(`buf.yaml` の `SERVICE_SUFFIX` / `RPC_REQUEST_STANDARD_NAME` / `RPC_RESPONSE_STANDARD_NAME` except 配下)。

```proto
syntax = "proto3";
package resonite_io.v1;
option csharp_namespace = "ResoniteIO.V1";

// ポインタ状態スナップショット。各 RPC は操作適用後の状態を engine thread 上で読んで返す。
message PointerState {
  float x = 1;        // 現在の保持位置 (pixel, origin 左上)
  float y = 2;
  int32 width = 3;    // ポインタ座標空間 = 現在の window 解像度 (pixel)。
  int32 height = 4;   // client に有効な pixel 範囲 [0,width]x[0,height] を伝える。
}

message PointerMoveRequest      { float x = 1; float y = 2; }
message PointerClickRequest     { float x = 1; float y = 2; }   // 左 press+release (atomic)
message PointerRightClickRequest{ float x = 1; float y = 2; }
message PointerScrollRequest {
  float x = 1; float y = 2;             // スクロールを当てる画面位置
  float delta_x = 3; float delta_y = 4; // スクロール量 (engine の axis delta 規約に合わせる)
}
message PointerGetStateRequest {}

service Pointer {
  rpc Move(PointerMoveRequest) returns (PointerState);              // hover/highlight
  rpc Click(PointerClickRequest) returns (PointerState);            // left invoke
  rpc RightClick(PointerRightClickRequest) returns (PointerState);  // 要 spike
  rpc Scroll(PointerScrollRequest) returns (PointerState);
  rpc GetState(PointerGetStateRequest) returns (PointerState);
}
```

> 設計メモ: `width` / `height` を state に含めるのは、Camera のレンダリング解像度と window 解像度が一致しない場合に client が pixel をスケールできるようにするため。`is_over_ui` 等の hover 対象読み取りは前提依存(2)の UI introspection と統合して将来 field 追加(番号は連番)で拡張する。

## 実装方式: component-level Pointer driver

このプロジェクトの Resonite は **Linux / Proton(Wine)** 上で動くため、**OS ネイティブ injection は採用不可**。`InputInterface.InjectTouch()` / `InjectRightClick()` は `ISystemInputInjector` → `WindowsInputInjector`(`SetCursorPos` / `InputSimulator` / user32)に委譲し、Wine 下で機能しない前提。ContextMenu と同じく **OS 入力を使わない component-level 経路**で実現する(`decompiled/` 実コードで検証済み)。

`FrooxEnginePointerBridge` は **永続的な `RelayTouchSource` を 1 個** LocalUser 配下の隠しスロットに持ち、**stateful repeater**(Locomotion 流 `RunInUpdates(0, Tick)` 自己再スケジュール)で保持位置を毎 tick `UpdateTouch()` し続けて hover を維持する。

| 操作       | engine 側経路                                                                                  | スレッド                        | 確度     |
| ---------- | ---------------------------------------------------------------------------------------------- | ------------------------------- | -------- |
| Move       | 保持 (x,y) を更新 → getter が ray 化 → `UpdateTouch()` で hover 配送                           | engine tick                     | OK       |
| Click      | Move 後、hit した `Button.SimulatePress(0.1f, ButtonEventData)`(無ければ touch Begin/End 駆動) | engine tick(`RunSynchronously`) | OK       |
| Scroll     | Move 後、`Canvas.ProcessAxis(source, (dx,dy))`(または対象 `ScrollRect.NormalizedPosition`)     | engine tick                     | OK       |
| RightClick | `Canvas.TriggerSecondary(source)` を試行。受け手 UI が限定的 → 不可なら contingency            | engine tick                     | 要 spike |
| GetState   | 保持 (x,y) + `WindowResolution` を読む                                                         | 任意 / engine tick              | OK       |

座標変換は `decompiled/` の `PointerInteractionController.PointerToRay`(world-space UI: pixel → 正規化 UV → `MathX.UVToPerspectiveCameraDirection` で camera ray)を正典として再現する。**userspace overlay(dash)UI** は `ComputeOverlayPoint` 系の別マッピングが要り、前提依存(1)の dash open/close と密接。world-space UI と overlay UI のどちらを主対象にするかは spike で確定。

未準備(`FocusedWorld` / `LocalUser` / touch source 未生成)時は `PointerNotReadyException` を投げ、Service が `FailedPrecondition` に翻訳(ContextMenu と同一規約)。

## レイヤー別実装(ContextMenu をミラー / 将来)

### 新規作成

| ファイル                                                            | 内容                                                                                                                                                                                        |
| ------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `proto/resonite_io/v1/pointer.proto`                                | 上記 proto                                                                                                                                                                                  |
| `mod/src/ResoniteIO.Core/Pointer/IPointerBridge.cs`                 | Bridge IF + `PointerStateSnapshot`(Core POCO record)+ `PointerNotReadyException`。Bridge IF は **proto 型でなく POCO を返す**(Fake が CS0738 を出さない規約)                                |
| `mod/src/ResoniteIO.Core/Pointer/PointerService.cs`                 | `V1.Pointer.PointerBase` 実装。optional DI、共通 `HandleAsync` で例外翻訳、`MapToProto`。`ContextMenuService.cs` と同型                                                                     |
| `mod/src/ResoniteIO/Bridge/FrooxEnginePointerBridge.cs`             | component-level driver。`RunSynchronously` + `TaskCompletionSource`、`RelayTouchSource` spawn、repeater、`SimulatePress` / `ProcessAxis`。`IDisposable` で repeater 停止 + 隠しスロット削除 |
| `mod/tests/ResoniteIO.Core.Tests/Common/Fakes/PointerBridgeFake.cs` | 自前 ABC の Fake(記録 + 例外注入)                                                                                                                                                           |
| `mod/tests/ResoniteIO.Core.Tests/Pointer/PointerServiceTests.cs`    | Kestrel in-process gRPC + 実 UDS round-trip。各 RPC が Fake へ届く / 例外翻訳 / 未設定 bridge で `Unavailable`                                                                              |
| `python/src/resoio/pointer.py`                                      | `PointerClient`(async ctx mgr)+ `PointerState` POCO。`move` / `click` / `right_click` / `scroll` / `get_state` の unary メソッド                                                            |
| `python/src/resoio/cli/pointer.py`                                  | flat command `resoio pointer`。`register(subparsers, common)` + `async _run`                                                                                                                |
| `python/tests/resoio/test_pointer.py`                               | grpclib in-process server round-trip                                                                                                                                                        |
| `python/tests/resoio/cli/test_pointer.py`                           | CLI 引数 dispatch                                                                                                                                                                           |
| `python/tests/e2e/pointer.py`                                       | 実 Resonite e2e(**前提依存 (1)(2) が前提**)                                                                                                                                                 |

### 既存ファイル編集

- `mod/src/ResoniteIO.Core/Session/SessionHost.cs`: `Start()` に `IPointerBridge? pointerBridge = null` / `AddSingleton` / `app.MapGrpcService<PointerService>()` / 未設定 warning。
- `mod/src/ResoniteIO/ResoniteIOPlugin.cs`: pointer bridge field / `OnEngineReady` で生成し `SessionHost.Start` に渡す / **SafeShutdown chain** に挿入(UI 操作系として contextmenu の隣、locomotion 群の後)。`SafeDispose` で repeater 停止 + slot 削除。
- `python/src/resoio/__init__.py`: `from resoio.pointer import PointerClient, PointerState` / 公開 `__all__` に alphabetical 追加。
- `python/src/resoio/cli/__init__.py`: コマンドモジュール一覧に `pointer` を append。
- 契約ピン: `ApiContractTests.cs`(`ResoniteIO.Core.Pointer.*` / `ResoniteIO.V1.Pointer*`)、`test_proto_contract.py`(field 番号)、`test_api_contract.py`(公開名一覧 + parametrize)。

## 段階的実装計画(前提依存 → Pointer。spike-first)

> **着手は前提依存から。** 慎重さを速度に優先。OS injection 不採用・component-level 経路・right-click の可否は実機 spike で確かめてからフル実装。

0. **(前提)** dash(userspace)open/close と UI introspection を別途設計・実装(別ドキュメント / 別 Step)。これが無いと以降の e2e が組めない。
1. **decompile 最新化 & spike**: `just decompile` で `decompiled/` 再生成(現スナップショットは数週間前)。使い捨て bridge で **(a) hover → highlight / (b) SimulatePress → 押下 / (c) ScrollRect スクロール / (d) right-click** を実機確認。d 不可なら contingency。
2. **proto**: 作成 → `just gen-proto` → Python 生成物 diff を同 commit。
3. **C# Core + Core Test** を並列実装(Kestrel round-trip / Fake)。
4. **Python `PointerClient` + grpclib round-trip test**。
5. **Mod `FrooxEnginePointerBridge`**(spike 成果の正典化)+ smoke + SafeShutdown 登録。
6. **CLI `resoio pointer`** + CLI test。
7. **e2e harness**(前提依存の dash open + introspection を使って UI を出し、要素位置を知り、指して効果確認)。
8. 契約ピン更新 + `just run` 全 green → commit。

作業ブランチは `feature/<日付>/pointer-modality` を `main` から分岐。commit は関心事単位(`feat(proto/pointer)` 等)。

## リスク・未確定事項

- **前提依存(dash open/close + UI introspection)が未設計** → これらを先に解く。Pointer 単体は実機検証不能。
- **Wine 下の OS injection 不採用は確度高だが未実測** → spike(step 1)で component-level の動作を最初に確認。
- **right-click の component-level 経路が薄い**(`IUISecondaryActionReceiver` 実装 UI が限定) → contingency: (a) RightClick を `Unimplemented` stub で v1 から外す、(b) `InteractionHandler.OpenContextMenu` reflection をポインタ位置で起動(ContextMenu と機構共有)。spike 結果でユーザー確認。
- **Camera 解像度 != window 解像度** → `PointerState.width` / `height` でスケール情報を返す。
- **engine 内部 field / 型名のドリフト** → reflection 解決失敗時 fail-fast、e2e に「実機で 1 操作が効く」を pass 判定に含める。
- **userspace overlay UI 対応**は dash open/close と密接。world-space UI を主にするか overlay を主にするかは spike で確定。

## エージェントチーム実行フロー(着手時)

`CLAUDE.md`「エージェントチーム戦略」準拠。proto / C# Core / Python が論理的に独立なので並列度を最大化(spike は orchestrator 主導、フェーズ2で `spec-driven-implementer` × N と `spec-test-author` × N を disjoint 並列、proto を触る implementer は 1 つに限定、フェーズ5で `code-quality-reviewer` を独立モジュール毎に並列、最後に `docstring-author`)。

## 検証(エンドツーエンド)

- **単体 / 結合**: `just run`(format → gen-proto → build → test → type)全 green。Core は Kestrel in-process gRPC + 実 UDS、Python は grpclib in-process(testing-strategy 準拠、3rd-party / engine 表面 mock 禁止)。
- **e2e(Claude 自動駆動 / 前提依存あり)**: `just deploy-mod` → `just resonite-start` → **dash open + UI introspection で操作対象 UI と要素位置を用意** → `python/tests/e2e/pointer.py` → `just resonite-stop`。move → hover highlight / click → 反応 / scroll → 移動 を Camera 録画 + `just log` で確認。状態を変える操作は「逆 → 本 → 逆 → 本」の対称 4 step で no-op と区別。
- 成功条件: 実機 UI に対し pixel (x,y) 指定の hover / click / scroll が効くことを観測。
