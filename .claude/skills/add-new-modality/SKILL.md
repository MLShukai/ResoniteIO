---
name: add-new-modality
description: "Use when adding a new modality to resonite-io — proto, C# Core Service + Bridge IF, C# Mod FrooxEngine bridge, Python client, CLI, tests. Next planned modality is Step 6 Manipulation. Triggers: '新規モダリティ', 'Manipulation', 'IManipulationBridge', 'ManipulationService', 'モダリティを追加', 'add new modality'."
version: 0.1.0
---

# Add a New Modality

resonite-io は **モダリティ単位** (`Camera` / `Speaker` / `Microphone` / `Locomotion` / `Manipulation` / `Display`) で独立した非同期ストリームを提供する。C# 側と Python 側の構造は **モダリティ単位でミラーリング** する。

このスキルは Step 6 (Manipulation) のように **新しいモダリティを最初から追加する** 流れと規約を集約する。

______________________________________________________________________

## 1. ミラーリング規約

| 層      | パス                                                                                             | 命名                                       |
| ------- | ------------------------------------------------------------------------------------------------ | ------------------------------------------ |
| proto   | `proto/resonite_io/v1/<modality>.proto`                                                          | service 名はモダリティ名そのもの           |
| C# Core | `mod/src/ResoniteIO.Core/<Modality>/I<Modality>Bridge.cs`, `<Modality>Service.cs`                | namespace `ResoniteIO.Core.<Modality>`     |
| C# Mod  | `mod/src/ResoniteIO/Bridge/FrooxEngine<Modality>Bridge.cs`                                       | namespace `ResoniteIO.Bridge`              |
| Python  | `python/src/resoio/<modality>.py`                                                                | `<Modality>Client` (async ctx mgr)         |
| CLI     | `python/src/resoio/cli/<action>.py`                                                              | action 名 flat command (`resoio <action>`) |
| Tests   | `mod/tests/ResoniteIO.Core.Tests/<Modality>/*Tests.cs`, `python/tests/resoio/test_<modality>.py` |                                            |

依存方向は **Core ← Mod** で逆参照禁止。Python (`resoio`) は Resonite 非依存。

______________________________________________________________________

## 2. C# 側の規約

### 名前空間と csproj 設定

- Core 側は `ResoniteIO.Core.<Modality>` (cross-cutting utility である `UnixNanosClock` 等は root `ResoniteIO.Core`)、Mod 側は `ResoniteIO.Bridge` (engine 実装) と `ResoniteIO` (Plugin 本体)
- `Nullable=enable` + `TreatWarningsAsErrors=true` を `.csproj` で必ず有効にする

### Service / Bridge の責務分離 (Core/Mod 二層)

- gRPC server は **別スレッドで動作** させ、FrooxEngine 本体スレッドをブロックしない
- Service 実装は Core 側にあり engine を知らないため、engine 依存処理は Bridge IF 経由で同期/非同期にディスパッチする
- 詳細: [`feedback_core_mod_layering.md`](../../memory/feedback_core_mod_layering.md)

### Bridge IF は Core POCO を返す

Bridge IF が proto 型を返すと、Fake bridge が interface 実装で CS0738 fail する。Camera 同様 **Core POCO + Service の MapToProto** で挟むこと。

詳細: [`feedback_bridge_iface_uses_core_poco.md`](../../memory/feedback_bridge_iface_uses_core_poco.md)

### Engine thread dispatch

LocalUser 駆動など FrooxEngine API を呼ぶ箇所 (Mod 側 Bridge 実装) は engine の update tick 上にディスパッチする必要がある:

- **コンポーネントグラフ変更**: `World.RunSynchronously` + `TaskCompletionSource`
- **純粋読み (snapshot)**: 任意スレッドで OK

詳細: [`feedback_bridge_engine_thread_dispatch.md`](../../memory/feedback_bridge_engine_thread_dispatch.md)

### proto 生成と CS0436 警告

- C# 側は `<Protobuf>` ItemGroup により `dotnet build` 時に `Grpc.Tools` が自動生成 (Server スタブのみ、`obj/` 出力で commit しない)
- 配置は **Core 側 `mod/src/ResoniteIO.Core/ResoniteIO.Core.csproj`** に集約
- Mod 側 csproj は Core を `ProjectReference` するだけで proto を直接参照しない
- Core テスト側で Client stub を別生成する関係で **CS0436 (重複型)** が出るため、テスト csproj 限定で `<NoWarn>$(NoWarn);CS0436</NoWarn>` を入れる
- 詳細: [`feedback_grpc_tools_message_duplication.md`](../../memory/feedback_grpc_tools_message_duplication.md)

### gRPC streaming の cancel 例外

`Grpc.AspNetCore + Kestrel UDS` では client cancel が `OperationCanceledException` だけでなく `IOException` で表面化する経路あり。**3 段構え catch** で吸収:

```csharp
try { ... }
catch (OperationCanceledException) when (ct.IsCancellationRequested) { /* expected */ }
catch (IOException) when (ct.IsCancellationRequested) { /* expected */ }
```

