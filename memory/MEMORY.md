# Memory Index

resonite-io プロジェクトの規約・知見・ユーザーの好みを記録するインデックス。詳細は各ファイルを参照。

タスク発火型の手順 (環境セットアップ / debug / 新規モダリティ追加) は [`.claude/skills/`](../.claude/skills/) 配下に置き、Claude harness が trigger に応じて自動で読み込む。

## Skills

- [`setup-resonite-env`](../.claude/skills/setup-resonite-env/SKILL.md) — 初回環境構築、Gale プロファイル、Steam Launch Options、UDS パス
- [`debug-resonite-mod`](../.claude/skills/debug-resonite-mod/SKILL.md) — print-debug + ログ tailing、decompile、container ↔ host Resonite bridge
- [`add-new-modality`](../.claude/skills/add-new-modality/SKILL.md) — 新規モダリティ追加 (proto + Core + Mod + Python + CLI + tests)
- [`github-ops`](../.claude/skills/github-ops/SKILL.md) — gh CLI で PR / issue を作成・レビュー、ブランチ push、`gh auth` 設定
- [`testing-strategy`](../.claude/skills/testing-strategy/SKILL.md) — real resource 優先のテスト方針、4 区分、Kestrel in-process gRPC + grpclib e2e、mock 禁止対象
- [`merge-main`](../.claude/skills/merge-main/SKILL.md) — PR 前に main を作業ブランチへ取り込み、コンフリクト解消
- [`edit-dot-claude`](../.claude/skills/edit-dot-claude/SKILL.md) — `.claude/` 配下を /tmp 経由で編集して permission prompt を抑える手順
- [`maximize-parallels`](../.claude/skills/maximize-parallels/SKILL.md) — 独立な tool 呼び出しを 1 メッセージで並列発火する判定基準
- [`write-docs`](../.claude/skills/write-docs/SKILL.md) — ドキュメントサイト (MkDocs Material + mkdocstrings) の配置・preview/build・API ページ規約・モダリティ追加時の docs 手順
- [`release-resonite`](../.claude/skills/release-resonite/SKILL.md) — version bump + tag push で Thunderstore mod + PyPI を同時公開、一回限りの setup

## Feedback (project-wide convention / 落とし穴)

### Core / Mod 二層・Bridge 設計

- [Core/Mod 二層構成](feedback_core_mod_layering.md) — コアは Resonite 非依存ライブラリ、mod は engine bridging のみの薄いアダプタ。proto/Service は Core、Bridge 実装は mod。
- [Bridge IF は proto 型ではなく Core POCO を返す](feedback_bridge_iface_uses_core_poco.md) — Fake bridge が interface 実装すると CS0738 で fail。Camera 同様 Core POCO + Service の MapToProto で挟む。
- [Bridge での engine thread ディスパッチ](feedback_bridge_engine_thread_dispatch.md) — コンポーネントグラフ変更は World.RunSynchronously + TaskCompletionSource、純粋読みは任意スレッド。
- [Connection Bridge 導入時に proto を変えない](feedback_session_bridge_no_proto_change.md) — Step 2 で Bridge IF 注入のみに留め Ping proto は据え置いた判断。波及コストを測る習慣の根拠。
- [FrooxEngine Settings API](feedback_frooxengine_settings_api.md) — `Settings.GetActiveSetting<T>() / UpdateActiveSetting<T>()` が公式、内部 `RunSynchronously` で engine thread に dispatch。foreground fps は engine 公式経路で制御不可。
- [SaveRecord は upload task を await する](feedback_record_save_await_upload_task.md) — `RecordManager.SaveRecord` は upload task を enqueue して即返すだけ。`RecordSaveResult.task.Task` を await しないと直後の GetRecordAtPath/GetRecords で record が見えない (e2e でのみ顕在化)。DeleteRecord(Record) は durable。

### モダリティ実装パターン

