---
name: resonite-bundled-dlls
description: Resonite (Renderite.Host) が同梱する Microsoft.AspNetCore.* / Microsoft.Extensions.* / SignalR の DLL 一覧と version。mod 側で新規 transitive 依存を追加した際の同梱 / 除外判断基準。
metadata:
  type: reference
---

Resonite は .NET 10 ランタイムで動作するが、`Resonite_Data/Managed/` (実体は
Renderite.Host が配置する Steam インストールディレクトリ直下) に **過去の
.NET 5 / .NET 9 時代の Microsoft.* DLL を一部そのまま同梱している*\*。SDK 10.0.x で
ビルドした `ResoniteIO.Core` (Kestrel + Grpc.AspNetCore.Server) が transitive で
要求する DLL のうち、Resonite 同梱版と **version 一致するもの** と **skew が
あるもの** が混在しているため、mod 側の plugin folder にどれを同梱して overshadow
するかは DLL ごとに判断する必要がある。

本メモは 2026-05-20 時点の実機 (`ResonitePath`) で確認した結果を固定知識として
記録する。Resonite が version 上げ下げをした際は `comm -12` で再確認し更新する。

## 同梱されている DLL 一覧 (2026-05-20 実機確認)

### Version skew あり (plugin folder で **v10 を同梱して overshadow**)

| DLL                                                   | Resonite 同梱 | SDK 10.0.x |
| ----------------------------------------------------- | ------------- | ---------- |
| `Microsoft.AspNetCore.Http.Features.dll`              | 5.0           | 10         |
| `Microsoft.Extensions.Configuration.dll`              | 9.0           | 10         |
| `Microsoft.Extensions.Configuration.Abstractions.dll` | 9.0           | 10         |
| `Microsoft.Extensions.Configuration.Binder.dll`       | 9.0           | 10         |

これらは Kestrel / Hosting が要求する API 表面が古い version に無いため、
overshadow しないと server startup が `MissingMethodException` / 起動失敗で死ぬ。

### Version 一致 (v10 同士、plugin folder には **同梱しない**)

- `Microsoft.AspNetCore.SignalR.Common.dll` (v10)
- `Microsoft.AspNetCore.SignalR.Protocols.Json.dll` (v10)
- `Microsoft.AspNetCore.SignalR.Client.dll` (v10.0.7)
- `Microsoft.AspNetCore.SignalR.Client.Core.dll` (v10.0.7)
- `Microsoft.AspNetCore.Http.Connections.Client.dll` (v10.0.7)
- `Microsoft.AspNetCore.Http.Connections.Common.dll` (v10)
- `Microsoft.AspNetCore.Connections.Abstractions.dll` (v10)
- `Microsoft.Extensions.DependencyInjection.dll` (v10)
- `Microsoft.Extensions.DependencyInjection.Abstractions.dll` (v10)
- `Microsoft.Extensions.Logging.dll` (v10)
- `Microsoft.Extensions.Logging.Abstractions.dll` (v10)
- `Microsoft.Extensions.Options.dll` (v10)
- `Microsoft.Extensions.Primitives.dll` (v10)
- `Microsoft.Extensions.Features.dll` (v10)
- `Microsoft.Extensions.ObjectPool.dll` (v10)

これらは csproj の `_ResoniteBundledV10Dll` ItemGroup に列挙され、
`CopyAspNetCoreSharedFrameworkRuntime` Target と `PostBuild` Target の両方で
deny-list として `Remove` される。

## 判断指針 (新規 transitive 依存を Core に追加した時)

1. Core に新しい NuGet パッケージを参照したら、`dotnet build -c Release` 後に
   `mod/src/ResoniteIO/bin/Release/` (csproj が `AppendTargetFrameworkToOutputPath=false`
   なので TFM サブディレクトリ無し、`net10.0` ターゲット) に
   出てきた DLL のうち `Microsoft.AspNetCore*.dll` / `Microsoft.Extensions.*.dll` を
   全列挙する。

2. それぞれに対して **Resonite 同梱があるか**を `comm -12` で確認:

   ```sh
   comm -12 <(ls "$ResonitePath" | sort) \
            <(ls mod/src/ResoniteIO/bin/Release/ | sort)
   ```

3. 衝突した DLL について、host 側で version を比較:

   ```sh
   # Resonite 同梱
   dotnet -e "System.Reflection.AssemblyName.GetAssemblyName(\
     \"$ResonitePath/Microsoft.Extensions.Configuration.dll\").Version"
   # mod ビルド成果物
   dotnet -e "System.Reflection.AssemblyName.GetAssemblyName(\
     \"mod/src/ResoniteIO/bin/Release/Microsoft.Extensions.Configuration.dll\"\
     ).Version"
   ```

4. 判定:

   - **version 一致** → `_ResoniteBundledV10Dll` ItemGroup に追加 (= 同梱しない)
   - **version skew** → deny-list に **入れない** (= 同梱して overshadow)。SDK 側の
     新しい version が plugin folder から先にロードされるよう、`PluginAssemblyResolver`
     と組み合わせて動作することを実機で確認する。

5. 結果を本メモ (一覧表) と \[\[bepinex-transitive-dlls\]\] の skew リスト両方に
   反映する。

**Why:** Resonite 5/9 → SDK 10 の skew があるまま v10 を持ち込まないと Kestrel/Hosting
が `MissingMethodException` で死ぬ。逆に v10 同士で plugin folder にも v10 を置くと、
**Default ALC は「最初にロードされた DLL を優先」する** ため、Resonite engine 側の
正常なロード順序を阻害する可能性がある。SignalR 系は Resonite engine の
internal worldjoin / hosting 経路で使われており、ここを mod 側の v10 で踏み替える
リスクは取らない。

**How to apply:**

- 新規 transitive 追加時の checklist として step 1-5 を順に踏む。
- Resonite が version 更新で同梱 DLL を一斉に上げた場合、上記表は丸ごと陳腐化する。
  `comm -12` と AssemblyName 比較で再構築し、本メモを差し替える。
- `Microsoft.NETCore.App` (System.IO.Pipelines / System.Memory 等) は本メモの対象外。
  Resonite 本体ランタイムが完全に提供するので **plugin folder に同梱しない** 方針で
  問題は出ていない (出たら別途調査)。
- Google.Protobuf は本メモの skew パターンと**別経路**で扱う。3.11.4 同梱の制約は
  \[\[protobuf-3-11-4-in-resonite\]\] を参照。
