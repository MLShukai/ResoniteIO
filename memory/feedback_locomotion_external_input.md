---
name: locomotion-external-input
description: Locomotion Bridge は engine 既存の SmoothLocomotion / FirstPersonTargettingController / HeadSimulator に stateful repeater として注入する設計 (move/jump/crouch は ExternalInput、look は _horizontalAngle/_verticalAngle 直接積分)。pitch 符号 / AccessTools.FieldRefAccess の generic 引数順 / velocity 単位元 / consume-once jump / Reset + disconnect 検知 / Move body-local 変換 (LocalUserViewRotation) / Camera CameraStreamRequest 既存 bug 等の落とし穴を集約
metadata:
  type: feedback
---

Step 4 (Locomotion) で実機検証して確定した、`FrooxEngineLocomotionBridge` 周辺の
セマンティクスと注意点。今後 Locomotion を改修するときに最初に読む 1 本。
2026-05-19 の stateful repeater 化 + Reset RPC + disconnect 検知 + pitch 符号
反転解除 + Move rotation source を LocalUserViewRotation に変更を反映済み。
2026-06-10 の look 直接角度駆動化 (cursor-lock サブシステム撤去) を反映済み。

## 1. ExternalInput + stateful repeater で engine に注入する

Locomotion は engine 既存の `SmoothLocomotionBase` (Move / Jump) +
`HeadSimulator` (Crouch) に `InputAction.ExternalInput` を毎フレーム書き込み、
Look (Yaw + Pitch) は `FirstPersonTargettingController` の角度 field を直接
積分する方式で動かす。`LocalUser.Root` の Position / Rotation を直接駆動する
案は **採らない**:

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

→ 入力を持続させたいときは **毎 engine tick で再注入** する必要がある。書き込み
自体は任意スレッドから安全 (engine thread dispatch 不要、書き込みは race-free に
latest-wins、消費は engine 側 tick で起きる)。

**Why:** engine の `InputAction` は本来 binding (キー / マウス) から毎 tick
評価される設計で、ExternalInput は「外部から 1 frame ぶん差し込む」逃げ道。
書き込んだ値は 1 frame で消える前提で API が成立している。

**How to apply:** mod 側 Bridge が最新コマンドを保持し
`World.RunInUpdates(0, TickStep)` の self-rescheduling で engine update tick
ごとに `ExternalInput` に再注入する。client は **変化時に 1 回送るだけで avatar
が動き続ける** (旧 30 Hz keep-alive 戦略は廃止)。詳細は §6 参照。

Yaw / pitch は ExternalInput 経路を **使わない**。`ScreenCameraInputs.Look.Active`
が `InputInterface.IsCursorLocked` に gate され、`IsCursorLocked` は
`IsWindowFocused` (OS ウィンドウフォーカス) 必須のため、cursor lock を mod が
取得しても非フォーカス / 背面 / headless では look が原理的に効かなかった。
2026-06-10 以降は Bridge が `FirstPersonTargettingController` の
`_horizontalAngle` / `_verticalAngle` を `rate * Time.Delta` で毎 tick 直接積分
して gate を完全バイパスする (**focus 非依存**)。これに伴い look 用 cursor-lock
サブシステム (低 priority `RegisterCursorLock` の内部取得) は丸ごと撤去済みで、
**look は cursor lock を一切使わない**。client は Cursor modality や手動 mouse
lock を事前に呼ぶ必要はない。clamp (±89°) は engine が毎 frame 行うため Bridge
側の手動 clamp も不要。

## 2. pitch は Bridge 側で符号反転しない (実機検証ベース)

decompile 上は engine 側で反転加算する記述がある:

```csharp
// FirstPersonTargettingController.OnBeforeHeadUpdate (decompiled)
float2 v = base.Inputs.Look.Value.Value * base.Time.Delta;
_horizontalAngle += v.x;       // yaw: そのまま加算
_verticalAngle  -= v.y;        // pitch: y を反転加算 (decompile の読み)
```

