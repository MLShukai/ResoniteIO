# Manipulation (FrooxEngineManipulationBridge) ポジティブ grab 検証

`FrooxEngineManipulationBridge` が実機の per-hand `Grabber` に
**カーソルレイの hit 点中心** の grab をさせ、掴んだ grabbable が
**実際に手に追従する** ことを目視で確認する手動検証手順。加えて
VR モードで grab が `FAILED_PRECONDITION` で拒否されることを確認する。
自動 e2e ではカバーできない部分のみをここに残す。

実装計画上の対応:

- [resonite_io_plan.md](../../../resonite_io_plan.md) Step 6 (Manipulation) の
  grab/release が **物を実際に掴めること** の目視確認相当
- RPC 経路 (mod ロード / bridge が実 Grabber に到達 / カーソル照準 → レイ計算 →
  raycast → grab の呼び出し経路が例外なく回る / レスポンスが well-formed /
  hand 解決が正しい) の自動検証は
  [python/tests/e2e/manipulation.py](../../../python/tests/e2e/manipulation.py)
  で `just e2e-test manipulation` 経由
- 残るマニュアル要素:
  1. **掴める object にカーソルを重ねた上で `grabbed=True` /
     `is_holding=True` になり、掴んだ object が手に視覚的に追従すること**。
     これは本質的に人間しかできない (後述)
  2. **前後に並べた 2 つの object のうち手前が掴まれること**
     (raycast の距離順先頭 = 最手前という仮定の実機確認)
  3. **VR モードで grab が `FAILED_PRECONDITION` になること**
     (VR への切替は人間の HMD 操作が必要)

## なぜ手動なのか

default の home world は grabbable object を一切公開しておらず、
grabbable を **決定論的に spawn する API も無い**。そのため自動 e2e では
`grabbed=False` のまま「呼び出し経路が例外なく回る」ことしか確認できない。
掴んだ object が手に追従するか否か・手前の object が選ばれるかは目視判断に
なるため、ポジティブ grab はこの手動手順に分離している。VR モード確認も
HMD の装着 / モード切替が必要で自動化できない。

## 前提

- ResoniteIO mod が Gale 経由起動の Resonite に正しくロードされる状態
  (確認: `just resonite-start` 後に `just log` で `Loading Plugin ResoniteIO`
  が出る)
- Gale プロファイルに必須 plugin install 済み (`just check-gale` 全 ✓)
- Steam Launch Options に `WINEDLLOVERRIDES="winhttp=n,b" %command%`
- host で `just host-agent` daemon が GUI session の端末で起動している
  (`DISPLAY` / `WAYLAND_DISPLAY` 必須)
- container 内で `cd python && uv sync` 済み
- Resonite は **デスクトップ (screen) モード** で起動している (VR 確認手順を
  除く)
- **掴める object を 1 つ用意する**。例:
  - Dev Tool / インベントリ から box などの grabbable prop を視界内に
    spawn する、または
  - 既に grabbable な prop が置いてある world に居る / その prop が見える
    位置に立つ

## 手順: ポジティブ grab (カーソル照準)

container 内 shell から deploy + 起動:

```sh
just deploy-mod                # build + plugin deploy
just resonite-start            # host 経由で Gale → Resonite 起動
```

Resonite 内で:

1. 掴める object を視界内に spawn / 配置する (座標を控える必要はない)
2. object が画面に映る位置・向きに立つ

container 内 shell からカーソルを object に重ねる (正規化座標 `<x> <y>` は
0.0〜1.0。まず中央 `0.5 0.5` に置き、screenshot を見ながら調整する):

```sh
uv run --project python resoio cursor set 0.5 0.5
python3 scripts/resonite_cli.py screenshot --output /tmp/aim.png
# カーソルが object に重なるまで cursor set の座標を調整して繰り返す
```

カーソルが object に重なったら grab:

```sh
uv run --project python resoio manipulate grab --hand right --radius 0.3
```

CLI 出力が `grabbed=True` であることを確認する。続けて状態を表示:

```sh
uv run --project python resoio manipulate state --hand right
```

