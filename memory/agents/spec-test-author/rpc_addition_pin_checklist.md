---
name: rpc-addition-pin-checklist
description: モダリティに RPC / field を追加した時に更新すべき契約ピンとテストの定型チェックリスト (Cursor.Release / held で確立)
type: feedback
---

モダリティに RPC や proto field を足す仕様が来たら、振る舞いテストに加えて以下のピンを必ず同時更新する。

**Why:** Cursor 持続保持 (Release RPC + `held` field) の作業で確立。ピン更新漏れは CI で契約テストだけが落ちる形で発覚し、原因切り分けに時間がかかる。

**How to apply:**

- C# `ApiContractTests.cs`:
  - `I<Modality>Bridge_MethodSignatures_MatchSnapshot` に新メソッドの (名前, 引数型) を追加
  - `ResoniteIOV1_GeneratedProtoTypes_MatchSnapshot` に新 request/response 型をアルファベット順で追加 (例: `CursorReleaseRequest` は `CursorReflection` の **後**。"Refl" \< "Rele")
- Python `test_proto_contract.py`: field map に新 field 番号、新 message は空 dict でも追加 + import
- Python の inline fake (`_FakeCursor(CursorBase)` 等) は betterproto2 生成 base の**全 handler を実装必須** (足さないと abstract エラーでテスト全滅)。client テストと CLI テストの両方の fake に追加が要る
- 状態フラグ (held 等) の round-trip は既存 set/get テストへの assert 追加で兼ねられる。fake は「成功時のサーバ報告値」を返す形にする (set→held=True, release→held=False)
- e2e: 状態を保持する機能は「別接続で読み戻して assert」が核心。teardown は `finally` + best-effort 逆操作 (release) で状態を残さない
