---
name: pattern-engine-input-mode-tests
description: Engine 入力 (レイ / raycast / ScreenActive 等) に依存する RPC のテスト変換パターン (Manipulation Grab レイベース化で確立)
type: feedback
---

Engine 入力依存の RPC (例: cursor-ray grab) をテスト化するときの確立パターン:

- **レイ計算 / raycast / ScreenActive 判定は fake に持ち込まない**。fake (`I<Modality>Bridge`) は結果だけ script する (`GrabSucceeds=true/false` = hit/miss)。レイ経路の検証は実機 e2e (cursor 照準 → 呼び出し → well-formed assert、`grabbed=True` は assert しない) + manual に分担する。
- **モード拒否 (VR 等) は新規例外型ではなく既存 NotReady 例外 + message** で表現され、Service が FailedPrecondition に翻訳する。テストは status code + message substring (例: `"desktop"`) のみ pin。完全一致は禁止。
- **削除した CLI flag は SystemExit 契約ピン** (`@pytest.mark.api_contract`、parse_args が SystemExit) で静かな復活を検出する。
- **proto field 削除は reserved 欠番コメント付きで field map から落とす** (test_proto_contract.py に「N は旧 X、再利用禁止」コメントを残す)。
- e2e で cursor 保持を使う step は `finally` で `cursor.release()` を best-effort 実行し、他 step / 他シナリオに保持を残さない。

**Why:** Part B (Grab レイベース化, 2026-06-10) で仕様 §7 として確定し、実装と並行で書いて全 green。
**How to apply:** 今後の engine 入力依存モダリティ (照準系 / 入力モード分岐のある RPC) の breaking change テストで同じ分担を踏襲する。