- [Camera v2 制約集約](feedback_camera_v2_constraints.md) — Renderite framebuffer 直取り経路の確定アーキ、Wine sandbox 制約、InterprocessLib / OverlayCamera / Settings API の落とし穴を 1 本に集約。
- [Locomotion ExternalInput 経路の落とし穴](feedback_locomotion_external_input.md) — stateful repeater / Reset RPC / disconnect 検知 / pitch 符号 / `AccessTools.FieldRefAccess` の generic 引数順 / velocity 単位元 / Move body-local 変換 (HeadFacingRotation) / Camera 既存 bug を集約。
- [Locomotion HeadFacingRotation で body-relative 成立](feedback_locomotion_headfacing_body_relative.md) — 2026-05-19 実機計測で V_B / V_D の角度差 87.1° を観測、`HeadFacingRotation` 経路が正しいと定量確認。
- [Speaker engine tap と方向別 modality 分割](feedback_speaker_engine_tap.md) — Audio は Speaker/Microphone に方向別分離、Speaker は `AudioOutputDriver.AudioFrameRendered` を HarmonyLib Postfix で tap、WASAPI thread の hot path 設計と SafeShutdown 順序。
- [Microphone engine tap](feedback_microphone_engine_tap.md) — Microphone は `AudioInput` 派生 + `AudioSystem.RegisterAudioInput` で完結。`MonoSample` (Elements.Assets) 固定、`UnregisterAudioInput` 不在の制約、ring buffer + Locomotion 流 self-rescheduling repeater 設計、UI 手動切替方針。
- [Dash overlay は ContextMenu と別系統](feedback_dash_overlay_vs_contextmenu.md) — ESC の dash は `Userspace.UserspaceWorld` 配下の `UserspaceRadiantDash`。UI 要素は言語非依存の `Slot.ReferenceID` + `LocaleStringDriver.Key` で識別 (`Text.LocaleContent` は setter 専用)。pixel 直指しは不採用。
- [Grabber engine 経路 (旧称 Manipulation)](feedback_grabber_engine_api.md) — Grab/Release は `InteractionHandler.Grabber.Grab(point,radius)`/`Release()` (掴むと HolderSlot へ reparent し手に自動追従、edge-triggered one-shot)。hand-pose は TrackedDevicePositioner が毎フレーム上書きし注入不可でスコープ外。ContextMenu と同形の unary RPC、home に grabbable 無く positive grab は manual。
- [Cursor set は one-shot warp](feedback_cursor_lock_mechanism.md) — `SetMousePosition` warp (Wine では no-op) + 一時 `RegisterCursorLock` → settle 確認後に即 unregister。位置は保持しない (マウストラップ解消)。Wine の menu-at-cursor は同一操作内のみ有効。正規化 \[0,1\] 座標。

### proto / build

- [proto RPC envelope naming except](feedback_proto_rpc_naming_except.md) — RPC_REQUEST/RESPONSE_STANDARD_NAME は buf.yaml で except 済み。streaming のデータ型はモダリティ固有名でよい。
- [grpc-tools message-type duplication in test projects](feedback_grpc_tools_message_duplication.md) — Core で Server stub、Tests で Client stub を別生成すると message 型が CS0436 で重複警告。テスト csproj 限定で NoWarn 抑制する。
- [BepInEx mod の transitive DLL 同梱](feedback_bepinex_transitive_dlls.md) — `*.dll` ワイルドカード + deny-list 戦略。Resonite と version 一致なら除外、skew のみ overshadow。
- [Resonite 同梱 DLL 一覧と判断指針](feedback_resonite_bundled_dlls.md) — Resonite 同梱の AspNetCore/Extensions/SignalR DLL 一覧と version、新規 transitive 追加時の checklist。
- [netstandard2.0 の polyfill 要件](feedback_netstandard20_polyfills.md) — Span/BinaryPrimitives は `System.Memory` NuGet、HashCode.Combine は無いので手組み hash で代替。
- [BepInExRenderer は framework 配置](feedback_bepinex_renderer_as_framework.md) — `ResoniteModding-BepInExRenderer` は plugin dir を作らず `Renderer/BepInEx/core/` に framework を deploy する。check-gale は `BepInEx.Preloader.dll` で確認。
- [Resonite 同梱 Google.Protobuf 3.11.4 制約](feedback_protobuf_3_11_4_in_resonite.md) — `UnsafeByteOperations` 等 Protobuf 3.15+ API は TypeLoadException で死ぬ。PluginAssemblyResolver では救えないケースがある。
- [InterprocessLib callback signature](feedback_interprocesslib_callback_signature.md) — `Messenger.ReceiveValueArray<T>` の callback は `Action<T[]?>`、namespace は DLL 名と独立して `InterprocessLib`。static event は Dispose で必ず -=。

### 検証フロー

- [Claude が e2e 検証を回す](feedback_claude_drives_e2e_verification.md) — host-agent bridge で Resonite を Claude が自動起動・停止・撮影できるので、検証は Claude が完結させる。`mod/tests/manual/*.md` は本質的に人間しかできない確認 (UI 手動切替・voice 受信確認等) に限定する。
- [問いかける前に resonite-status を実行](feedback_resonite_status_before_asking.md) — e2e/実機の可否を聞く前に必ず `just resonite-status` を先に実行する。host-agent は常駐前提なので「立ち上げた?」と毎回聞かない。
- [sign-in 必須 e2e は 1 boot に畳む](feedback_e2e_single_signin_per_boot.md) — resonite_session fixture は test ごとに Resonite を再起動するが、連続 2 回目の boot は cloud sign-in が確実に通らない。Inventory/World 等 sign-in を要する e2e は 1 file = 1 test に統合して 1 boot / 1 sign-in に閉じる。

### gRPC streaming テスト

