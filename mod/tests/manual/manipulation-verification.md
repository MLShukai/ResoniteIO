# Manipulation (FrooxEngineManipulationBridge) ポジティブ grab 検証

`FrooxEngineManipulationBridge` が実機の per-hand `Grabber` を掴ませ、
掴んだ grabbable が **実際に手に追従する** ことを目視で確認する手動検証
手順。自動 e2e ではカバーできない部分のみをここに残す。

実装計画上の対応:

- [resonite_io_plan.md](../../../resonite_io_plan.md) Step 6 (Manipulation) の
  grab/release が **物を実際に掴めること** の目視確認相当
- RPC 経路 (mod ロード / bridge が実 Grabber に到達 / 例外なし / レスポンスが
  well-formed / hand 解決が正しい) の自動検証は
  [python/tests/e2e/manipulation.py](../../../python/tests/e2e/manipulation.py)
  で `just e2e-test manipulation` 経由
- 残るマニュアル要素: **掴める object を用意した上で `grabbed=True` /
  `is_holding=True` になり、掴んだ object が手に視覚的に追従すること**。
  これは本質的に人間しかできない (後述)

## なぜ手動なのか

default の home world は user の手の届く範囲に grabbable object を一切
公開しておらず、grabbable を **決定論的に spawn する API も無い**。その
ため自動 e2e では `grabbed=False` のまま「呼び出し経路が例外なく回る」
ことしか確認できない。掴んだ object が手に追従するか否かは目視判断に
なるため、ポジティブ grab はこの手動手順に分離している。

## 前提

- ResoniteIO mod が Gale 経由起動の Resonite に正しくロードされる状態
  (確認: `just resonite-start` 後に `just log` で `Loading Plugin ResoniteIO`
  が出る)
- Gale プロファイルに必須 plugin install 済み (`just check-gale` 全 ✓)
- Steam Launch Options に `WINEDLLOVERRIDES="winhttp=n,b" %command%`
- host で `just host-agent` daemon が GUI session の端末で起動している
  (`DISPLAY` / `WAYLAND_DISPLAY` 必須)
- container 内で `cd python && uv sync` 済み
- **掴める object を 1 つ用意する**。例:
  - Dev Tool / インベントリ から box などの grabbable prop を手の届く位置に
    spawn する、または
  - 既に grabbable な prop が置いてある world に居る / その prop の傍に立つ

## 手順

container 内 shell から deploy + 起動:

```sh
just deploy-mod                # build + plugin deploy
just resonite-start            # host 経由で Gale → Resonite 起動
```

Resonite 内で:

1. 掴める object を手の届く範囲に spawn / 配置する
2. その object のおおよその world 座標を控える (Inspector で slot の Global
   Position を見るのが確実)。あるいは座標を使わず、object が手の grab 球に
   入るように立つ

container 内 shell からその座標目掛けて grab (座標 `X Y Z` は控えた値):

```sh
uv run --project python resoio manipulate grab \
  --hand right --point X Y Z --radius 0.3
```

手の現在位置で掴む場合 (object が手の grab 範囲に入っている前提) は
`--point` を省略:

```sh
uv run --project python resoio manipulate grab --hand right
```

CLI 出力が `grabbed=True` であることを確認する。続けて状態を表示:

```sh
uv run --project python resoio manipulate state --hand right
```

`is_holding=True` で `objects=[...]` に掴んだ slot 名が出ていることを確認。
**Resonite の view を動かして、掴んだ object が手に追従する** ことを目視
確認する (手を動かす / 視点を回す → object が手と一緒に動く)。

最後に release してドロップを確認:

```sh
uv run --project python resoio manipulate release --hand right
uv run --project python resoio manipulate state --hand right
```

`is_holding=False` になり、object がその場に残る (手から離れて落ちる /
留まる) ことを目視確認する。

## 判定基準

- grab 後: CLI が `grabbed=True`、`state` が `is_holding=True` で
  `objects=[<掴んだ slot 名>]` を表示
- 目視: 掴んでいる間、object が手に追従する (手 / 視点を動かすと一緒に動く)
- release 後: CLI が `is_holding=False`、`objects=[]`
- 目視: release 後は object が手から離れ、その場に留まる

## 想定される失敗モードと診断

### `grabbed=False` のまま掴めない

- object が grab 球 (`--radius`) の外。`--radius` を広げる (例 0.5) か、
  `--point` を object の Global Position により近づける
- 対象が grabbable でない (Grabbable component が無い slot)。Inspector で
  `Grabbable` component の有無を確認
- `--hand` が逆の手。物理的に届く側の手を指定する (desktop では primary =
  right)

### `bridge ready check failed (FAILED_PRECONDITION): ...`

`ManipulationBridge` がまだ engine ready 前、または focus world / per-hand
Grabber が未確定。Userspace でなく Home World 等いずれかの world に居る状態で
再実行する。

### 掴めるが手に追従しない (`grabbed=True` だが object が動かない)

掴み判定は成立しているが grab 後の parent 付け / follow が効いていない可能性。
[just log](../../../justfile) で grab 時の Bridge ログを確認し、Grabber が
対象 slot を grab list に入れているか追う。Resonite 側で object が
`NonpersistentGrab` や anchor 固定されていないかも確認する。

## クリーンアップ

```sh
just resonite-stop             # container → host bridge 経由で Resonite を停止
```
