---
name: pytest-k-filter-discoverability
description: 機能単位で stress-run / flake 検出するとき `pytest -k <feature>` を使うことが多い。テスト関数名に共通プレフィックスが付いていないと一部 case が漏れる。
metadata:
  type: reference
---

`pytest -k <feature>` は **テスト関数名の部分一致** でフィルタする。新規モダリティや新機能の test を書くとき、関連テストが全部同じ keyword で hit するように関数名のプレフィックスを揃える。

**Why:** stress-run (`for i in 1..5; do pytest -k muxed; done`) や CI の `-k` フィルタは関数名を見るだけで、ファイル位置やクラスのまとめは見ない。`test_record_both_flags_equivalent_to_no_flag` のように関連機能であっても feature keyword を含まない関数名にすると、stress-run でその case が常に外れる。

**実例:** record-cli の muxed テスト 6 件のうち `test_record_both_flags_equivalent_to_no_flag` は `muxed` という単語を関数名に含まないので、`pytest -k muxed` で 5/6 しか collect されなかった (リポジトリ a6b9d76 時点)。

**How to apply:** レビュー時に「この機能の test を `-k <feature>` で全部 stress-run できるか?」を 1 回確認する。漏れがあればリネーム提案を Should / Nice に出す。テスト書く側にも「機能 keyword を関数名先頭付近に必ず含める」を AGENTS.md か skill に上げる候補。
