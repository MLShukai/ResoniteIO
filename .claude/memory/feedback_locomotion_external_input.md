---
name: locomotion-external-input
description: Locomotion Bridge は engine 既存の SmoothLocomotion / FirstPersonTargettingController / HeadSimulator に ExternalInput 経路で注入する設計。pitch 符号反転 / 30Hz hold-while-streaming / AccessTools.FieldRefAccess の generic 引数順 / Camera CameraStreamRequest 既存 bug 等の落とし穴を集約
metadata:
  type: feedback
---

Step 4 (Locomotion) で実機検証して確定した、`FrooxEngineLocomotionBridge` 周辺の
セマンティクスと注意点。今後 Locomotion を改修するときに最初に読む 1 本。

## 1. ExternalInput 経由の設計と 30Hz hold-while-streaming

Locomotion は engine 既存の `SmoothLocomotionBase` (Move / Jump) +
`FirstPersonTargettingController` (Look = Yaw + Pitch) + `HeadSimulator` (Crouch)
に `InputAction.ExternalInput` を毎フレーム書き込む方式で動かす。`LocalUser.Root`
の Position / Rotation を直接駆動する案は **採らない**:

- engine 既存の collision / smoothing / clamp (`_verticalAngle` の ±89° 制限等)
  をそのまま使えるので WASD + マウスルックの体感に揃う
- VR mode 切替・active locomotion module 切替で engine が自動で path を切り替えて
  くれる

**`ExternalInput` は engine update tick で消費 + null reset される**:

```csharp
// Analog3DAction.Evaluate (decompiled)
if (ExternalInput.HasValue) {
    _intermediateResult += ExternalInput.Value;
    ExternalInput = null;
}
```

→ 入力を持続させたいときは Python から **30Hz 程度で連続発行** する。stream を
止めれば即 idle に戻る (送信責務 = active input、無送信 = neutral)。Bridge への
書き込み自体は任意スレッドから安全 (engine thread dispatch 不要、書き込みは
race-free に latest-wins、消費は engine 側 tick で起きる)。

**Why:** engine の `InputAction` は本来 binding (キー / マウス) から毎 tick
評価される設計で、ExternalInput は「外部から 1 frame ぶん差し込む」逃げ道。
書き込んだ値は 1 frame で消える前提で API が成立している。

**How to apply:** Python 側で `await asyncio.sleep(1/30)` のループで送り続ける
パターンが既定。drive stream を切ったときの idle 復帰を assert したいテストは
「送信停止 → 1〜2 frame 待って Bridge `Received` の最後が neutral」を確認する。

## 2. pitch は engine 側が反転加算するので Bridge で符号反転

```csharp
// FirstPersonTargettingController.OnBeforeHeadUpdate (decompiled)
float2 v = base.Inputs.Look.Value.Value * base.Time.Delta;
_horizontalAngle += v.x;       // yaw: そのまま加算
_verticalAngle  -= v.y;        // ★ pitch: y を反転加算
```

Python API は「上向き正」(`pitch_rate > 0 で見上げる`) で公開し、Bridge 内で
`external_y = -pitch_rate` の符号反転を入れる。proto field の単位は
**rad/sec ではなく `engine が time-delta で乗算する rate` ベース** (engine 側で
`* base.Time.Delta` が掛かる点に注意、`engine の degree/sec 換算は engine 内部 定数次第`)。

**Why:** 「Python API を直感的な向き」+「engine 内部表現は engine の都合」の二
レイヤを分け、Bridge で 1 箇所だけ翻訳するため。proto は Python から見た方向で
定義 (`positive = look up`)。

**How to apply:** decompile の `FirstPersonTargettingController` が改修されて
反転方向が変わったら Bridge 1 箇所の符号を直すだけで済む。e2e の「見上げ phase」
で頭が下がる症状を観測したらここを疑う。

## 3. `AccessTools.FieldRefAccess` の generic 引数順

private field を typed delegate で 1 度だけ解決する canonical 形:

```csharp
private static readonly AccessTools.FieldRef<TDeclaring, TField> _ref =
    AccessTools.FieldRefAccess<TDeclaring, TField>("field_name");
```

generic 引数は **(declaring type, field type) の順**。逆に書くと
`InvalidCastException` ではなく **silently wrong delegate** が返ることがあるので
typo に気付きにくい (実装ミスると常に `LocomotionNotReadyException` になる)。

Step 4 で使った 3 経路:

| field                                   | declaring                                      | field type               |
| --------------------------------------- | ---------------------------------------------- | ------------------------ |
| `SmoothLocomotionBase._normalInput`     | `SmoothLocomotionBase`                         | `SmoothLocomotionInputs` |
| `TargettingControllerBase<...>._inputs` | `TargettingControllerBase<ScreenCameraInputs>` | `ScreenCameraInputs`     |
| `HeadSimulator._inputs`                 | `HeadSimulator`                                | `HeadInputs`             |

**Why:** Harmony の `FieldRef<T,U>` は **`T` がインスタンス、`U` が返り値**。
逆順を許容しないが compile-time check も無いため、ミスると runtime まで気付け
ない。