- [streaming fps_limit テストの tolerance](feedback_streaming_fps_limit_test_tolerance.md) — pacing 検証は理論値 +2 ぶんの上限スラックで書く。「+1 edge frame + 1 boundary slip」。
- [test 専用 service host pattern](feedback_test_only_service_host.md) — GrpcHost に mount しない wave の Core 側 modality は、test 専用の最小 Kestrel host を分離して round-trip テストを書く。
- [gRPC client cancel exception surface](feedback_grpc_client_cancel_exception_surface.md) — Grpc.AspNetCore + Kestrel UDS では client cancel が OperationCanceledException だけでなく IOException で表面化する経路あり、3 段構え catch で吸収。

### Python 規約

- [pyright unused private in src/](feedback_pyright_unused_private_in_src.md) — tests/ が strict 除外なので `_` prefix の private 関数を test だけ参照すると unused 扱い。`__all__` に列挙して回避。
- [examples/ では `_` private prefix を使わない](feedback_examples_no_private_prefix.md) — `python/examples/` のサンプルは library ではなく教材。constants も helper も plain 名で書く。library 本体・CLI は従来通り `_` prefix 維持。
- [cross-import されるシンボルに `_` prefix を付けない](feedback_no_private_prefix_on_cross_imports.md) — private モジュール分割時、import される側のシンボルは unprefixed。privacy はモジュール名の `_` が担う。

### ツール・運用

- [dotnet local tools を優先する](feedback_dotnet_local_tools.md) — .NET CLI ツールは `.config/dotnet-tools.json` で管理し、global tool + PATH 操作は避ける。
- [agent model は inherit](feedback_agent_model_inherit.md) — `.claude/agents/*.md` の `model:` は `inherit` 固定。session model は settings.container.json で一元 pin (Fable 5 移行の教訓)。
- [git に --no-pager を付けない](feedback_git_no_pager.md) — 非インタラクティブ Bash では既定で pager を使わないため冗長。
- [docstring-author に cleanup も依頼する](feedback_docstring_author_includes_cleanup.md) — 呼ぶたびに「新規 polish」だけでなく「冗長コメント trim」もスコープに含めて指示する。
- [リリースパイプライン](feedback_release_pipeline.md) — `v*` tag で Thunderstore mod + PyPI を同時公開。正規 version = csproj、CHANGELOG = release notes、net472 除外、namespace mlshukai、repo は MLShukai へ移管。

## Reference

- [Resonite modding wiki 抜粋](reference_resonite_modding.md) — BepisLoader / BepInEx / `bep6resonite` テンプレ / `ResoniteHooks` / Thunderstore packaging の要点と URL マップ。
- [pressure-vessel の filesystem 共有経路](reference_pressure_vessel_paths.md) — `/home/$USER` は通る、`/run/user/<UID>` と `/tmp` は通らない。`~/.resonite-io/` を採用した経緯。
- [WorldManager.WorldFocused 仕様](reference_worldmanager_world_focused.md) — event 発火タイミング、`World.Name` / `User.UserName` の tearing 許容性、Bridge での snapshot 読み戦略。
- [Camera.RenderToBitmap は ~31ms の hard cap](reference_camera_render_to_bitmap_30fps_cap.md) — 640×480 RGBA8 で natural 30fps cap。送信側最適化は基本効かない。
- [Generated proto layout](reference_generated_proto_layout.md) — `python/src/resoio/_generated/` の構造と pyright / ruff / coverage 除外規約。
- [betterproto2 packaging](reference_betterproto2_packaging.md) — `betterproto2` に `[compiler]` extra は存在せず、`betterproto2_compiler` は別 distribution。
- [Load-bearing whys](reference_load_bearing_whys.md) — `mod/src/` + `python/src/resoio/` + Core テストの中で docstring trim 時に削ってはいけない WHY コメント一覧 (Connection loader / Camera v2 renderer bridge / Locomotion / Speaker WASAPI tap / Microphone AudioInput など)。

## サブエージェント由来のメモ

`memory/agents/<agent-type>/` に各サブエージェントが auto memory 機能で書き出した
作業メモが格納されている (各 agent 定義の memory パスもこの `agents/` を指す)。harness が自動ロード
する領域だが、本リポジトリでは git 管理する方針。project-wide 共有価値のあるものは上記 Feedback /
Reference に昇格済みで、各 agent 配下に残るのは当該 agent 固有の作業ノウハウのみ。各 agent ディレクトリ
の `MEMORY.md` がその agent のインデックス。

- [spec-driven-implementer/MEMORY.md](agents/spec-driven-implementer/MEMORY.md) — implementer 固有の作業ノウハウ (HEAD 確認 / pre-commit stash / uv tool skew / test pacing / modality wiring / proto reflection)
- [code-quality-reviewer/MEMORY.md](agents/code-quality-reviewer/MEMORY.md) — レビュー観点 (dedup 閾値 / muxed checklist / pytest -k / skew evidence / Grabber を HandleAsync に統合しない理由)
- [spec-test-author/MEMORY.md](agents/spec-test-author/MEMORY.md) — テスト設計メモ (Locomotion field rename scope / ContextMenu / Dash screens)
- [docstring-author/MEMORY.md](agents/docstring-author/MEMORY.md) — doctest-modules が addopts に無い等の docstring 周辺ノウハウ