これを根拠に Bridge で `-pitch_rate` を書いていたが、2026-05-19 の実機検証で
「UP キー (pitch_rate > 0) が下向き」になる逆挙動を観測したため反転を解除。
**現行コード (2026-06-10 の直接角度駆動) は
`_fpcVerticalAngleRef(fpc) -= snapshot.PitchRate * fpc.Time.Delta` を直接書く**。
これは engine `OnBeforeHeadUpdate` の `_verticalAngle -= y` (y = `+PitchRate`)
と同一演算であり、ExternalInput 時代の実機検証済み挙動 (UP=見上げ) をそのまま
保つ。yaw も同様に `_fpcHorizontalAngleRef(fpc) += snapshot.YawRate * dt`
(engine の `_horizontalAngle += x` と同形)。

**Why:** proto contract (positive = 見上げ) を不変にしつつ、Bridge は engine
実装の符号慣例に従う方が破綻が起きにくい。decompile の読み違いをコードに
残し続けるより、実機検証ベースの contract を 1 か所に集約する。

**How to apply:** decompile を再生成して `_verticalAngle` 関連の演算子が変わっ
ていないか、別途追加の反転 (`FirstPersonTargettingController.OnBeforeHeadUpdate`
以外の経路) が見つかったら本セクションに追記する。実機で UP / DOWN キーの
方向が proto 規約 (positive=up) と乖離する症状を観測したら本 fix の regression
を疑う。

## 3. `AccessTools.FieldRefAccess` の generic 引数順

private field を typed delegate で 1 度だけ解決する canonical 形:

```csharp
private static readonly AccessTools.FieldRef<TDeclaring, TField> _ref =
    AccessTools.FieldRefAccess<TDeclaring, TField>("field_name");
```

generic 引数は **(declaring type, field type) の順**。逆に書くと
`InvalidCastException` ではなく **silently wrong delegate** が返ることがあるので
typo に気付きにくい (実装ミスると常に `LocomotionNotReadyException` になる)。

現行の 4 経路:

| field                                              | declaring                         | field type               |
| -------------------------------------------------- | --------------------------------- | ------------------------ |
| `SmoothLocomotionBase._normalInput`                | `SmoothLocomotionBase`            | `SmoothLocomotionInputs` |
| `HeadSimulator._inputs`                            | `HeadSimulator`                   | `HeadInputs`             |
| `FirstPersonTargettingController._horizontalAngle` | `FirstPersonTargettingController` | `float`                  |
| `FirstPersonTargettingController._verticalAngle`   | `FirstPersonTargettingController` | `float`                  |

(`TargettingControllerBase<ScreenCameraInputs>._inputs` 経路は 2026-06-10 の
look 直接角度駆動化で撤去。)

**Why:** Harmony の `FieldRef<T,U>` は **`T` がインスタンス、`U` が返り値**。
逆順を許容しないが compile-time check も無いため、ミスると runtime まで気付け
ない。

**How to apply:** 新規 private field 経由の注入を増やすときは、最初に
`AccessTools.FieldRefAccess<TDeclaring, TField>(name)` の宣言を **同 file 内
既存の 4 経路と並べて diff し、引数順が揃っているか目視確認**。Resonite が
update されたら decompile を再生成し、field 名 / declaring type の改名を
diff チェックする (改名されると Bridge は常に precondition 失敗扱いとなり、
stateful repeater が next tick まで apply を skip し続ける)。

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
側で `LocomotionCmd(move_forward=1.0, velocity=3.0)` で再確認する。

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

## 6. stateful repeater + Reset RPC + disconnect 検知

新設計の要点 (2026-05-19 以降の現行):

- **mod 側 Bridge が最新コマンドを保持し、`World.RunInUpdates(0, TickStep)` の
  self-rescheduling で engine update tick ごとに `ExternalInput` に再注入する**。
  client は state 変化時に 1 回送るだけで avatar が動き続ける
- gRPC stream 側 (ThreadPool スレッド) は `_state` を `lock` 越しに書き換える
  だけ、engine 側 (engine thread) も同 `lock` で読む (latest-wins の race 安全)
- **jump は consume-once pulse**: Bridge `_state.JumpPending: bool` を tick で
  apply したら即 false に戻す。CLI / Python は `jump=True` を 1 回送るだけ
