---
name: spec-format-conventions
description: resonite-io で orchestrator が要求する詳細仕様書のフォーマット (Part 単位分割 / proto 契約完全形 / テスト観点の削除・書き換え・新規区別 / 仮定一覧)
type: feedback
---

resonite-io の implementer/test-author 並列体制向け仕様書は次の形が求められる (2026-06-10 Cursor 保持 + Grab レイ化改修で確立):

- 独立に実装できる機能 Part ごとに 1 ファイル (`/tmp/resonite-io-specs/spec-part-X-*.md` 等)。依存方向 (Part A 先行 / proto 編集は 1 implementer に限定) を冒頭に明記
- 必須セクション: (1) proto 契約は message/rpc の**完全形** — field 番号・reserved・doc コメント文面まで確定 (コードブロック禁止のため表 + 引用文で表現)、(2) C# Core 契約 (IF シグネチャ + POCO 定義 + 例外→gRPC status mapping 表)、(3) Mod Bridge 挙動 (状態遷移表 + step 列挙、実装自由度は「実装判断に委ねる」と明記)、(4) Python 契約 (シグネチャ + CLI 出力フォーマット確定)、(5) テスト観点を given/when/then で**削除/書き換え/新規を区別した表**に展開、(6) 受け入れ基準 = `just run` 全パス + 実機検証チェックリスト
- e2e テストには必ず「書くが実行は orchestrator が実機で行う」と注記する
- 末尾に「仮定 (planner 判断)」と「実装判断に委ねた点」の番号付き一覧を置き、最終報告でも列挙する
- 上位計画 (承認済み plan ファイル) からの逸脱は不可。計画が曖昧な点は推測で進めず、仮定として明示して仕様に書き込む

**Why:** implementer と test-author が互いの成果物を見ずに並列作業するため、仕様だけで両者の出力が噛み合う粒度が必要。
**How to apply:** マルチエージェント実装サイクルの仕様策定依頼を受けたら、この構成をデフォルトとして使う。
