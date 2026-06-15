---
name: pattern-public-vs-wire-enum-pins
description: Which contract-pin file an enum goes in depends on whether the public resoio enum is re-exported wire or offset-folded
metadata:
  type: feedback
---

公開 `resoio` enum を contract-pin するとき、**どちらのピンファイルに書くか** は「公開 enum が wire enum をそのまま re-export か / UNSPECIFIED を畳んで offset したか」で決まる。

**Why:** Python 側の modality client には 2 系統の enum がある。

- **re-export 型** (例 `ContactStatus` / `OnlineStatus`): 公開 symbol が生成 wire enum そのもの (`ContactStatus is WireContactStatus`)。response の status をそのまま surface する read-path enum はこれ。値に wire の `UNSPECIFIED=0` を含む。
- **offset-fold 型** (例 `ContactFilter` / World `SessionFilter` / `RecordSource` / `RecordSortDirection`, Session `SessionAccessLevel`): 公開 enum が wire の `UNSPECIFIED=0` slot を documented head (ALL / PUBLIC / DESCENDING など) に畳むので numeric が 1 ずれる。`_<X>_TO_WIRE` dict で name (意味) で map する request-path enum。

**How to apply:**

- re-export 型 → `test_proto_contract.py` の `_EXPECTED_ENUM_VALUES` にだけ書く (wire 値そのものが公開値なので二重ピン不要)。`test_contact.py` で `PublicEnum is WireEnum` を 1 行 unit assert すると re-export 契約が固定できる。
- offset-fold 型 → wire 側を `test_proto_contract.py` の `_EXPECTED_ENUM_VALUES` に、公開側 (ALL=0 等) を `test_api_contract.py` の専用 `test_public_<x>_members_match_snapshot` に **両方** 書く。さらに client の request-path test で `公開 ALL → wire UNSPECIFIED` の name-map を実 UDS 往復で 1 ケース固定する (numeric 一致に頼らない)。
- `__all__` には re-export 型 / offset-fold 型どちらの公開 enum も載るので、`test_api_contract.py` の `_EXPECTED_PUBLIC_NAMES` (alphabetised) に追加する。

Contact の具体: ContactStatus/OnlineStatus = re-export, ContactFilter = offset-fold (ALL/ACCEPTED/REQUESTS = 0/1/2, wire は UNSPECIFIED/ACCEPTED/REQUESTS)。

See \[\[rpc-addition-pin-checklist\]\], \[\[contact-v1-types\]\].
