---
name: cli-design
description: "resoio CLI (python/src/resoio/cli/) の設計・出力規約。新コマンド追加や --format / 出力形式を扱う前に読む。argparse thin module 構成、flat command 命名、--format human|json (構造化出力)、cli/output.py シリアライザ、pid/path-only コマンド、interactive 除外、exit code / stderr / stdout 規約を集約。Triggers: 'CLI コマンドを追加', 'resoio cli', '--format', 'json 出力', 'output.py', 'to_jsonable', 'emit', 'CLI 設計', 'structured output', 'machine-readable'."
version: 0.1.0
---

# resoio CLI の設計規約

`resoio` CLI (`python/src/resoio/cli/`) の構造と出力規約を集約する。新しいコマンドを足すとき、または `--format` / 出力形式を扱うときに読む。モダリティ追加全体の流れは [`add-new-modality`](../add-new-modality/SKILL.md) §7 が入口で、CLI の詳細はこの skill が正規。

## 1. argparse の構成

- **thin module**: 1 コマンド = 1 ファイル (`python/src/resoio/cli/<action>.py`)。各モジュールは `register(subparsers, common)` と `async def _run(args)` を公開し、`register` 内で `parser.set_defaults(func=_run)` する。
- **新コマンドの登録**: `cli/__init__.py` の `_COMMAND_MODULES` に追記するだけ。`main()` → `_build_parser()` が各モジュールの `register` を呼ぶ。
- **heavy import は遅延**: gRPC stack / numpy / 生成スタブの import は `_run` (や分岐先) の中で行う。`resoio --help` と shell 補完を速く保つため、module top では import しない。
- **共通親 parser**: `_build_common_parent()` が `-s/--socket` 等の全コマンド共通フラグを持ち、各コマンドが `parents=[common]` で継承する。**nested subparser は argparse の仕様で親を継承しないので、各 leaf に `parents=[common]` を再アタッチする** (cursor/display/context-menu/dash/world)。

## 2. flat command 命名

- **action 名の flat command** で並べる (`resoio ping` / `record` / `mic` / `grab` / `display`)。
- **subgroup 階層化はしない** (`resoio voice mic` ではなく `resoio mic`)。詳細は [`add-new-modality`](../add-new-modality/SKILL.md) §7。
- positional `action` + 前後自由なフラグ (例: `grab`) か、nested subparser (例: `world` / `dash`) かはコマンドの性質で選ぶ。flat 設計 (positional action) を選んだら subparser 化して文法を変えない。

## 3. 出力規約 (最重要)

人間可読 (default) と機械可読を **`--format human|json`** で切り替える。

### `--format` を付けるコマンド / 付けないコマンド

- **構造化データを返すコマンドにのみ** `--format` を付ける。**共通親 parser には付けない** (carve-out にまで漏れるため)。
  - top-level コマンド: `register` 内で `output.add_format_argument(parser)` を 1 回呼ぶ。
  - nested コマンド: `fmt = output.build_format_parent()` を作り、**結果を返す leaf** だけ `add_parser(..., parents=[common, fmt])` で付ける。
- **`--format` を付けない (carve-out)**:
  - **pid / path を 1 つ返すだけ** → 値を 1 行 stdout に出すだけ (`shutdown`/`terminate` は pid、`screenshot`/`record`/`world thumbnail` は保存した絶対パス)。
  - **interactive** (`drive` / `grab interactive` / `inventory` REPL/TUI) → 構造化出力なし、従来どおり human のみ。
- flat 設計のため `--format` が parser 全体に乗り、一部 action では無意味になる場合 (`grab interactive`)、その action で `is_structured(args.format)` を検知して **exit 2 + stderr で明示拒否** する (黙って無視しない)。

### 入出力チャネルの規約

- 成功/失敗は **exit code**、エラーメッセージは **stderr**、結果は **stdout**。
- json は **stdout に 1 ドキュメントのみ**。binary を stdout に流すモード (`-o -`) とは排他 (パス行などを混ぜない)。
- human モードは原則 **バイト単位で不変** (既存テストが契約を pin)。挙動を変える場合はテストとあわせて更新する。

