---
name: commentout-gamelibs-skew
description: 実機 FrooxEngine.dll にあるが Resonite.GameLibs NuGet に無い API が publish でのみ CS1061 を起こす構造と、機能を「コメントアウトで一時退避」する仕様の書き方
metadata:
  type: feedback
---

実機 Resonite DLL を使う `just run` は通るのに CI publish が CS1061 で落ちる、という事故が起きうる。
原因と仕様策定上の対処を以下に確定する (2026-06-22 Session ResoniteLink enable の 0.6.0 publish 失敗で確立)。

**構造 (Why)**:

- mod 本体 (`mod/src/ResoniteIO/`) の csproj は `ResonitePath` 指定時は実機 `FrooxEngine.dll` を、未指定時は
  `Resonite.GameLibs` NuGet (公開フォールバック) を参照する。
- 実機 DLL にあるが GameLibs に無い engine API (今回は `World.ResoniteLink` /
  `IsAllowedToRunResoniteLink()` / `StartResoniteLink()`) を使うと、**GameLibs 経路でだけ CS1061** になる。
- `dotnet.yml` (通常 CI) は **Core 層しかビルドしない**。mod 本体がコンパイルされるのは publish (`v*` tag,
  `PackTS`) 時のみ。よって通常 CI も `just run` も素通りし、tag を打った瞬間に publish が落ちる。
- ローカル再現コマンド: `env ResonitePath= dotnet build mod/src/ResoniteIO/ResoniteIO.csproj -c Release`。
  この成功が「publish が通る」最重要受け入れ条件。

**「コメントアウトで一時退避」仕様の書き方 (How to apply)**:

- ユーザー方針が「削除でなくコメントアウト (GameLibs 追随後に復活)」のときは、proto field は **`reserved`
  キーワードを使わずコメント形式 + 番号明記** で予約する。理由: `reserved` は復活時に 2 操作 (reserved 削除 +
  field 追加) と同番号衝突を招き「コメントを外すだけで戻せる」要件を壊す。コメント形式なら解除 1 操作で戻る。
- 生成物 (`python/src/resoio/_generated/`) は手編集せず、proto コメントアウト後 `just gen-proto` 再生成で
  該当フィールドが自動消滅する。その diff を同一 commit に含める。proto を触る implementer は 1 つに絞る。
- 整合性の核は「dead reference を残さない」: コメントアウトした型/field を**構築/参照/import する全箇所**を
  同時にコメントアウトする。層の連鎖 (proto → 生成物 → Core record/Service → Mod bridge → Python dataclass/
  client → CLI flag/handler/rendering → tests) を漏れなく辿る。
- C# 特有の罠を仕様に必ず明記する: (1) positional record のパラメータをコメントアウトすると末尾 dangling
  comma が壊れる → src と tests の構築箇所で同じ末尾化を揃える、(2) `<see cref>` / `<paramref>` の doc 言及を
  残すと `TreatWarningsAsErrors=true` 下で cref 解決失敗が error 化 → doc 言及もコメントアウト対象。
  object initializer の dangling comma は C# 合法なのでカンマ調整不要、という差も区別する。
- 「機能専用の例外クラス」(例 `SessionResoniteLinkException`、Core にあり FrooxEngine 非依存なので GameLibs
  build はこれ自体ではなく Mod 側 throw でのみ落ちる) は、機能を外すと dead になる。**全層コメントアウト方針なら
  例外クラスもコメントアウトし、`ApiContractTests.cs` の公開 API 契約ピン行も同時にコメントアウト**する
  (契約は「現在 export している public API を正とする」ため)。残す案 (案 B) も成立するが方針整合で劣る。
- CHANGELOG は読者向けなのでコメントアウトでなく **本文削除/書き換え**。未 publish 版なら該当機能項目を消す。

**再発防止 (Future Work として仕様に書く)**: `dotnet.yml` に「GameLibs フォールバックでの mod 本体 Release
ビルド」ジョブを足せば同種事故を tag 前に検出できる。本修正スコープ外でも別 issue として提案する価値がある。