**How to apply:** 新規 private field 経由の注入を増やすときは、最初に
`AccessTools.FieldRefAccess<TDeclaring, TField>(name)` の宣言を **同 file 内
既存の 3 経路と並べて diff し、引数順が揃っているか目視確認**。Resonite が
update されたら decompile を再生成し、field 名 / declaring type の改名を
diff チェックする (改名されると Bridge は常に `LocomotionNotReadyException` を
投げるようになる)。

## 4. velocity は ExternalInput 経路の自前再現 (単位元 1.0)

engine の Shift = sprint は独立 InputAction ではなく、binding 評価時に
`Move *= ScreenLocomotionDirection.FastMultiplier (=2.0)` を掛ける設計。
**ExternalInput はこの multiplier を bypass する**ため、Bridge 側で
`Move.x/z *= command.Velocity` を literal に掛けて再現する。

proto field `velocity` の意味:

- **単位元は 1.0** (= 通常歩行、Python `LocomotionCmd.velocity` の default)
- `2.0` で engine の `FastMultiplier` 相当、任意倍率を Python 側から指定可
- proto3 仕様上 wire default は **0**: convenience client (`LocomotionCmd`)
  経由なら自動で 1.0 が入るので問題ないが、raw proto を直接生成して
  `velocity` を未指定にすると Move が 0 倍されて停止する。これは proto3
  の必然 (optional フラグを付けない限り default を 0 以外にできない) で、
  Bridge は再解釈しない。trade-off を Python 側 default で吸収する設計。

**Why:** ExternalInput は binding 評価結果に加算されるため、倍率を
自前で掛けないと sprint=false と挙動が変わらない。proto field を float
で公開したのは Python 側から走行速度を実機チューニングできるようにするため
(server 側 const 変更を都度デプロイしなくていい)。0→1.0 の wire-side
fallback は **設けない**ことで「proto 値 = Bridge で掛かる値」の対応を 1:1
に保ち、ドキュメントが proto field 1 箇所で済む。

**How to apply:** e2e の fast 前進 phase で「通常前進 phase より明らかに
距離が伸びている」ことを目視確認。差が体感より小さい場合は `Move`
magnitude が `_maxMagnitude` で normalize されている可能性があり、Python
側で `LocomotionCmd(move_y=1.0, velocity=3.0)` で再確認する。

## 5. Camera bridge が `CameraStreamRequest.width/height` を無視している既存 bug

Step 4 locomotion e2e の調査中に発覚。client が `width=1280, height=720` を
要求しても、Camera bridge は renderer ネイティブ解像度 (E1 実測 1280×720 だが
別世界では別値) のフレームを返してくる。

- locomotion e2e (`python/tests/e2e/locomotion.py`) の `VideoWriter` は
  **初フレームの `frame.shape` を見て遅延生成** することで吸収済み
- `camera_stream.py` 側は要求解像度で `VideoWriter` を先に作る設計のため、
  ネイティブ解像度と一致しない場合 frame 書き込みが silent fail し、
  257-byte の空 mp4 が「成功」してしまう可能性がある (実害は出ていない)
- Step 5 着手前に Camera 側の挙動修正 (要求解像度に追従させるか、proto から
  width/height を除いて renderer-native のみとする) を別 PR で着手

**Why:** Camera v2 の `RendererFrameInterprocessReceiver` は renderer 側
`AsyncGPUReadback` の出力をそのまま流し、renderer の `OverlayCamera` 描画解像度
(= Resonite window のネイティブ解像度) で固定される設計。proto に `width/height`
を残したまま「無視する」のは API contract と実装が乖離している。

**How to apply:** 新規 e2e で `VideoWriter` を使うときは **初フレームの
`frame.shape` で lazy 初期化**するパターンを `python/tests/e2e/locomotion.py` から
コピーする。Camera 側挙動修正の PR を書く時は (a) proto から width/height を除く
or (b) renderer 側で resize する、の 2 択を spec-planner と相談。

## 6. 既知の corner case (実害が出てから対処する候補)

- **active module が SmoothLocomotion 以外** (Teleport / NoClip / GrabWorld 等):
  Bridge が `LocomotionNotReadyException` を投げ Python 側に `FailedPrecondition`
  が伝わる。manual-test に「locomotion mode が Walk になっていること」を入れる。
  home world (`Userspace`) も NoLocomotion 系で永久 fail。
- **VR mode で FirstPersonTargettingController が null**: Bridge は silent skip
  (Drive 自体は成功するが yaw/pitch が engine に届かない)。将来 capability RPC
  で `has_look` を露出する余地あり。
- **`IsCursorLocked=false` で engine 側 Look.Active=false**: ユーザーが Resonite
  window でマウスを掴んでいないと yaw/pitch が動かない。precondition error には
  せず silent skip (副作用なし)、manual に明記。
- **30Hz で `jump=true` を 30 frame 連発する**: `DigitalAction.ExternalInput` は
  OR-merge で edge detect が無いと連続ジャンプになる可能性。e2e の jump phase は
  ~1 秒 / 30 tick に留め、症状が出たら client 側で「`jump=true` を 1 tick だけ
  送って次は false」のパルス化に切り替える。