### exit code

- `0` 成功 (および `BrokenPipeError` で stdout が早閉じされたパイプ) / `1` 実行時エラー / `2` 引数・バリデーションエラー / `130` KeyboardInterrupt。

## 4. シリアライザ `cli/output.py`

stdlib のみ (yaml 等の追加依存は持たない)。公開 API:

| 関数                          | 役割                                                            |
| ----------------------------- | --------------------------------------------------------------- |
| `add_format_argument(parser)` | `--format {human,json}` (default `human`) を 1 つ追加           |
| `build_format_parent()`       | nested leaf 用に `--format` だけ持つ parent を返す              |
| `is_structured(fmt)`          | `fmt == "json"`                                                 |
| `to_jsonable(obj)`            | 再帰正規化 (下記)                                               |
| `render(payload, fmt)`        | json 文字列 (human は `ValueError`)                             |
| `emit(payload, fmt)`          | stdout に 1 ドキュメント書き出し (`BrokenPipeError` は握り潰す) |

### 配線パターン

```python
async def _run(args):
    from resoio.cli.output import emit, is_structured
    from resoio.<modality> import <Modality>Client
    async with <Modality>Client(args.socket) as client:
        state = await client.<rpc>()
    if is_structured(args.format):
        emit(state, args.format)      # wrapper dataclass / proto Message をそのまま渡す
    else:
        print(_format_state(state))   # 既存テキスト経路 (不変)
    return 0
```

- **payload は wrapper dataclass / betterproto2 Message をそのまま `emit` に渡す**。`to_jsonable` が `dataclasses.fields` で **snake_case フィールド名 + 宣言順** に展開する。明示 dict を組むのは合成・flatten・計算値 (例: `rtt_ms`) が要るときだけ。
- **`Message.to_dict()` は使わない** (camelCase になり default 値を落とす)。

### `to_jsonable` の落とし穴 (dispatch 順が load-bearing)

- **enum は `.value` でなく `.name`**。betterproto2 enum は `IntEnum` で `.value` は無意味な int。enum 判定は int 判定より **前**。
- **bool は int より前**に通す (bool は int の subclass、後だと `True`→`1` になる)。
- **bytes / bytearray / numpy は `TypeError`**。バイナリは payload に入れない (loud に失敗させる)。
- 大きな int (`unix_nanos` ~1.7e18) はそのまま正確に round-trip する。

### ファイル保存系 (`screenshot` / `record` / `world thumbnail`)

`-o` 規約を統一する: `-o -` → stdout に raw バイナリ (パス行なし) / `-o path` → そのファイル / **`-o` 省略 → カレントに日付ファイル** (`<name>_YYYYMMDD_HHMMSS.<ext>`)。**ファイル保存時は `os.path.abspath(path)` を 1 行 stdout に出す** (機械可読・`--format` 不要)。

## 5. テスト

`testing-strategy` skill を必ず参照。CLI テストの典型形:

- `python/tests/resoio/cli/test_<action>.py` に、**実 `grpclib.server.Server` + 実 UDS + inline fake `<Modality>Base`** を立てて `_amain(_build_parser().parse_args(argv))` を駆動する (grpclib/betterproto2 は mock しない)。
- json ケース: `["--format","json", ...]` を流し `capsys` で stdout を捕捉、`json.loads` で payload を assert。**stdout が 1 ドキュメントのみ**・enum は name 文字列・大 int 正確・非 ascii 保持 (`ensure_ascii=False`) を確認。
- human ケースは原則不変で残す。挙動を変えたコマンドだけ更新する。
- argparse usage エラー (exit 2) は `parse_args` の `SystemExit.code` で pin する。

## 6. ドキュメント

新コマンド / 出力形式を変えたら `docs/cli.md` を更新する ([`write-docs`](../write-docs/SKILL.md) 参照)。
