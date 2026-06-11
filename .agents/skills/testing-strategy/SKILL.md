---
name: testing-strategy
description: resonite-io のテスト戦略。real resource を最優先し、自前 ABC (I<Modality>Bridge / ILogSink 等) のみ fake 可、3rd-party / FrooxEngine 表面 (grpclib / Kestrel internals / BepInEx / FrooxEngine.* / Elements.Core.* / betterproto2 internals / Task.Delay / asyncio.sleep 等) のモックは禁止。4 区分 (unit / integration-with-fakes / integration-real / manual・e2e)、tests ミラーレイアウト (C# Core.Tests / Python tests/resoio)、書いてはいけないテスト、公開 API 契約ピン例外、Kestrel in-process gRPC + 実 UDS + UnixNanosClock + 実 protobuf wire、mutation testing、Wine + Linux Resonite と engine thread 周りの実行環境クセ。テストコードを書く／壊れた manual シナリオを調査する／pytest / xUnit 周りを設定する前に読む
---

# resonite-io テスト方針リファレンス

本 skill は手元で書き始める前にざっと読む「実行可能なまとめ」として位置づける。
背景となる学びの蓄積は [memory/](../../../memory/) 配下のファイル群に集約されている。

## 哲学

resonite-io は **proto over UDS gRPC + Resonite engine** 結合が支配的な monorepo。「動くテスト」ではなく「**実環境の振る舞いを保証するテスト**」を優先する。

3rd-party / engine の表面をミラーした fake は、その挙動に対する **自分の仮定** をテストするだけで、上流変更を検出できない (GOOS / Freeman & Pryce: "Don't mock what you don't own")。fake が drift して CI 緑でも実 Resonite で死ぬ事故を防ぐため、**実 resource を最優先** とする。

### 検証対象の優先順位

1. **実 resource** — `tmp_path` で実 file I/O、Kestrel in-process gRPC server + 実 grpclib client での proto ラウンドトリップ、実 UDS への bind、`UnixNanosClock` の実時刻、実 protobuf serialization、tempfile に書いた実 PCM/WAV / 実画像 fixture を実コーデックに通す
2. **自前 ABC の fake** — resonite-io が自分で定義した抽象 (`I<Modality>Bridge` 系: `ICameraBridge`, `ISpeakerBridge`, `IMicrophoneBridge`, `ILocomotionBridge`, `IDisplayBridge`、共通の `ILogSink` 等) の差し替え。**所有しているもの** は OK
3. **3rd-party / engine 表面のモック → 禁止**:
   - C# 側: `Microsoft.AspNetCore.*`, `Grpc.Core.*`, `Grpc.AspNetCore.*` の internals、`BepInEx.*`, `HarmonyLib.*`, `MonoMod.*`, `FrooxEngine.*`, `Elements.Core.*`, `ProtoFlux.*`, `World`, `Engine`, `Slot`, `User`, `Task.Delay`, `Thread.Sleep`, `DateTime.UtcNow`
   - Python 側: `grpclib.Channel` / `grpclib.client.Stream`, `betterproto2` の internals, `asyncio.sleep`, `time.time_ns`, `os` の I/O 関数, `socket` 直叩き
   - 必要なら integration-real に分類する
4. **自分のコードの内部関数モック → 禁止**: `GrpcHost._BindAsync` / `CameraService._OnFrameInternal` のような内部メソッドを直接 `mocker.patch` / Moq で置き換える行為。リファクタで壊れるだけで何も保証しない

## 基本原則

- 必要十分なテストのみを記述する。過剰なテストは避ける
- 内部実装の詳細はテストしない。公開インターフェースと振る舞いをテストする
- Python のテスト関数に戻り値の型アノテーションは不要
- C# のテストメソッドは `public async Task` または `public void`、`[Fact]` / `[Theory]` を付ける
- **コードカバレッジは診断であり目標ではない**。Fowler: *"high coverage numbers are too easy to reach with low quality testing"*。100% は赤信号

## テストレイアウト

### Python — `python/tests/resoio/` を `python/src/resoio/` に 1 対 1 でミラー

- `python/src/resoio/camera.py` ↔ `python/tests/resoio/test_camera.py`
- `python/src/resoio/__init__.py` ↔ `python/tests/resoio/test_api_contract.py` (公開 API 契約ピン)
- `python/src/resoio/cli/record.py` ↔ `python/tests/resoio/cli/test_record.py`
- `python/tests/` 直下に置くのは `__init__.py` / `helpers.py` / `conftest.py` / `e2e/` / (必要なら) `fakes/` のみ
- 1 ファイル 1 テストを原則とし、モダリティ単位のミラーを維持する
- `python/tests/e2e/<scenario>.py` は host-agent + live Resonite が必要な end-to-end シナリオ群。`@pytest.mark.e2e` で marker し、デフォルト `pytest` 収集対象外。`just e2e-test` 経由で明示的に実行する。`python/tests/e2e/conftest.py` に `resonite_session` fixture と host-agent 必須チェックを集約

### C# — `mod/tests/ResoniteIO.Core.Tests/` を `mod/src/ResoniteIO.Core/` に 1 対 1 でミラー

- `mod/src/ResoniteIO.Core/Camera/CameraService.cs` ↔ `mod/tests/ResoniteIO.Core.Tests/Camera/CameraServiceTests.cs`
- `mod/src/ResoniteIO.Core/Hosting/GrpcHost.cs` ↔ `mod/tests/ResoniteIO.Core.Tests/Connection/GrpcHostLifecycleTests.cs`
- `mod/tests/ResoniteIO.Core.Tests/Common/` 配下に共通 fixture (Kestrel host harness 等) を集約。fake は `Common/Fakes/<Modality>BridgeFake.cs`
- BepInEx 側 (`mod/src/ResoniteIO/`) は smoke 単位のみ `mod/tests/ResoniteIO.Tests/` で検証 (FrooxEngine 実機が必要な分は manual)

### E2E — `python/tests/e2e/` (Codex 自動駆動が canonical・新規モダリティで必須)

- Resonite 実機を起動して end-to-end で振る舞いを確認するシナリオ群
- **Codex が `scripts/resonite_cli.py` (host-agent bridge) 経由で起動・停止・撮影まで自動駆動する** のが基本路線。新規モダリティの実機検証は `python/tests/e2e/<modality>.py` を pytest harness として書く
- **新規モダリティでは e2e を必ず Codex が実装し、自分で実行して検証する (任意ではない)**。`just test` の green だけで「完了」としない。e2e green + 後述の screenshot 目視まで到達して初めて完了とする (`just resonite-status` で起動可否を事前確認する規約に従う)
- **状態変化を伴う実機操作 (ワールド移動・focus・UI 変化・カメラ描画変化など) は、API 戻り値の assert に加えて `scripts/resonite_cli.py screenshot` (= `python/tests/e2e/<modality>.py` 内の `_screenshot()` ヘルパー) で操作前後の screenshot を撮り、実際に状態が変わったことを目視確認する**。screenshot は `python/tests/e2e/e2e_artifacts/` (gitignore 済) に保存する
- 実機の cloud 依存ステップ (公開セッション一覧/join 等) は対象が不安定なため、候補リトライ + 決定的な fallback (例: 自分の record からの起動) + 空 cloud 時の明示 skip で flaky を避ける
- CI 自動収集対象外 (`require_host_agent` autouse fixture で skip)。`just e2e-test` 経由で明示的に走らせる
- `just deploy-mod` で plugin を配置してから動かす

### Manual — `mod/tests/manual/` (本質的に人間しかできない確認だけ)

- 残すのは Codex が自動化できない検証のみ (Resonite Settings UI でのデバイス手動切替、別アカウントで join しての voice 受信聴取、視覚/聴覚的な品質判断など)
- 新規 markdown 手順書の追加は原則禁止。e2e harness で代替できるか先に検討する

## テスト 4 区分

| 区分                       | 配置                                                                                     | 検証対象                                                                                                                   | モック許容                                                                             |
| -------------------------- | ---------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| **unit**                   | `python/tests/resoio/test_<file>.py`、`mod/tests/ResoniteIO.Core.Tests/<File>Tests.cs`   | 純粋ロジック (proto encoding、timestamp 計算、UDS path 解決、UnixNanosClock の単調性等)                                    | なし                                                                                   |
| **integration-with-fakes** | 同上、`python/tests/fakes/` / `mod/tests/ResoniteIO.Core.Tests/Common/` から fake import | モジュール間結合 (`I<Modality>Bridge` 越し、`<Modality>Service` ↔ Bridge IF の契約)                                        | **自前 ABC のみ** (`FakeCameraBridge`, `FakeSpeakerBridge`, `FakeMicrophoneBridge` 等) |
| **integration-real**       | 同上                                                                                     | adapter / proto wire / Kestrel + grpclib 結合点 (実 in-process server、実 UDS、実時刻)                                     | 原則なし。Kestrel `WebApplication.CreateBuilder` + `IServer` を実 socket で立てる      |
| **e2e (Codex 自動)**       | `python/tests/e2e/`                                                                      | end-to-end (実 Resonite、`just deploy-mod` 後の FrooxEngine + BepInEx + ResoniteIO loaded、Codex が host-agent 経由で駆動) | なし                                                                                   |
| **manual (人間のみ)**      | `mod/tests/manual/`                                                                      | 本質的に人間しかできない確認のみ (UI 手動切替、別アカウントでの voice 受信確認 等)                                         | なし                                                                                   |

新規テストを書く前に区分を決める。3rd-party / engine モックが必要に見えたら integration-real に分類できないか先に検討する。

### integration-real の典型パターン

| 領域                  | real resource                                                                                                                      |
| --------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| filesystem            | Python: `tmp_path` / `tmp_path_factory` (pytest 組込)、C#: `Path.GetTempPath()` + `IDisposable` で cleanup                         |
| UDS                   | `$XDG_RUNTIME_DIR` または `tmp_path` 配下にユニークな socket path を作って実 bind/connect、cleanup を忘れない                      |
| gRPC server (C#)      | `WebApplication.CreateBuilder` + `UseUrls("http://unix:/path/to/sock")` + `MapGrpcService<TService>()`、`StartAsync` / `StopAsync` |
| gRPC client (Python)  | `grpclib.client.Channel` を実 UDS path に向ける。`betterproto2` 生成 stub を素直に使う                                             |
| gRPC server-streaming | server 側 `IAsyncEnumerable<T>` を yield、client 側 `async for` で読む。バッファリングや completion を実観測                       |
| gRPC client-streaming | client 側 `async iter` で送信、server 側 `IAsyncEnumerable<TRequest>` で受信、最終応答を返す                                       |
| protobuf wire compat  | message を実 byte に serialize → 別言語/別バージョンで deserialize して field 一致を確認                                           |
| clock                 | `UnixNanosClock` を直に呼んで単調性 / nanosecond 精度を実観測。時間にまつわるテストはモックせず、短い `await` で十分小さく         |
| log capture           | `ILogSink` 実装を inject して capture する。`ILogger`, `Trace`, `Console.Out` の差し替えはしない                                   |

infra (実 Resonite / Wine / FrooxEngine 等) が未整備の場合、テストは書かず orchestrator に「manual / e2e が必要だが手順 / 環境未整備」と報告する。

### `Task.Delay` / `asyncio.sleep` / `DateTime.UtcNow` のモック禁止

時間に依存するテストは fake clock で書きたくなるが、resonite-io では:

- timestamp の正しさ自体が **仕様**: `Camera` / `Speaker` / `Microphone` のフレームに付与される `monotonic_ns` は `UnixNanosClock` 経由でしか取らない契約を実観測すべき
- fake clock を入れると `UnixNanosClock` の単調性 / overflow 安全性 / nanosecond 精度を **自分の仮定** でしか保証できない
- 短時間の待ち合わせは数十 ms 程度の実 `await` で書き、CI でも安定するように十分大きいマージンを置く

どうしても fake clock が必要なケース (1 時間以上のシナリオなど) は orchestrator に申告する。

## tests/fakes/ の運用 — **自前 ABC のみ**

- 自前 ABC の fake のみ実装する: `FakeCameraBridge` / `FakeSpeakerBridge` / `FakeMicrophoneBridge` / `FakeLocomotionBridge` / `FakeDisplayBridge` / `FakeLogSink` 等
- **禁止カテゴリ** (新規追加禁止):
  - C#: `FakeKestrelServer`, `FakeHttpContext`, `FakeFrooxEngineWorld`, `FakeProtoFluxImpulse`, `FakeBepInEx*`, `FakeHarmonyPatch*`, `FakeDateTime`, `FakeTask*`
  - Python: `FakeGrpcChannel`, `FakeGrpcStream`, `FakeBetterprotoMessage`, `FakeAsyncio*`, `FakeOsSocket`
- 表面拡張が必要に出ても、テストファイル内でサブクラス化せず正典クラス側に追加する
- 共有 fake の置き場所:
  - Python: **現状は test file 内 inline fake で十分** (`_EchoConnection` / `_FakeDisplay` のように `_` prefix の private クラスを各 test file 直書き)。複数 test file から参照したくなった時点で初めて `python/tests/fakes/<modality>.py` に切り出す
  - C#: `mod/tests/ResoniteIO.Core.Tests/Common/Fakes/<Modality>BridgeFake.cs`

## 何をテストするか / しないか

### 書く

- 正常系: 期待通りの入力に対する出力 (Camera ストリームが N フレーム流れる、Locomotion で 1 RTT 内に ack が返る、Microphone の sample rate が proto と一致する等)
- 異常系: エラー発生時の例外やメッセージ (**substring** 検証、完全一致は不可)
- 警告: 設定失敗時などの `RuntimeWarning` / `LogLevel.Warning`
- エッジケース: 境界値・空入力・巨大入力 (フレーム rate 0 / 巨大、PCM 音声の境界長、UDS path の長さ制限)
- proto wire 不変条件: field 番号、message 名、enum 値の固定 (`api_contract` マーカー)

### 書かない (marginal value ゼロ — 削除対象)

- **継承の追試**: `assert issubclass(MyError, RuntimeError)` / `Assert.IsAssignableFrom<RuntimeError>(...)` を、`class MyError(RuntimeError):` / `class MyError : RuntimeError` のために書く。pyright / C# コンパイラと言語仕様が既に保証している
- **import 可能性の追試**: `assert X is not None` を import 直後に書く / `Assert.NotNull(typeof(X))`
- **定数 literal の追試**: `assert TIMEOUT == 5` / `Assert.Equal(5, Timeout)`。意味的不変条件 (例: `assert TIMEOUT >= MIN_RTT`) なら OK
- **getter/setter のラウンドトリップ**: `obj.foo = x; assert obj.foo == x`
- **`__init__` / コンストラクタでフィールド設定されたことだけの確認**
- **framework / stdlib / BCL の動作追試**: `assert json.loads("{}") == {}` / `Assert.Equal(0, new List<int>().Count)`
- **例外メッセージの完全一致**: `assert str(err) == "exact text"` / `Assert.Equal("exact", ex.Message)`。`"keyword" in str(err)` / `Assert.Contains("keyword", ex.Message)` の意味性検証に留める
- **モックの戻り値をそのまま検証するだけ**: モックの動作確認になっている

### 例外: 公開 API 契約ピン

外部利用者が依存する公開 API 名・基底クラス・型エイリアス・proto wire 互換は契約として固定する価値あり (Hyrum's law mitigation)。**唯一の例外** として:

- 集約場所:
  - Python: `python/tests/resoio/test_api_contract.py`
  - C#: `mod/tests/ResoniteIO.Core.Tests/ApiContractTests.cs`
  - proto: `python/tests/resoio/test_proto_contract.py` (wire 互換ピン)
- マーカー:
  - Python: `@pytest.mark.api_contract` (要 `pyproject.toml` 登録)
  - C#: `[Trait("Category", "ApiContract")]`
- 意図を明示: コメントで「これは契約ピンであり振る舞いテストではない」と書く
- 対象例: `resoio.__all__` の整合性、`ResoniteIO.Core` の public surface 列挙、proto field 番号 / enum 値の不変性、公開例外の継承関係

## モック (使用する場合)

### Python

- `pytest_mock` を使用する (`unittest.mock` は使わない。`mocker.Mock` を使う)
- 複数のテストで共有するモックは `python/tests/conftest.py` にフィクスチャとして定義
- 特定のテストでのみモックの振る舞いを変更する場合、フィクスチャの戻り値で上書き
- **モック対象は自前 ABC のみ**。3rd-party 表面 / engine 表面 / 自分のコードの内部関数はモックしない (前述)

### C\#

- xUnit + Moq を使う場合も **自前 ABC のみ** モック対象 (`Mock<ICameraBridge>` 等)
- 共通 fixture は `mod/tests/ResoniteIO.Core.Tests/Common/<Name>Fixture.cs` に集約し、`IClassFixture<T>` で inject
- `FrooxEngine.*` / `BepInEx.*` / `Microsoft.AspNetCore.*` 内部型のモックは禁止

## Kestrel in-process gRPC ラウンドトリップの典型形 (C#)

`<Modality>Service` の振る舞いを **実 wire を通して** 検証するための定型。

```text
1. Arrange:
   - 一時 UDS path を作る (Path.Combine(Path.GetTempPath(), "resoio-test-" + Guid))
   - WebApplication.CreateBuilder() で Kestrel server を組み立て、
     UseUrls("http://unix:" + sockPath) と MapGrpcService<TService>() を呼ぶ
   - StartAsync() で listen 開始
   - GrpcChannel.ForAddress を UDS Connector で開いて生成 stub を inject
2. Act:
   - 生成 stub のメソッド (unary / server-streaming / client-streaming) を呼ぶ
3. Assert:
   - 返ってきた message / stream の中身を実観測 (timestamp の単調性 / field 値 / 完了 status)
4. Cleanup:
   - StopAsync() → channel.Dispose() → File.Delete(sockPath)
   - IAsyncDisposable / IClassFixture で確実に呼ばれる形にする
```

`mod/tests/ResoniteIO.Core.Tests/Common/KestrelTestServer.cs` に基盤クラスとしてまとめる想定。

## Python `grpclib` end-to-end ラウンドトリップの典型形

C# 側の Kestrel server を立てるのが重い場合は、Python 側だけで `grpclib.server.Server` を `<Modality>Service` 風の fake handler とともに立て、`<Modality>Client` の挙動を実 wire で検証する。

```text
1. Arrange:
   - 一時 UDS path を作る (tmp_path / ("resoio-test.sock"))
   - grpclib.server.Server に fake handler (自前 ABC 実装) を bind
   - server.start(path=...) で listen 開始
2. Act:
   - resoio の <Modality>Client (内部で grpclib.client.Channel を実 UDS で開く) を呼ぶ
3. Assert:
   - 返ってきた response / async iterator を実観測
4. Cleanup:
   - server.close() / await server.wait_closed() → unlink path
```

`python/tests/conftest.py` に `uds_server` fixture として共通化する。

## e2e シナリオ (`python/tests/e2e/`)

実 Resonite を起動して end-to-end で振る舞いを確認するシナリオ群。**Codex が host-agent 経由で自動駆動するのが canonical**。`just deploy-mod` → `just resonite-start` → pytest harness が gRPC client / Camera 録画 / `just log` 解析を回す → `just resonite-stop` の流れ。

- 各シナリオは `python/tests/e2e/<scenario>.py` として書き、`require_host_agent` autouse fixture で skip 制御する
- 状態を変える対称 API (Locomotion 前進 → 停止、Display 表示 → 非表示 等) を検証する場合は、起動直後の自然な状態から本命操作を呼んでも no-op と区別できないため、**逆操作 → 本操作 → 逆 → 本** の 4 step で書く。同じペアを 2 回繰り返すことで idempotence も確認できる
- **可視的な状態変化を伴う操作 (ワールド移動・focus・UI 変化等) は、API 戻り値 assert に加えて操作前後で `_screenshot()` (`scripts/resonite_cli.py screenshot`) を撮り、実際に変化したことを目視確認する** (例: `world.py` の join 前後 / focus 前後)。screenshot 検証まで含めて初めて e2e 完了とする
- アーティファクト (録画 MP4 / screenshot 等) は `python/tests/e2e/e2e_artifacts/` (gitignore 済み) に保存する

`mod/tests/manual/` には Codex が自動化できない確認のみを残す (本質的に人間しかできない確認 = 別アカウントでの voice 受信聴取・視覚/聴覚品質判断等)。新規追加する前に e2e harness で代替できないか必ず検討する。

Resonite 起動 / 停止 / ログ tail の手順は [/debug-resonite-mod skill](../debug-resonite-mod/SKILL.md) を参照。

## pytest / xUnit 設定の含意

### Python

- `--strict-markers` のため、`@pytest.mark.<name>` は事前に `pyproject.toml` の `[tool.pytest.ini_options] markers` に登録する必要がある。未登録だとテストはエラーになる
- 利用マーカー: `api_contract` (公開 API 契約ピン)、`e2e` (host-agent + live Resonite 必須、`just e2e-test` 経由でのみ収集)。`integration_real` / `manual` のような横断マーカーは付けない (レイアウト分離だけで十分)
- `pytest-asyncio` を使うため `asyncio_default_fixture_loop_scope = "function"` 想定。`asyncio_mode = "auto"` でも明示的に `@pytest.mark.asyncio` でも可

### C# (xUnit)

- `<Nullable>enable</Nullable>` + `<TreatWarningsAsErrors>true</TreatWarningsAsErrors>` がテストアセンブリにも効く。`Mock<T>` の return-null は CS8603 を起こすので注意
- proto 生成物はテストアセンブリでも build-time に出る。`dotnet build mod/tests/ResoniteIO.Core.Tests/` で再生成される
- `[Theory]` の `MemberData` で生成ロジックを書く時に LINQ allocation が気になるなら `[InlineData]` で十分

## 推奨ツール: mutation testing

「fake が drift しているか」を **経験的に** 検証する手段として、Python は `mutmut` ([github.com/boxed/mutmut](https://github.com/boxed/mutmut))、C# は `Stryker.NET` ([stryker-mutator.io/docs/stryker-net/introduction](https://stryker-mutator.io/docs/stryker-net/introduction/)) が有効。

- 仕組み: source を機械的に corrupt し (`+` → `-`, `>` → `>=`, `true` → `false` 等)、テストが mutant を検出するか測る。**survive した mutant** は、その箇所のテストが弱い (しばしば fake が mutant を吸収している) 合図
- CI 必須ではない。リリース前 / 四半期程度の頻度で十分
- 100% mutation score を狙わない。コストが super-linear
- 用途は弱いテストの削除と強いテストの追加判断。target metric にしない
- 適用優先: 純粋ロジック (UnixNanosClock、proto encoding、UDS path 解決) → adapter 層 (`<Modality>Service`、`<Modality>Client`)

## 実行環境の注意点

### Wine + Linux で動く Resonite (manual / e2e)

Resonite は Linux では Steam Proton (Wine) 経由で動く。container ↔ host bridge を通して操作する:

- container 内から `just resonite-start` / `just resonite-stop` を叩くと、host 側 `scripts/host_agent.py` 経由で Steam が起動 / 停止する
- BepInEx のログは host 側 `gale/BepInEx/LogOutput.log` に出る。container 内から `just log` で tail -F できる
- UDS path は host から見て `$HOME/.resonite-io/`、container からは bind-mount された同 path。permission は 0700 必須 (devcontainer の `initializeCommand` で事前作成済み)
- mod 配置は `just deploy-mod` で `gale/BepInEx/plugins/ResoniteIO/` に DLL + PDB を書き込む形

### Resonite engine thread / SafeShutdown

- `FrooxEngine.World` を触る Bridge メソッドは engine update thread でしか呼べない。`World.RunSynchronously` でマーシャルする
- `OnEngineReady` で GrpcHost を bind し、`SafeShutdown` (BepInEx ProcessExit / 通常の Quit) で確実に Stop されるシーケンスは contract。Manipulation などの新規モダリティを追加する際にも、partial-failure を SafeShutdown が拾えるかを必ず確認する
- gRPC handler 側で engine thread 必要な操作を sync 待ちすると engine が止まる。`EngineCompletionSource` (= TaskCompletionSource を engine thread から SetResult する) パターンで書く

### container ↔ host のテスト実行

- C# / Python の自動テスト (`just test` 配下) は **すべて container 内で実行**。host 側に .NET / uv を入れない方針
- manual シナリオ (実 Resonite 必須) は host で Resonite が立ち上がる必要があるので、container から `just resonite-start` で host へ起動指示を出す
- proto 変更時は `just gen-proto` を container 内で流してから commit する。生成物の diff が必ず同 commit に入ること (CI の `proto-check` workflow が再生成 diff を検証する)

## 参考文献

本方針の根拠となった主要文献:

- [Martin Fowler: On the Diverse And Fantastical Shapes of Testing (2021)](https://martinfowler.com/articles/2021-test-shapes.html) — pyramid / honeycomb / trophy の整理、sociable vs solitary
- [Kent C. Dodds: Write tests. Not too many. Mostly integration.](https://kentcdodds.com/blog/write-tests) — testing trophy
- [André Schaffer (Spotify): Testing of Microservices](https://engineering.atspotify.com/2018/01/testing-of-microservices) — honeycomb shape
- [Sebastian Bergmann: Do not mock what you do not own](https://thephp.cc/articles/do-not-mock-what-you-do-not-own) — GOOS 原則
- [James Shore: Testing Without Mocks: A Pattern Language](https://www.jamesshore.com/v2/projects/nullables/testing-without-mocks) — Infrastructure Wrapper + Narrow Integration Test
- [Kent Beck: Test Desiderata](https://testdesiderata.com/) — Predictive vs Fast の trade-off
- [Hillel Wayne: Some tests are stronger than others](https://buttondown.com/hillelwayne/archive/some-tests-are-stronger-than-others/) — marginal value の見方
- [Hillel Wayne: In Defense of Testing Mocks](https://buttondown.com/hillelwayne/archive/in-defense-of-testing-mocks/) — mock を併用する条件
- [Mark Seemann: Test trivial code](https://blog.ploeh.dk/2013/03/08/test-trivial-code/) — 公開 API 契約ピンの根拠 (反対意見も含めて)
- [Martin Fowler: Test Coverage](https://martinfowler.com/bliki/TestCoverage.html) — 100% は赤信号
- [grpc-dotnet testing docs](https://learn.microsoft.com/en-us/aspnet/core/grpc/test-services) — ASP.NET Core gRPC service の in-process テストパターン
- [grpclib examples](https://github.com/vmagamedov/grpclib/tree/master/examples) — Python async gRPC server / client 構築例
- [Stryker.NET](https://stryker-mutator.io/docs/stryker-net/introduction/) — .NET 向け mutation testing
