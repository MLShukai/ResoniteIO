# CLAUDE.md

このファイルは Claude Code (claude.ai/code) がこのリポジトリを扱う際のガイダンスを提供する。

## プロジェクト概要

`resonite-io` は **Resonite を AI エージェントの実行環境として使うための双方向 IPC ブリッジ**。Resonite クライアント側で動く C# Mod (`ResoniteIO`、BepisLoader) と Python パッケージ (`resoio`) を、gRPC over Unix Domain Socket で接続する monorepo。

設計思想は **強化学習的な抽象化ではなく、リアルタイムロボティクス的な設計**。`Observation/Action` の抽象は持たず、`Camera` / `Speaker` / `Microphone` / `Locomotion` / `Manipulation` といったモダリティ単位で独立した非同期ストリームを提供する。音声系は方向別に `Speaker` (Resonite → Python) と `Microphone` (Python → Resonite) を分離。RL の `step()` 同期はスコープ外で、Python 側ライブラリで上に構築されるべきもの。

C# 実装は **Core/Mod 二層構成**: コア機能 (gRPC server / Service / proto handler / 各モダリティのドメインロジック) は **Resonite に一切依存しないピュアライブラリ `ResoniteIO.Core`** に置き、BepInEx Plugin `ResoniteIO` は engine bridging のみを担う薄いアダプタとする。依存方向は **Core ← Mod** で逆参照禁止。Python (`resoio`) も Resonite 非依存。詳細は [feedback_core_mod_layering.md](memory/feedback_core_mod_layering.md) 参照。

C# / Python 両側のモジュール構造は **モダリティ単位でミラーリング** する。新規モダリティは Core 側 `<Modality>Service` + Mod 側 `FrooxEngine<Modality>Bridge` のペアで追加する。

詳細な背景・スコープ・採用技術・段階的実装計画は [resonite_io_plan.md](resonite_io_plan.md) を **必ず** 参照すること（Step 0〜8、決定事項一覧、リスク欄を含む）。

## メモリ・スキル参照

セッション開始時、または規約が関係しそうなタスクに着手する前に [memory/MEMORY.md](memory/MEMORY.md) のインデックスを確認すること。タスク発火型の手順 (環境セットアップ / debug / 新規モダリティ追加) は [.claude/skills/](.claude/skills/) 配下に置き、Claude harness が trigger に応じて自動で読み込む。

新しい規約・フィードバックが判明したら `memory/feedback_*.md` を追加し `MEMORY.md` に 1 行リンクを張る。プロジェクト固有の規約は `memory/` に集約し、harness が自動ロードする `~/.claude/projects/.../memory/` パスは使わない (git 管理を優先する方針)。memory ディレクトリを repo root に置いているのは、Claude Code の安全機能で `.claude/` 配下への write permission が通らないため。

## 開発原則

LLM コーディングで陥りがちなミスを減らすための行動指針。**慎重さを速度に優先する** バイアスを置いている。trivial なタスクでは判断で柔軟に運用してよい。

### 1. 実装前に考える

**仮定を勝手に置かない。混乱を隠さない。トレードオフを表に出す。**

実装に着手する前に:

- 仮定は明示的に述べる。不確かなら質問する
- 複数の解釈が成り立つなら全部提示する。黙って 1 つに決めない
- もっと単純な方法があるなら言う。正当な理由があれば押し返す
- 何かが不明瞭なら止まる。何が混乱の原因か名指しして質問する

### 2. シンプルさを優先

**問題を解く最小限のコード。投機的な実装はしない。**

- 頼まれていない機能は足さない
- 単発の用途しかないコードに抽象化は入れない
- 要求されていない「柔軟性」「設定可能性」は持ち込まない
- 起こり得ないシナリオに対するエラーハンドリングは書かない
- 200 行書いて 50 行で済むなら書き直す

自問する: 「これをシニアエンジニアが見たら過剰だと言うか?」Yes なら単純化する。

### 3. 外科的な変更

**触る必要があるものだけ触る。自分が散らかしたものだけ片付ける。**

既存コードを編集するとき:

- 周辺コード・コメント・整形を「ついでに改善」しない
- 壊れていないものをリファクタしない
- 自分なら違う書き方をするとしても既存スタイルに合わせる
- 無関係な dead code に気付いたら指摘する。勝手に消さない

自分の変更が orphan を生んだ場合:

