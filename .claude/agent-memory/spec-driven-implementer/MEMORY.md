# Memory Index — spec-driven-implementer

## Feedback

- [check HEAD before implementing](feedback_check_head_before_implementing.md) — On a feature branch matching the task name, verify prior commits haven't already landed the work before re-implementing.
- [grpc-tools message-type duplication in test projects](feedback_grpc_tools_message_duplication.md) — Core で Server stub、Tests で Client stub を別生成すると message 型が CS0436 で重複警告。テスト csproj 限定で NoWarn 抑制する。
- [Engine.OnShutdown subscription deferred to Step 3](feedback_engine_onshutdown_deferred.md) — mod 停止は AppDomain.ProcessExit best-effort。Engine.OnShutdown 経由のより早い hook 調査は Step 3 で再評価。
- [BepInEx mod の transitive DLL 同梱](feedback_bepinex_mod_transitive_dlls.md) — CopyLocalLockFileAssemblies=true + PostBuild Copy 双方が必要。framework reference は別経路で要 E2E 検証。
- [proto RPC envelope naming except](feedback_proto_rpc_naming_except.md) — RPC_REQUEST/RESPONSE_STANDARD_NAME は buf.yaml で except 済み。streaming のデータ型はモダリティ固有名でよい。
- [streaming fps_limit テストの tolerance](feedback_streaming_fps_limit_test_tolerance.md) — pacing 検証は理論値 +2 ぶんの上限スラックで書く。「+1 edge frame + 1 boundary slip」。
- [Bridge での engine thread ディスパッチ](feedback_bridge_engine_thread_dispatch.md) — コンポーネントグラフ変更は World.RunSynchronously + TaskCompletionSource、純粋読みは任意スレッド。
- [uv tool install resoio version skew](feedback_uv_tool_install_resoio.md) — `uv tool install --editable` ignores uv.lock; isolated env picks betterproto2 0.10 against compiler 0.9 stubs and ImportErrors.
- [BepInExRenderer は framework 配置](feedback_bepinex_renderer_as_framework.md) — `ResoniteModding-BepInExRenderer` は plugin dir を作らず `Renderer/BepInEx/core/` に framework を deploy する。check-gale は `BepInEx.Preloader.dll` で確認。
- [netstandard2.0 の polyfill 要件](feedback_netstandard20_polyfills.md) — Span/BinaryPrimitives は `System.Memory` NuGet、HashCode.Combine は無いので手組み hash で代替。
- [test 専用 service host pattern](feedback_test_only_service_host.md) — SessionHost に mount しない wave の Core 側 modality は、test 専用の最小 Kestrel host を分離して round-trip テストを書く。
- [FrooxEngine Settings API](feedback_frooxengine_settings_api.md) — `Settings.GetActiveSetting<T>() / UpdateActiveSetting<T>()` が公式、内部 `RunSynchronously` で engine thread に dispatch。`Engine.Current.GetCoreSetting` は存在しない。foreground fps は engine 公式経路で制御不可。
- [InterprocessLib callback signature](feedback_interprocesslib_callback_signature.md) — `Messenger.ReceiveValueArray<T>` の callback は `Action<T[]?>`、namespace は DLL 名と独立して `InterprocessLib`。static event は Dispose で必ず -=。
- [pyright unused private in src/](feedback_pyright_unused_private_in_src.md) — tests/ が strict 除外なので `_` prefix の private 関数を test だけ参照すると unused 扱い。`__all__` に列挙して回避。
- [asyncio add_reader テストの key pacing](feedback_asyncio_add_reader_test_pacing.md) — os.pipe stdin + add_reader 駆動 CLI の round-trip テストは keystroke を `asyncio.sleep` で pace しないと exit key が drain される。
- [locomotion HeadFacingRotation で body-relative 成立](feedback_locomotion_headfacing_body_relative.md) — 2026-05-19 実機 \[LocomotionPos\] 計測で V_B / V_D の角度差 87.1° を観測、`HeadFacingRotation` 経路が正しいと定量確認。
- [gRPC client cancel exception surface](feedback_grpc_client_cancel_exception_surface.md) — Grpc.AspNetCore + Kestrel UDS では client cancel が OperationCanceledException だけでなく IOException で表面化する経路あり、3 段構え catch で吸収。
- [pre-commit stash で staged 内容が消える事象](feedback_precommit_stash_silent_unstage.md) — 並列 worktree で pre-commit 経路が "Skipped" 連発 + exit 1 を返した場合、`git status` で再 stage して再 commit する。