詳細: [`feedback_grpc_client_cancel_exception_surface.md`](../../memory/feedback_grpc_client_cancel_exception_surface.md)

### BepInEx mod の transitive DLL 同梱

新規 Core 依存が増えると bin/ に DLL が出ないことがある。`CopyLocalLockFileAssemblies=true` + PostBuild Copy 双方が必要。AspNetCore framework reference は SDK shared framework dir から専用 Target で都度コピー。
詳細: [`feedback_bepinex_transitive_dlls.md`](../../memory/feedback_bepinex_transitive_dlls.md)

______________________________________________________________________

## 3. proto の規約

- `buf.yaml` で `SERVICE_SUFFIX` + `RPC_REQUEST_STANDARD_NAME` / `RPC_RESPONSE_STANDARD_NAME` を except (モダリティ固有ドメイン名を優先する規約)
- service 名はモダリティ名そのもの。message 型は `CameraFrame` 等のドメイン名で命名
- スキーマは **Step ごとに incremental に詰める**
- 詳細: [`feedback_proto_rpc_naming_except.md`](../../memory/feedback_proto_rpc_naming_except.md)

`.proto` を変更したら **必ず** `just gen-proto` を再実行し、Python 生成物 (`python/src/resoio/_generated/`) の差分も同じ commit に含める。

______________________________________________________________________

## 4. Python 側の規約

- パッケージ名は `resoio`、import 名は `resoio`
- PEP 561 typed (`py.typed` 同梱)
- バージョンは `pyproject.toml` の `[project].version` を真値とし、`resoio.__version__` は `importlib.metadata` 経由
- **カプセル化**: クラスの内部実装の詳細や `__init__` で設定される属性は原則 private (`_` prefix)。外部から参照する必要があるものだけ public にする
- **private モジュール規約**: テストを書かないモジュールは `_` prefix、書くモジュールは prefix なし。外部公開は親 `__init__.py` の `__all__` で別軸として集約

### pyright strict と private symbol

`tests/` が strict 除外なので `_` prefix の private 関数を test だけ参照すると **unused 扱い**になる。`__all__` に列挙して回避。

詳細: [`feedback_pyright_unused_private_in_src.md`](../../memory/feedback_pyright_unused_private_in_src.md)

### client-streaming パターン

既存 (Locomotion / Microphone) は **async ctx mgr で client-streaming** を提供。新規モダリティでも同じ pattern に合わせること:

```python
async with client.stream() as session:
    await session.send(chunk)
summary = session.summary  # 結果は ctx exit 後に取得
```

参考: [`feedback_locomotion_external_input.md`](../../memory/feedback_locomotion_external_input.md), [`feedback_microphone_engine_tap.md`](../../memory/feedback_microphone_engine_tap.md), [`feedback_speaker_engine_tap.md`](../../memory/feedback_speaker_engine_tap.md)

______________________________________________________________________

## 5. テスト規約

### 基本原則

- 必要十分なテストのみ。過剰なテストは避ける
- 内部実装の詳細はテストせず、**公開インターフェースと振る舞い**をテストする
- Python のテスト関数に戻り値の型アノテーションは不要

### Python テストレイアウト

`python/tests/` は `python/src/resoio/` の構造を 1 対 1 でミラーリング:

- `src/resoio/foo.py` ↔ `tests/resoio/test_foo.py`
- `tests/` 直下に置くのは `__init__.py` / `helpers.py` / `conftest.py` / `manual/` のみ
- 1 ファイル 1 テストを原則とする

### 実践的なテスト

- 実オブジェクト・実入出力で振る舞いを検証する
- できる限りモックを使わない。テスト用の実データ (一時ファイル等) で代替できるなら実データを使う
- モック許容範囲: 外部 API (Resonite クライアント本体・gRPC peer)、ファイルシステム/DB など再現困難な依存
- 内部モジュール同士の結合はモックせず実結合
- 複数パラメータは `@pytest.mark.parametrize`
- `pytest_mock` を使用 (`mocker.Mock`)。`unittest.mock` は使わない
- 共有モックは `tests/conftest.py` のフィクスチャに集約

### gRPC のテスト

- 単体: 生成された dataclass メッセージに対する純粋関数のテスト (mock 不要)
- 結合: in-process で gRPC server/client を立てて UDS で繋ぐパターンを優先 (`grpclib` で簡単に書ける)。Resonite 本体には依存させない
- Resonite 接続を伴う end-to-end は `python/tests/e2e/` に置き、`pytest --ignore=python/tests/e2e` で自動収集対象外にする

### C# 側

- xunit
- **Core 側** (`ResoniteIO.Core.Tests`): Resonite 非依存なので **Kestrel ラウンドトリップを含む統合テストを書ける**。tmp_path UDS に GrpcHost を bind、`Grpc.Net.Client` から実 RPC を投げて検証
- **Mod 側** (`ResoniteIO.Tests`): FrooxEngine 依存があるため smoke test と Bridge adapter ロジック (engine API を呼ばない範囲) のみ。実 engine を要するシナリオは `python/tests/e2e/<modality>.py` を Claude が host-agent 経由で自動駆動する。Claude が自動化できない確認のみ `mod/tests/manual/` に markdown で残す