`is_holding=True` で `objects=[...]` に掴んだ slot 名が出ていることを確認。
**Resonite の view を動かして、掴んだ object が手に追従する** ことを目視
確認する (手を動かす / 視点を回す → object が手と一緒に動く)。

最後にカーソル保持を解放し、release してドロップを確認:

```sh
uv run --project python resoio cursor release
uv run --project python resoio manipulate release --hand right
uv run --project python resoio manipulate state --hand right
```

`is_holding=False` になり、object がその場に残る (手から離れて落ちる /
留まる) ことを目視確認する。

## 手順: 手前の object が掴まれること (raycast 距離順の確認)

レイ上に grabbable を **前後に 2 つ** 並べ (例: 手前 1m / 奥 3m に box)、
両方にカーソルが重なる位置で grab する:

```sh
uv run --project python resoio cursor set <x> <y>   # 2 つの box が重なる照準
uv run --project python resoio manipulate grab --hand right --radius 0.3
uv run --project python resoio manipulate state --hand right
```

`objects=[...]` が **手前の box の slot 名** であることを確認する
(`RaycastAll` の先頭 hit = 最手前という仮定の実機検証)。確認後は
`cursor release` + `manipulate release` で後片付けする。

## 手順: VR モードで FAILED_PRECONDITION

VR モードで Resonite を起動する (または Dash からデスクトップ → VR に
切り替える)。container 内 shell から:

```sh
uv run --project python resoio manipulate grab --hand right
```

CLI が **`FAILED_PRECONDITION` エラーで失敗** し、エラーメッセージに
`desktop` が含まれる (要旨: grab はデスクトップ (screen) モード必須) ことを
確認する。`grabbed=False` の正常終了に **ならない** こと (エラーで返ること)
が判定基準。確認後はデスクトップモードに戻す。

## 判定基準

- grab 後 (デスクトップモード・カーソルが grabbable に重なっている):
  CLI が `grabbed=True`、`state` が `is_holding=True` で
  `objects=[<掴んだ slot 名>]` を表示
- 目視: 掴んでいる間、object が手に追従する (手 / 視点を動かすと一緒に動く)
- 前後 2 object: 手前の slot 名が `objects=[...]` に出る
- release 後: CLI が `is_holding=False`、`objects=[]`
- 目視: release 後は object が手から離れ、その場に留まる
- VR モード: grab が `FAILED_PRECONDITION` (message に `desktop`) で失敗する

## 想定される失敗モードと診断

### `grabbed=False` のまま掴めない

- カーソルが object に重なっていない (レイ miss、または hit 点が別の面)。
  screenshot でカーソル位置を確認し `cursor set` の座標を調整する
- hit 点から object の Grabbable まで `--radius` 内に入っていない。
  `--radius` を広げる (例 0.5)
- 対象が grabbable でない (Grabbable component が無い slot)。Inspector で
  `Grabbable` component の有無を確認
- 手前に別のコライダ (壁・UI 等) がありレイがそちらに当たっている。
  照準位置・立ち位置を変える

### `FAILED_PRECONDITION: ... desktop ...`

VR モードで grab を呼んだ (仕様どおりの拒否)。デスクトップモードに切り替えて
再実行する。

### `bridge ready check failed (FAILED_PRECONDITION): ...`

`ManipulationBridge` がまだ engine ready 前、または focus world / per-hand
Grabber / Mouse が未確定。Userspace でなく Home World 等いずれかの world に
居る状態で再実行する。

### 掴めるが手に追従しない (`grabbed=True` だが object が動かない)

掴み判定は成立しているが grab 後の parent 付け / follow が効いていない可能性。
[just log](../../../justfile) で grab 時の Bridge ログを確認し、Grabber が
対象 slot を grab list に入れているか追う。Resonite 側で object が
`NonpersistentGrab` や anchor 固定されていないかも確認する。

## クリーンアップ

```sh
uv run --project python resoio cursor release   # カーソル保持が残っていれば解放
just resonite-stop             # container → host bridge 経由で Resonite を停止
```
