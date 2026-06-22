---
name: feedback_commentout_test_adjustments
description: 機能を「削除でなくコメントアウト」で外す修正に追従してテストを調整するときの言語別ノウハウ (C# positional record の末尾化 / proto field 契約テストの厳密集合一致 / orphan doc comment 回避)
type: feedback
---

機能を物理削除でなく「コメントアウト」で外す修正 (復活前提) にテストを追従させる際のルール。
2026-06-22 の ResoniteLink 0.6.0 publish 修正 (`fix/20260622/resonite-link-comment-out`) で確立。

**Why:** GameLibs NuGet に実機専用 API が無く publish ビルドが落ちたため、ResoniteLink を全層
コメントアウト。「コメントを外すだけで復活」を保つ必要があり、テストも削除でなくコメントアウトで揃える。

**How to apply:**

- **C# positional record の末尾パラメータ化が最大の事故ポイント**。`SessionSettingsSnapshot(...)` の
  末尾 2 引数をコメントアウトすると、その上の引数 (`IsHost: true,`) のカンマを削って末尾化しないと
  コンパイル不能。src 側 (ReadSettings / record 定義) と tests 側 (FakeSessionBridge の構築) で
  **同一の末尾化**を行う。object initializer (`with { ... }` / `new X { ... }`) の末尾 dangling comma は
  C# では合法なので、そちらはコメントアウトだけで OK (カンマ調整不要)。
- **C# の `///` XML doc を持つメンバをコメントアウトするときは doc ごとブロックコメント `/* */` で囲む**。
  `///` だけ残すと CS1587 (XML comment not on valid language element) が `TreatWarningsAsErrors=true` で
  error 化しうる。`<see cref>` / `<paramref>` が消える型/引数を指している場合も同様にコメントアウト必須。
- **複数行 Fact/メソッドのコメントアウト**: C# は `/* */` ブロックが楽 (ただし内部に `*/` が無いこと確認)。
  Python は docstring `"""` を含むため `"""` 囲みは破綻する → **各行 `#`** でコメントアウトする。
- **proto field 番号契約テスト (`test_proto_contract.py`) は厳密 dict 等値比較** (`_field_numbers(cls) == expected`)。
  消える field の expected エントリは「欠番コメント」を残すだけでは不十分で、行をコメントアウトして
  dict のキーから実除外しないと比較が落ちる (仕様の OQ として明示されることが多い = spec-test-author 判断)。
- **対で揃える**: Python の fake が組む `Pb...(...)` と、期待 dataclass `...(...)` は両方から同じ field を
  コメントアウトしないと等値比較が壊れる。
- **orphan import チェック**: ブロックをコメントアウトしたら、そこだけで使っていた import が orphan に
  なっていないか grep。他ブロックで使われていれば残す (元から他用途の import は触らない)。
- **検証**: ビルド実行が禁止される状況 (implementer が並行 `dotnet build` 中) では、Python は
  `python3 -c "import ast; ast.parse(open(f).read())"` で構文だけ確認 (import/実行を伴わず競合しない)。
  C# は残存 grep をブロックコメント境界の目視で裏取り。