### Test-only Service host

GrpcHost に mount しない wave の Core 側 modality は、**test 専用の最小 Kestrel host を分離** して round-trip テストを書く。
詳細: [`feedback_test_only_service_host.md`](../../memory/feedback_test_only_service_host.md)

### Streaming pacing tolerance

pacing 検証は理論値 +2 ぶんの上限スラックで書く (`+1 edge frame + 1 boundary slip`)。
詳細: [`feedback_streaming_fps_limit_test_tolerance.md`](../../memory/feedback_streaming_fps_limit_test_tolerance.md)

______________________________________________________________________

## 6. SafeShutdown chain への組み込み

`ResoniteIOPlugin` は `SafeShutdown` 経由で partial-failure / `AppDomain.ProcessExit` どちらも同じ Dispose chain に集約する。順序は:

```
receiver → camera → display → locomotion → microphone → speaker → connection
```

新規モダリティを足すときは、依存方向 (例: 出力系より入力系を先に止めるか) を考慮して chain の適切な位置に挿入する。

______________________________________________________________________

## 7. CLI 規約

- `python/src/resoio/cli/` 配下に **action 名 flat command** で 1 ファイルずつ (`ping` / `capture` / `record` / `mic` / `locomotion` / `display` 形式)
- subgroup 階層化はしない (例: `resoio voice` ではなく `resoio mic`)
- 単体テストは `python/tests/resoio/cli/test_<action>.py`

______________________________________________________________________

## 8. ステップごとの incremental 実装

1. proto を先に書いて `just gen-proto` で Python 側生成
2. C# Core 側に `I<Modality>Bridge` + `<Modality>Service` を実装
3. Core Test で Kestrel ラウンドトリップを書き、Fake Bridge で Service の挙動を検証
4. Python `<Modality>Client` を実装、in-process gRPC で round-trip テストを書く
5. Mod 側 `FrooxEngine<Modality>Bridge` を実装 (engine API 呼び出し)
6. Mod 側 smoke test を足し、`SafeShutdown` chain に登録
7. CLI を追加
8. `just run` (format → gen-proto → build → test → type) が green になることを確認してコミット
9. docs を更新: `docs/api/<modality>.md` を作成 + `mkdocs.yml` の nav に追記 + `docs/architecture/modalities.md` のモダリティ表に行追加 → [`write-docs`](../write-docs/SKILL.md) skill 参照

______________________________________________________________________

## 9. 関連 memory (まとめ)

### コア規約

- [`feedback_core_mod_layering.md`](../../memory/feedback_core_mod_layering.md) — Core/Mod 二層構成
- [`feedback_bridge_iface_uses_core_poco.md`](../../memory/feedback_bridge_iface_uses_core_poco.md) — Bridge IF は POCO
- [`feedback_bridge_engine_thread_dispatch.md`](../../memory/feedback_bridge_engine_thread_dispatch.md) — engine thread dispatch

### proto / build

- [`feedback_proto_rpc_naming_except.md`](../../memory/feedback_proto_rpc_naming_except.md)
- [`feedback_grpc_tools_message_duplication.md`](../../memory/feedback_grpc_tools_message_duplication.md)
- [`feedback_bepinex_transitive_dlls.md`](../../memory/feedback_bepinex_transitive_dlls.md)
- [`feedback_netstandard20_polyfills.md`](../../memory/feedback_netstandard20_polyfills.md)

### gRPC streaming

- [`feedback_grpc_client_cancel_exception_surface.md`](../../memory/feedback_grpc_client_cancel_exception_surface.md)
- [`feedback_streaming_fps_limit_test_tolerance.md`](../../memory/feedback_streaming_fps_limit_test_tolerance.md)
- [`feedback_test_only_service_host.md`](../../memory/feedback_test_only_service_host.md)

### Python 規約

- [`feedback_pyright_unused_private_in_src.md`](../../memory/feedback_pyright_unused_private_in_src.md)
- [`reference_generated_proto_layout.md`](../../memory/reference_generated_proto_layout.md)
- [`reference_betterproto2_packaging.md`](../../memory/reference_betterproto2_packaging.md)

### 先行モダリティの実装パターン

- [`feedback_locomotion_external_input.md`](../../memory/feedback_locomotion_external_input.md) — client-streaming + repeater
- [`feedback_speaker_engine_tap.md`](../../memory/feedback_speaker_engine_tap.md) — server-streaming + audio tap
- [`feedback_microphone_engine_tap.md`](../../memory/feedback_microphone_engine_tap.md) — client-streaming + virtual capture device

### Engine API

- [`feedback_frooxengine_settings_api.md`](../../memory/feedback_frooxengine_settings_api.md) — Settings API 経路と FPS 制御の制約