- 自分の変更が原因で未使用になった import / using / 変数 / 関数は消す
- 元から dead だったコードは、頼まれない限り消さない

判定基準: diff の全行が、ユーザーの要求から直接トレースできるか?

### 4. ゴール駆動の実行

**成功条件を定義する。検証できるまでループする。**

タスクを検証可能なゴールに変換する:

- 「バリデーションを足す」→「不正な入力に対するテストを書いて通す」
- 「バグを直す」→「再現するテストを書いて通す」
- 「X をリファクタする」→「変更前後でテストが通ることを確認する」
- 「proto に field を追加する」→「`just gen-proto` を回し、両言語の生成物 diff を含め、wire 互換テストが通る」

複数ステップのタスクでは短い計画を先に提示する:

```text
1. [手順] → 検証: [チェック]
2. [手順] → 検証: [チェック]
3. [手順] → 検証: [チェック]
```

強い成功条件があれば独立してループできる。弱い条件 (「動くようにする」) は確認を繰り返す羽目になる。

**この原則が効いている指標**: diff から不要な変更が減る、過剰実装による書き直しが減る、ミスの後ではなく着手前に確認質問が出る。

## プロジェクト状況

**現状: 当初計画の Step 0〜7 がすべて完了**。Step 0 = Docker 化開発環境、Step 1 = mod/python/proto スケルトン、Step 2 = `Connection.Ping`、Step 3 = Camera server-streaming RPC、Step 4 = Locomotion client-streaming RPC、Step 5 = Speaker server-streaming RPC、Step 6 = Manipulation Grab/Release unary RPC、Step 7 = Microphone client-streaming RPC。加えて当初の 8-step 計画外の userspace / world 系モダリティ **Display / World / ContextMenu / Dash / Inventory / Cursor** (いずれも unary RPC 中心) も実装済み。Cursor は desktop カーソル位置を正規化座標で set/get するモダリティ (cursor lock で位置を保持)。ContextMenu は engine-native 配置に揃えてあり (旧 `Pointer.Target = null!` 回避策を撤去)、`open` は現カーソル位置に開く (中央表示は事前に `cursor.set_position(0.5, 0.5)`)。**auto-close (視点移動でメニューが閉じる) の注意**: この経路は engine の exit-lerp が担うが、それには「実 OS カーソル (active screen pointer)」が必要。Wine/Proton 上では OS injection 不可で cursor lock の forced position は active pointer とは見なされないため、agent 操作では exit-lerp が発火しない (実機検証済み)。agent は `close()` で明示的に閉じる。詳細: [feedback_cursor_lock_mechanism.md](memory/feedback_cursor_lock_mechanism.md)。

詳細な Step 履歴・RPC 仕様・Bridge クラス命名等は [resonite_io_plan.md](resonite_io_plan.md) を正規とする。新規モダリティ追加の規約は [.claude/skills/add-new-modality/](.claude/skills/add-new-modality/) に集約。

実装済みの主要要素 (概観):

- 開発環境: `compose.yml` / `.devcontainer/` (devcontainer.json / Dockerfile / initialize.sh) / `justfile` / `scripts/host_agent.py` + `scripts/resonite_cli.py` (container ↔ host Resonite bridge)
- C# Core (`mod/src/ResoniteIO.Core/`): モダリティ単位で IF と Service を `<Modality>/` 配下にまとめる (Connection / Camera / Speaker / Microphone / Locomotion / Manipulation / Display / World / ContextMenu / Dash / Inventory / Cursor)。共通基盤として `UnixNanosClock` / `ILogSink` (`Logging/`) と汎用 gRPC host `GrpcHost` (`Hosting/`)
- C# Mod (`mod/src/ResoniteIO/`): `ResoniteIOPlugin` (OnEngineReady で GrpcHost 起動、SafeShutdown で partial-failure / ProcessExit を統合) / `Bridge/FrooxEngine<Modality>Bridge`
- Python (`python/src/resoio/`): モダリティごとに `<Modality>Client` (`ConnectionClient` / `CameraClient` / `SpeakerClient` / `MicrophoneClient` / `LocomotionClient` / `ManipulationClient` / `DisplayClient` / `WorldClient` / `ContextMenuClient` / `DashClient` / `InventoryClient` / `CursorClient`) と `_socket.py` / `_generated/`
- CLI (`python/src/resoio/cli/`): action 名 flat command (`resoio ping` / `record` / `mic` / `locomotion` / `manipulate` / `display` / `world` / `context-menu` / `dash` / `inventory` / `cursor`)。subgroup 階層化はしない。`record` は `--video` / `--audio` の filter フラグ (両方未指定で muxed mp4/mkv) で Camera/Speaker を取得する Resonite→Python 方向、`mic` は Microphone を Python→Resonite に流す独立コマンド、`cursor` は desktop カーソルを set/center/get する
- proto: `proto/resonite_io/v1/{connection,camera,locomotion,speaker,microphone,manipulation,display,world,context_menu,dash,inventory,cursor}.proto`
- UDS path: 本番 gRPC IPC は `$HOME/.resonite-io/`、debug bridge は `$HOME/.resonite-io-debug/`