- **graceful close vs cancel/error の disconnect 検知**:
  - `await requestStream.MoveNext()` が `false` を返す (`CompleteAsync`) → **state
    維持** (RL/ロボティクスで「短命コマンドを送って閉じる」 idiom が成立する)
  - `MoveNext` が `OperationCanceledException` または `IOException` を投げる (UDS
    切断 / Http/2 RST_STREAM / Python crash) → **全 state 自動 reset** (safety)
  - Grpc.AspNetCore + Kestrel UDS では cancel が `IOException` で表面化する経路
    があるため、catch 3 段構え (`OperationCanceledException` → `IOException` →
    `Exception when ct.IsCancellationRequested`) で吸収。詳細は
    `feedback_grpc_client_cancel_exception_surface` (agent-memory) 参照
- **明示的 `Reset` RPC**: `LocomotionResetRequest` に move / look / crouch / jump
  の 4 bool。**全 false なら全 reset** と Service 層で展開 (proto3 wire default が
  0 で「未指定」と「全 false」が区別不能なため一意解釈)。部分 reset は対象 field
  のみ true
- Service 実装は [mod/src/ResoniteIO.Core/Locomotion/LocomotionService.cs](../../mod/src/ResoniteIO.Core/Locomotion/LocomotionService.cs)、
  engine 側再注入は [mod/src/ResoniteIO/Bridge/FrooxEngineLocomotionBridge.cs](../../mod/src/ResoniteIO/Bridge/FrooxEngineLocomotionBridge.cs)
  に集約

**Why:** AI エージェントから Locomotion を使う側に「30Hz keep-alive を維持する」
責務を負わせる旧設計はリアルタイムロボティクスの抽象として薄汚い。stateful 化で
client は「変化時に 1 回送る」典型的な actuator-driver IF になり、graceful close
で state 維持 + ungraceful disconnect で safety reset、の 2 軸を mod 側に集約
できる。timeout watchdog は採用せず、stream lifecycle を真値にする方が単純。

**How to apply:**

- 新規モダリティで「engine 側 tick で消費される ExternalInput 系の slot」がある
  場合は、本パターン (Bridge 内 `_state` + `World.RunInUpdates(0, TickStep)` self-
  rescheduling) を踏襲する。直接 timer thread から書くと engine Evaluate と race
- 既存 Locomotion テスト ([mod/tests/ResoniteIO.Core.Tests/Locomotion/](../../mod/tests/ResoniteIO.Core.Tests/Locomotion/))
  は graceful close で `Graceful` notify、client cancel で `Cancelled` notify を
  検証する 2 件が canonical。新 Service ロジックを足したら同じ pair を追加

## 7. 既知の corner case (実害が出てから対処する候補)

- **active module が SmoothLocomotion 以外** (Teleport / NoClip / GrabWorld 等):
  Bridge は新 IF (`SetState`) では throw せず、precondition NG として次 tick の
  再評価に委ねる (consumer は `FailedPrecondition` を見ない)。manual-test に
  「locomotion mode が Walk になっていること」を入れる。home world (`Userspace`)
  も NoLocomotion 系で永久 NG。
- **VR mode で FirstPersonTargettingController が null**: Bridge は silent skip
  (Drive 自体は成功するが yaw/pitch が engine に届かない)。将来 capability RPC
  で `has_look` を露出する余地あり。
- **look の window focus 依存 (解消済み, 2026-06-10)**: 旧実装は yaw/pitch が
  非 0 の間だけ `RegisterCursorLock` で `ScreenCameraInputs.Look.Active` の前提
  を満たそうとしたが、`IsCursorLocked = !unlock && IsWindowFocused` の focus 項
  は代替できず、非フォーカス / 背面 / headless で look が効かなかった。現行は
  `_horizontalAngle` / `_verticalAngle` 直接積分で gate ごとバイパスするため
  **focus 非依存で look が効く** (§1 / §2 参照)。
- **jump 連続発火**: Bridge 側 consume-once pulse (受信した次 1 engine tick
  だけ apply、その後 latch を下げる) で抑止済み。client が同じ tick 内に
  `jump=true` を複数送ると 1 pulse に圧縮される (manual test の trouble shoot
  に既知挙動として明記)。

## 8. Move は LocalUserViewRotation 経由で body-local に変換する

