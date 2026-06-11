# Grabber (FrooxEngineGrabberBridge) 手動検証

`FrooxEngineGrabberBridge` の grab/release のうち、**自動 e2e では
カバーできない部分のみ** をここに残す手動検証手順:

1. **掴んだ object が手に視覚的に追従すること** (目視判断)
2. **前後に並べた 2 つの object のうち手前が掴まれること**
   (raycast の距離順先頭 = 最手前という仮定の実機確認)
3. **VR モードで grab が `FAILED_PRECONDITION` になること**
   (VR への切替は人間の HMD 操作が必要)

実装計画上の対応:

- [resonite_io_plan.md](../../../resonite_io_plan.md) Step 6 (Grabber、旧称
  Manipulation) の grab/release の目視確認相当
- **ポジティブ grab は自動 e2e 化済み**:
  [python/tests/e2e/grabber.py](../../../python/tests/e2e/grabber.py)
  が `InventoryClient.spawn("/Inventory/Resonite Essentials/Mirror")` で
  grabbable な Mirror を spawn → cursor 照準 → `grabbed=True` /
  `object_names` に `Mirror` → release で `is_holding=False` までを
  自動 assert する (`just e2e-test grabber` 経由)。RPC 経路
  (mod ロード / bridge が実 Grabber に到達 / hand 解決 / well-formed
  レスポンス) も同テストがカバーする

## なぜこの 3 点だけ手動なのか

- 「掴んだ object が手に追従して動く」は位置 API が無く、視点・手を
  動かしながらの目視でしか確認できない
- 「手前の object が選ばれる」は前後 2 object の配置とカーソル照準の
  微調整が必要で、目視での照準合わせが前提になる
- VR モード切替は HMD の装着 / モード切替が必要で自動化できない

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

## 手順: 掴んだ object が手に追従すること (目視)

container 内 shell から deploy + 起動:

```sh
just deploy-mod                # build + plugin deploy
just resonite-start            # host 経由で Gale → Resonite 起動
```

home world ロード後、grabbable を spawn する (`resoio inventory` は
対話 REPL なので、shell 内で `spawn` を打ってから `exit` する):

```sh
uv run --project python resoio inventory
# REPL 内:
#   resoio:/Inventory$ spawn "/Inventory/Resonite Essentials/Mirror"
#   resoio:/Inventory$ exit
```

5 秒ほど待って Mirror が定位置に収まったら、カーソルを重ねて掴む
(e2e と同じ経路):

```sh
uv run --project python resoio cursor set 0.5 0.45
uv run --project python resoio grab --radius 0.5
uv run --project python resoio grab state
```

`grabbed=True` / `is_holding=True` / `objects=[Mirror]` を確認したら、
**Resonite の view を動かして、掴んだ Mirror が手に追従する** ことを目視
確認する (手を動かす / 視点を回す → Mirror が手と一緒に動く)。

確認後:

```sh
uv run --project python resoio cursor release
uv run --project python resoio grab release
```

`is_holding=False` になり、Mirror がその場に残ることを目視確認する。
spawn した Mirror を world から削除する API は無いので放置してよい
(local home は Resonite 再起動でリセットされる)。

## 手順: 手前の object が掴まれること (raycast 距離順の確認)

レイ上に grabbable を **前後に 2 つ** 並べ (例: 手前 1m / 奥 3m に box)、
両方にカーソルが重なる位置で grab する:

```sh
uv run --project python resoio cursor set <x> <y>   # 2 つの box が重なる照準
uv run --project python resoio grab --hand right --radius 0.3
uv run --project python resoio grab state --hand right
```

`objects=[...]` が **手前の box の slot 名** であることを確認する
(`RaycastAll` の先頭 hit = 最手前という仮定の実機検証)。確認後は
`cursor release` + `grab release` で後片付けする。

## 手順: VR モードで FAILED_PRECONDITION

VR モードで Resonite を起動する (または Dash からデスクトップ → VR に
切り替える)。container 内 shell から:

```sh
uv run --project python resoio grab --hand right
```

CLI が **`FAILED_PRECONDITION` エラーで失敗** し、エラーメッセージに
`desktop` が含まれる (要旨: grab はデスクトップ (screen) モード必須) ことを
確認する。`grabbed=False` の正常終了に **ならない** こと (エラーで返ること)
が判定基準。確認後はデスクトップモードに戻す。

## 判定基準

- 目視: 掴んでいる間、Mirror が手に追従する (手 / 視点を動かすと一緒に動く)
- 目視: release 後は object が手から離れ、その場に留まる
- 前後 2 object: 手前の slot 名が `objects=[...]` に出る
- VR モード: grab が `FAILED_PRECONDITION` (message に `desktop`) で失敗する

## 想定される失敗モードと診断

### `grabbed=False` のまま掴めない

- spawn 直後すぎる (Mirror がまだ定位置に収まっていない)。spawn 後 5 秒程度
  待ってから照準する。Resonite 起動直後すぎる spawn は想定位置に出ない
  ことがあるので、home world が完全にロードされてから spawn する
- カーソルが object に重なっていない (レイ miss、または hit 点が別の面)。
  screenshot でカーソル位置を確認し `cursor set` の座標を調整する
  (e2e は (0.5,0.45) → (0.45,0.5) → (0.55,0.4) の順で retry している)
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

`GrabberBridge` がまだ engine ready 前、または focus world / per-hand
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
uv run --project python resoio grab release
just resonite-stop             # container → host bridge 経由で Resonite を停止
```
