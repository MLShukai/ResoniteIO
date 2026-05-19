# Memory Index

resonite-io プロジェクトの規約・知見・ユーザーの好みを記録するインデックス。詳細は各ファイルを参照。

## Feedback

- [dotnet local tools を優先する](feedback_dotnet_local_tools.md) — .NET CLI ツールは `.config/dotnet-tools.json` で管理し、global tool + PATH 操作は避ける。
- [git に --no-pager を付けない](feedback_git_no_pager.md) — 非インタラクティブ Bash では既定で pager を使わないため冗長。
- [Core/Mod 二層構成](feedback_core_mod_layering.md) — コアは Resonite 非依存ライブラリ、mod は engine bridging のみの薄いアダプタ。proto/Service は Core、Bridge 実装は mod。
- [Session Bridge 導入時に proto を変えない](feedback_session_bridge_no_proto_change.md) — Step 2 で Bridge IF 注入のみに留め Ping proto は据え置いた判断。波及コストを測る習慣の根拠。
- [Resonite 同梱 Google.Protobuf 3.11.4 制約](feedback_protobuf_3_11_4_in_resonite.md) — `UnsafeByteOperations` 等 Protobuf 3.15+ API は TypeLoadException で死ぬ。PluginAssemblyResolver では救えないケースがある。
- [Camera v2 制約集約](feedback_camera_v2_constraints.md) — Renderite framebuffer 直取り経路の確定アーキ、Wine sandbox 制約、InterprocessLib / OverlayCamera / Settings API の落とし穴を 1 本に集約。
- [Locomotion ExternalInput 経路の落とし穴](feedback_locomotion_external_input.md) — pitch 符号反転 / 30Hz hold-while-streaming / `AccessTools.FieldRefAccess` の generic 引数順 / Camera 既存 bug 等を集約。
- [docstring-author に cleanup も依頼する](feedback_docstring_author_includes_cleanup.md) — 呼ぶたびに「新規 polish」だけでなく「冗長コメント trim」もスコープに含めて指示する。

## Reference

- [Resonite modding wiki 抜粋](reference_resonite_modding.md) — BepisLoader / BepInEx / `bep6resonite` テンプレ / `ResoniteHooks` / Thunderstore packaging の要点と URL マップ。WIP ページの代替参照先も併記。
- [pressure-vessel の filesystem 共有経路](reference_pressure_vessel_paths.md) — `/home/$USER` は通る、`/run/user/<UID>` と `/tmp` は通らない。`PRESSURE_VESSEL_FILESYSTEMS_RW` env は strip される。`~/.resonite-io/` を採用した経緯。
- [WorldManager.WorldFocused 仕様](reference_worldmanager_world_focused.md) — event 発火タイミング、`World.Name` / `User.UserName` の tearing 許容性、Bridge での snapshot 読み戦略。
- [Camera.RenderToBitmap は ~31ms の hard cap](reference_camera_render_to_bitmap_30fps_cap.md) — 640×480 RGBA8 で natural 30fps cap。`b.render_to_bitmap` p50 値。送信側最適化は基本効かない。

## サブエージェント由来のメモ

`.claude/agent-memory/<agent-type>/` に各サブエージェントが auto memory 機能で書き出した
作業メモが格納されている。harness が自動ロードする領域だが、本リポジトリでは git 管理する方針。
タスクが該当サブエージェントの担当範囲にかかるときは個別ファイルも参照する。

- [spec-driven-implementer/MEMORY.md](../agent-memory/spec-driven-implementer/MEMORY.md) — 実装フェーズの feedback (BepInEx 配布、Bridge スレッド戦略、proto 命名規約、テスト tolerance 等)
- [code-quality-reviewer/MEMORY.md](../agent-memory/code-quality-reviewer/MEMORY.md) — レビュー時に拾った reference / project メモ (`_generated/` 除外規約、betterproto2 packaging 等)
- [docstring-author/MEMORY.md](../agent-memory/docstring-author/MEMORY.md) — docstring trim 時に守るべき load-bearing comments の一覧