リポジトリ実構造:

```text
resonite-io/
├── compose.yml / .devcontainer/ (devcontainer.json / Dockerfile / initialize.sh) / justfile / .env.example / buf.yaml
├── resonite_io_plan.md        # 全体計画書 (Step 0〜8、決定事項、リスク)
├── proto/resonite_io/v1/      # *.proto (single source of truth)
├── mod/                       # C# 側 (.NET 10、Core/Mod 二層)
│   ├── src/ResoniteIO.Core/   # pure library (Resonite 非依存)
│   ├── src/ResoniteIO/        # BepInEx adapter (engine bridging のみ)
│   └── tests/                 # Core.Tests (Kestrel ラウンドトリップ) / Tests (smoke) / manual/
├── python/                    # Python 側 (uv + betterproto2 + grpclib)
│   └── src/resoio/            # Client 群 + cli/ + _generated/
├── scripts/                   # gen_proto / decompile / host_agent / resonite_cli
├── memory/                    # プロジェクト memory (MEMORY.md index + feedback_/reference_*.md + agents/<agent-type>/)
├── gale/                      # Gale (Resonite mod manager) profile (gitignore)
├── decompiled/                # ILSpy 出力 (gitignore)
└── .claude/                   # skills/ + agents/ + commands/ + settings*.json
```

## ツーリング

- タスクランナー: **`just`** (`set dotenv-load := true` で `.env` から `ResonitePath` 等を読む)。ビルド / テスト / gen-proto は **コンテナ内で実行する前提**
- C# (mod): **.NET 10 SDK** + BepisLoader 公式 Template (`dotnet new bep6resonite`) 準拠。フォーマッタ `csharpier`、配布 `tcli` (`.config/dotnet-tools.json` の local tool)。テスト `xunit`、`Nullable=enable` + `TreatWarningsAsErrors=true`
- Python (resoio): **`uv`** + Python `>=3.12`。gRPC は **`betterproto2[grpclib]`** (async)。`pyright` strict、`ruff` (line-length 88、ダブルクォート、isort + combine-as-imports)、`pytest` + `pytest-asyncio`/`pytest-cov`/`pytest-mock`
- proto: C# 側は csproj の `<Protobuf>` で `dotnet build` 時に自動生成 (Server スタブのみ、commit しない)。Python 側は `just gen-proto` で `python/src/resoio/_generated/` に書き、**commit する**。lint は `buf` (`SERVICE_SUFFIX` / `RPC_REQUEST_STANDARD_NAME` / `RPC_RESPONSE_STANDARD_NAME` を except)
- Docker 開発環境: `debian:bookworm-slim` ベースの単一 image に .NET / uv / protoc / dotnet local tools / pre-commit を同梱。`compose.yml` を `.devcontainer/devcontainer.json` から参照する devcontainer 方式で開く。詳細セットアップは [setup-resonite-env skill](.claude/skills/setup-resonite-env/SKILL.md) 参照
- CI / リリース: `.github/workflows/` に品質ゲート (`pre-commit` / `test` (Python 3.12-3.14) / `type-check` / `dotnet` / `proto-check`) と tag-driven リリース (`publish.yml`) を配置。`v*` tag の push で Thunderstore mod + PyPI パッケージを同時公開する。手順は [RELEASE.md](RELEASE.md) と [release-resonite skill](.claude/skills/release-resonite/SKILL.md) 参照 (正規 version = csproj `<Version>`、`python/pyproject.toml` は lockstep)

## コマンド

`just` レシピが C# / Python / proto をまたぐ作業をラップする。主要レシピ:

| レシピ                                                  | 役割                                                                                                                    |
| ------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `just run`                                              | `format` → `gen-proto` → `build` → `test` → `type` を直列実行 (コミット前の必須 check)                                  |
| `just gen-proto`                                        | `.proto` から Python 側コードを生成 (C# 側は csproj が build-time 生成)                                                 |
| `just deploy-mod`                                       | mod build + `gale/BepInEx/plugins/ResoniteIO/` へ DLL+PDB 配置                                                          |
| `just log`                                              | host 側で `gale/BepInEx/LogOutput.log` を tail -F (print-debug の主経路)                                                |
| `just decompile`                                        | Resonite first-party DLL を ILSpy で `decompiled/` に展開                                                               |
| `just init`                                             | host 側で初回 setup (docker / docker compose v2 検出 / `.env` 作成・検証 / `ResonitePath` 検証 / Gale プロファイル確認) |
| `just check-gale`                                       | Gale プロファイルに必須 plugin が揃っているか検証                                                                       |
| `just host-agent` / `just resonite-{start,stop,status}` | container ↔ host Resonite 起動・停止 bridge (debug 用)                                                                  |

全レシピは `just --list` で取得可能。サブコマンド分離 (`just py-test` / `just mod-build` 等) は troubleshooting 時のフォールバック。

**`.proto` を変更した場合は必ず `just gen-proto` を再実行し、生成物の差分も同じ commit に含める** (CI で再生成 diff を取るチェックを入れる予定)。

## 実行環境

**ホスト側に必要なものは `docker` / `docker compose v2` / `just` に加えて devcontainer を開く手段 (VS Code の Dev Containers 拡張 / Zed / `@devcontainers/cli`) のいずれか**。.NET / uv / protoc / pre-commit はすべてコンテナ内に閉じている。Resonite 自体は host で起動 (Steam)、コンテナは build / deploy 専用。`.env` の `ResonitePath` に Resonite 実行ファイルディレクトリ絶対パスを指定。

開発環境の入り方は devcontainer 方式:

1. host で一度 `just init` (docker / docker compose v2 検出、`.env` 作成・検証、`ResonitePath` 検証、Gale プロファイル確認)
2. devcontainer を開く — **VS Code**: 「Dev Containers: Reopen in Container」、**Zed**: dev container として開く、**CLI** (任意・headless / CI 用): `devcontainer up --workspace-folder .` → `devcontainer exec --workspace-folder . bash`
3. devcontainer が自動実行する: `initializeCommand` (host 側・作成前) が `~/.resonite-io{,-debug}/` を 0700 で作成し host UID/GID を `.env` に記録 (build-arg でコンテナ user に一致、deploy 成果物が host 所有になる)、`postCreateCommand` (container 内・作成後) が `scripts/container-init.sh` を実行 (`dotnet tool restore` + `uv sync` + `pre-commit install` + Claude settings symlink)
4. コンテナ内ターミナルで `just gen-proto` / `just build` / `just deploy-mod` / `just run` 等を従来どおり実行
5. 後片付けは VS Code / Zed の devcontainer 停止操作、または CLI なら `docker compose` を直接叩く

初回環境構築 (Docker / Gale プロファイル / Steam Launch Options) と debug 経路 (`just log` / `just decompile` / container ↔ host bridge) の詳細は専用 skill に集約済み:

- 初回セットアップ: [setup-resonite-env skill](.claude/skills/setup-resonite-env/SKILL.md)
- デバッグ手順: [debug-resonite-mod skill](.claude/skills/debug-resonite-mod/SKILL.md)

ライセンス・ToS: Resonite は明示的な研究用 bot 規定なし。慣習的には黙認〜歓迎 (詳細は [resonite_io_plan.md](resonite_io_plan.md) §7)。商用化や派手な公開実験を始める前にユーザーに確認する。

## コーディング規約とテスト方針

各モダリティは他のモダリティに依存しない (片方だけ使う構成も可)。グローバルな clock / barrier は持たず、各ストリームに **タイムスタンプ** を付与し、必要な同期は受信側で行う。通信データ型は **pyright strict をクリアする型付け**。

C# / Python の詳細な規約 (名前空間、Core/Mod 責務、Bridge engine thread dispatch、`Nullable` / warnings-as-errors、private prefix + `__all__`、proto 命名 except 等) は [add-new-modality skill](.claude/skills/add-new-modality/SKILL.md) に集約。**テスト方針** (real resource 優先、3rd-party / FrooxEngine 表面 mock 禁止、4 区分、Kestrel in-process gRPC + grpclib end-to-end の典型形等) は [testing-strategy skill](.claude/skills/testing-strategy/SKILL.md) を必ず参照する。

### カプセル化

- クラスの内部実装の詳細や属性は、基本的にすべて private (Python `_` prefix、C# `private` / `internal`) にする
- 外部から参照する必要がある属性のみ public にする
- Python: `__init__` で設定される属性は原則として private とする
- C#: コンストラクタで設定されるフィールドは原則として `private readonly`、必要に応じて `init`-only public プロパティで公開する

例 (Python):

```python
class Example:
    def __init__(self, dim: int):
        self._dim = dim  # private
        self._client = SomeClient(dim)  # private
```

例 (C#):

```csharp
public sealed class Example
{
    private readonly int _dim;
    private readonly SomeClient _client;

    public Example(int dim)
    {
        _dim = dim;
        _client = new SomeClient(dim);
    }
}
```

### Python の private モジュール規約

`python/src/resoio/` 配下のモジュールは **テストの有無** で `_` prefix の有無を決める:

- テストを書かない (真に private な実装) → ファイル名に `_` prefix を付ける (例: `_socket.py`)
- テストを書く / 書かれている → `_` prefix を **付けない** (例: `camera.py`, `microphone.py`)
- 外部公開は親 `__init__.py` の `__all__` で別軸として集約管理する。モジュール名から `_` を外すことと「外部公開」は独立した判断

## Git 運用

### ブランチ

- `main`: 開発の主軸
- 作業用ブランチの命名規則: `<種別>/<日付>/<内容>` (例: `feature/20260509/grpc-skeleton`、`fix/20260509/uds-permission`)
  - 種別: `feature`, `fix`, `refactor`, `docs`, `chore`
- 必ずブランチ上で commit する (`main` に直接 commit しない)。作業ブランチは `main` から分岐
- `main` へのマージはユーザーが判断・実行する
- リリースは `chore/<日付>/release-vX.Y.Z` で version bump → `main` マージ → `release/X.Y` 上で `vX.Y.Z` tag を push して `publish.yml` を発火させる。詳細は [RELEASE.md](RELEASE.md) / [release-resonite skill](.claude/skills/release-resonite/SKILL.md)

### コミットメッセージ

`<種別>(<スコープ>): <内容>` の形式に従う。

- 種別: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`
- スコープ: `mod`, `python`, `proto`, `scripts`, `ci`, `docs` などの top-level、または `mod/camera`、`python/locomotion` のようなモダリティ単位
- 例: `feat(mod/connection): UDS gRPC server をエンジン起動時に bind` / `feat(python/camera): server-streaming で RGB フレームを受信`

## 自走開発フロー

### 基本サイクル

1. **要件確認**: [resonite_io_plan.md](resonite_io_plan.md) の該当 Step を読み、スコープと未解決事項を把握する
2. **作業ブランチ作成**: `main` から `<種別>/<日付>/<内容>` で分岐
3. **作業はコンテナ内で行う** (devcontainer に入って attach。ビルド/テスト/gen-proto はすべてコンテナ内)
4. **実装**: コードを書く (C# / Python / proto)
5. **検証**: proto 変更時は `just gen-proto` を再実行。**コミット前に必ず `just run` を実行する** (全パス green)
6. **コミット**: 細かい単位で、1 コミットに複数の関心事を混ぜない
7. 4-6 を機能単位で繰り返す

### 判断基準

- plan に明記されている内容はそのまま実装する
- plan に記載がない実装の詳細は自分で判断してよい
- plan の未決事項に関わる部分は、合理的なデフォルトで実装し、コミットメッセージに判断理由を記載
- 型チェックエラー (pyright strict / C# warnings-as-errors) を放置しない
- スコープ外 (RL `step()`、マルチエージェント、ワールド作者向け API 等) は実装しない

## エージェントチーム戦略

「エージェントチームで行う」という指示があり、具体的な手順が示されていない場合、以下のサイクルに従う。利用可能なエージェントは [.claude/agents/](.claude/agents/) のもの。各エージェントの責務は **厳密に分離** されており、互いの担当領域に踏み込まない:

| エージェント              | 書く対象                                                                                      | 触ってはいけない対象                                             |
| ------------------------- | --------------------------------------------------------------------------------------------- | ---------------------------------------------------------------- |
| `spec-planner`            | 仕様書 (コードなし)                                                                           | コード全般                                                       |
| `spec-driven-implementer` | `mod/src/ResoniteIO.Core/` / `mod/src/ResoniteIO/` / `python/src/resoio/` / `proto/` のコード | `mod/tests/` / `python/tests/` (テストは絶対に編集しない)        |
| `spec-test-author`        | `mod/tests/` / `python/tests/` 配下のテストコード                                             | `mod/src/` / `python/src/` のプロダクションコード                |
| `code-quality-reviewer`   | `mod/src/` / `python/src/` の内部 (public API / proto wire は不変)                            | `mod/tests/` / `python/tests/`、public API、proto wire、CLI 引数 |
| `docstring-author`        | docstring / XML doc / コメント                                                                | ロジック                                                         |

### 実装サイクル

1. **spec-planner**: 要件を分析し、proto → C# Service / Bridge IF → Python Client の 3 層を含む実装計画と仕様書を策定する (コードは書かない)
2. **spec-driven-implementer + spec-test-author**: 仕様を共通の入力として **並列起動**。実装エンジニアは仕様に従って `src/` (proto / C# / Python) を書き、テストエンジニアは仕様に従って `tests/` を書く。テストは仕様書として機能する (実装に引きずられない)
3. **実装修正ループ**: テストが揃ったら、`spec-driven-implementer` がテストを通すように `src/` だけを修正する。**テストコードは絶対に触らない**。テストが間違っていると思われる場合は、orchestrator 経由で `spec-test-author` に質問を回す (テストの修正可否を判定するのは spec-test-author の責務)
4. **テストクリア**: すべてのテストが green になり、`just run` がパスしたら次へ
5. **code-quality-reviewer**: public API / proto wire / Core ← Mod 境界を一切変えずにリファクタリングする (重複排除・簡素化・命名・型精緻化)。`mod/tests/` / `python/tests/` は触らない。各ステップで `just test` を回し green を保つ
6. **docstring-author**: 最後にコメントやドキュメントの追加・更新が必要か確認する

### 並列化 (論理的に可能な最大数で並列実行する)

並列性の最大化はマルチエージェント運用の中心戦略。Agent tool 呼び出しを **1 メッセージに複数並べて発射する** ことで並列実行される。逐次にしてよいのは依存関係がある場合のみ。tool 呼び出しレベルの並列化指針は [/maximize-parallels skill](.claude/skills/maximize-parallels/SKILL.md) を参照。

- **フェーズ 2 (実装 + テスト)**:
  - 1 つの仕様に対して `spec-driven-implementer` と `spec-test-author` は常に並列で 2 つ走らせる
  - 仕様が独立した N 個のモダリティ / モジュールに分割可能なら、各モダリティ毎に `spec-driven-implementer × N` と `spec-test-author × N` の合計 **2N エージェント** を並列起動する (モダリティは互いに独立した非同期ストリームなので、Camera と Locomotion を別 implementer に投げる、proto と C# Core と Python Client を別 implementer に投げる、などが可能)
- **フェーズ 3 (実装修正ループ)**: 独立モジュールごとに `spec-driven-implementer` を並列。テストへの質問が必要なモジュールだけ `spec-test-author` を再起動する
- **フェーズ 5 (リファクタリング)**: 独立モジュールごとに `code-quality-reviewer` を並列起動

並列化の前提:

- 担当領域が disjoint (同じファイルを 2 つのエージェントが同時に編集しない)
- 並列起動した結果は orchestrator が統合する。コンフリクトが起きたら逐次に切り替える
- proto を変更するエージェントは 1 つに絞る (`just gen-proto` の生成物 diff を 1 commit にまとめるため)

### エージェント間通信のルール

エージェント同士は直接通信できない。すべての通信は orchestrator (親 Claude) が中継する:

- 実装エンジニアからテストエンジニアへの質問 → orchestrator が `spec-test-author` を起動して回答を取り、実装エンジニアに渡す
- 仕様の解釈が分かれる場合 → orchestrator がユーザーに明確化を依頼するか、`spec-planner` を再起動して仕様を更新する
- リファクタリングで public API / proto wire / Core ← Mod 境界を変えたくなった場合 → `code-quality-reviewer` は実施せず、改善案として報告。実施判断は orchestrator / ユーザーに委ねる