`Move.ExternalInput` は `UserRoot.Slot` 座標系の値として engine が解釈する
(`ScreenLocomotionDirection.Evaluate` が `Slot.GlobalDirectionToLocal` で
変換した値を Move binding 出力にしている、decompile
`ScreenLocomotionDirection.cs:46`)。素朴に world 軸 `(MoveRight, 0, MoveForward)` を
書くと、head の向きを無視した world-fixed 移動になり、yaw 旋回しても進む
方向が変わらない症状が出る (2026-05-19 実機 bug)。

原因: `UserRoot.Slot.GlobalRotation` は head 向きを反映せず ~identity の
ため、PhysicalLocomotion 内の `LocalDirectionToGlobal` も identity 近似と
なる。WASD binding が「正しく頭の向きに進む」のは binding 評価時に同 slot
上で **`World.LocalUserViewRotation` を経由して** world forward/right を
作り、`Slot.GlobalDirectionToLocal` で Slot 系に逆変換しているため
(`ScreenLocomotionDirection.cs:39-47`、既定 `LocomotionReference.View`)。
ExternalInput はこの変換を bypass するので、Bridge 側で同等の rotation
を掛ける必要がある。

修正: `ApplyToEngine` で `userRoot.World.LocalUserViewRotation` を world
forward/right に掛けた後 `Slot.GlobalDirectionToLocal` で Slot 系に変換する:

```csharp
var viewRot = userRoot.World.LocalUserViewRotation;
var slotForward = userRoot.Slot.GlobalDirectionToLocal(viewRot * float3.Forward);
var slotRight   = userRoot.Slot.GlobalDirectionToLocal(viewRot * float3.Right);
var worldUp     = float3.Up; // local 必須: float3.Up は property で in 渡し不可 (CS8156)
var slotUp      = userRoot.Slot.GlobalDirectionToLocal(in worldUp); // world-up (視点 pitch 非依存)
normalInput.Move.ExternalInput =
    (snapshot.MoveRight * slotRight
     + snapshot.MoveForward * slotForward
     + snapshot.MoveUp * slotUp) * snapshot.Velocity;
```

`move_up` は **world 絶対上下** を slot-local 化した軸。NoClip
(`NoclipLocomotion`) は `LocalDirectionToGlobal(Move)` を 3 成分そのまま位置加算
するので fly 中に上下移動でき、Walk (`PhysicalLocomotion` GroundTraction) は
`v3.x_z` で垂直成分を捨てるため自動的に無視される。Bridge は 1 本の slot-local
Move を書くだけでよく、**モード検出を持たない**。

### HeadFacingRotation を採らなかった理由 (2026-05-19 strafe-drift bug)

初期実装では `userRoot.HeadFacingRotation` を採っていた (LocalUserViewRotation
は pitch を含むため Move が下向きに sink する懸念があったが、これは後述
の通り杞憂だった)。実機で「strafe (`d` / `a`) が真横ではなく僅かに前方へ
ドリフトする」症状を観測し、`[LocomotionMove]` 診断ログで原因を pin:

- `HeadFacingRotation` は `UserRoot.HeadFacingRotation` getter が
  `floatQ.LookRotation(HeadFacingDirection, Slot.Up)` で構築し、
  `HeadFacingDirection` 自体は `(HeadSlot.LocalRotation * Forward).x_z.Normalized`
  と水平投影されている (decompile `UserRoot.cs:976-998`)。理屈上は yaw のみ
- 実際には avatar の **ヘッドボーン** (`HeadSlot.LocalRotation`) が
  locomotion 中の IK / animation で動的に揺れるため、user の camera 向き
  と数度ずれる。静止時 yaw≈-0.27°、strafe 開始後は ±5° で oscillate
- ExternalInput は engine consumer 側で `HFR.Inverted * Move(world)` の
  逆変換を受けるが、変換を行う Bridge の HFR と consumer の HFR が
  「同 tick 内でも数度ずれている」状況になり、cancel しきれず slotMove に
  最大 9% の前後成分が漏れる
- 一方 `LocalUserViewRotation` は ScreenController.ViewRotation を直接
  反映するので user 入力と完全同期 (yaw=+0.05° で安定)、slotMove は
  全 tick で `[1; 0; ~1e-10]` (浮動小数雑音のみ) を保つ

定量検証 (2026-05-19, Local world, `/tmp/strafe_diag.py` で `move_right=+1` を
5 s 駆動):

| rotation source              | slotMove (start)              | slotMove (mid)               | 漏れ         |
| ---------------------------- | ----------------------------- | ---------------------------- | ------------ |
| HFR (旧 active)              | `[0.9999; 0; +0.0055]`        | `[0.996; 0; -0.087]`         | 最大 ~9%     |
| LUVR (新 active = WASD 流儀) | `[0.99999994; 0; -1.164E-10]` | `[0.99999994; 0; -1.16E-10]` | 0 (雑音のみ) |

`Slot.GlobalPosition` 観測: LUVR で move_right=+1 を 5 s 駆動すると X が
0 → ~20 m、Z は -0.10 → -0.12 (0.02 m 漏れ、0.1%)。HFR 時代は同条件で
ユーザー視点に visible なドリフトが出ていた。

### pitch sink は実害なし (LUVR を採用しても問題ない理由)

`LocalUserViewRotation` は pitch を含むので `LUVR * Forward` は下向き
ベクトルになり得る。これだけ見ると Move が下向きに sink するように見えるが、
`PhysicalLocomotion.Update` 内 (`PhysicalLocomotion.cs:382-391`) で
`MovementMode.GroundTraction` のとき `v3 = v3.x_z.Normalized * v3.Magnitude`
が走り Slot-local Y 成分が常に零化されるため、結果的に水平面に保たれる。
default `Walk` モジュールはこの分岐に乗るので screen mode + 一般 world で
は実害なし。pitched 30° down + strafe right でも `slotMove = (1, 0, 0)` を
維持しつつ `Slot.GlobalPosition.y` は変化しないことを実機で確認済み。

### 4-stage diagnostic (前進方向は HFR / LUVR どちらでも同じ)

前進 → 90° yaw → 前進 の `Slot.GlobalPosition` 計測 (HFR 時代の旧 §8 結果、
LUVR でも同じ理由で成立):

- V_B (turn 前 前進ベクトル) ≈ `(0, 0, 7.88)` → +Z
- V_D (turn 後 前進ベクトル) ≈ `(7.99, 0, 0.40)` → +X
- 角度差 ≈ **87.1°** (頭の最終 yaw 88.6° と tolerance 内で一致)

LUVR と HFR は yaw 成分は (定常状態では) ほぼ一致するため、前進方向だけ
見ていれば strafe の bug は見逃される。strafe 直交性を別途検証する必要
あり。

**Why:** ExternalInput が Slot 座標系である事実は decompile を読まないと
気付きにくく、world-axis で書く naive 実装が「e2e は通る (RPC が完走する)
が動画では body-relative に動いていない」という silent 失敗を引き起こす。
HFR と LUVR の選択も「engine binding と完全に同じ rotation を採るのが
最も regression-free」というのが 2026-05-19 の最終結論。ここを固定 contract
として書き残すことで「strafe で前後にドリフトする」「move が世界固定方向に
流れる」両症状を見た次の人が一発で参照できる。

**How to apply:**

- Bridge の rotation source を `LocalUserViewRotation` 以外に切替えるのは
  regression。HFR は avatar の ヘッドボーン animation 影響を受けるため
  body-local 変換には不向き
- 新しい proto field (e.g. `body_relative: bool`) で world-fixed mode を
  opt-in したい場合のみ別経路を足す
- 実機検証は `python/tests/e2e/locomotion.py` (Codex が host-agent
  経由で自動駆動する) の 20 s シナリオ MP4 を目視 / フレーム比較する:
  - 前進方向: 0-3 s phase と 9-11 s phase で「yaw 旋回後に前進方向が
    画面上で変わる」こと
  - strafe 直交性: 5-7 s phase の `move_right=1.0` で前後方向に visible な
    ドリフトがないこと

関連: \[\[locomotion-headfacing-body-relative\]\] (spec-driven-implementer
memory、HFR 採用時の定量計測 prototype 経緯)。
