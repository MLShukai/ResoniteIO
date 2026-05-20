---
name: bepinex-transitive-dlls
description: BepInEx mod の bin/ には CopyLocalLockFileAssemblies=true + PostBuild Copy 双方が必要。AspNetCore framework reference は SDK shared framework dir から `*.dll` ワイルドカードでコピーし、Resonite 同梱と version 一致の DLL は deny-list で除外する。
metadata:
  type: feedback
---

BepInEx 6 mod (`Microsoft.NET.Sdk` ベースのライブラリ csproj) で AspNetCore 系の transitive 依存を持つ Core (`Grpc.AspNetCore.Server` 等) を `ProjectReference` する場合:

- 既定では NuGet 由来の transitive DLL は **bin/ に出ない** (deps.json 経由の nuget cache lookup を前提とした挙動)。BepInEx は `AssemblyLoadContext.Default` で plugin フォルダから DLL を解決するため、隣接 DLL が無いと load 失敗。
- 対策 1: csproj に `<CopyLocalLockFileAssemblies>true</>` を追加 → Grpc 系 NuGet DLL が bin/ に出るようになる。
- 対策 2: gale (Thunderstore mod manager) profile に deploy する PostBuild `<Copy>` Target にも、`Microsoft.AspNetCore*.dll` / `Microsoft.Extensions.*.dll` のワイルドカードで TargetDir から拾い、deny-list (`_ResoniteBundledV10Dll` / `_UnusedRuntimeDll`) で取り除く構成にする。Gale が canonical 版を提供する `BepInExResoniteShim` / `BepisResoniteWrapper` / `0Harmony` も明示 Remove する。
- `Microsoft.AspNetCore.App` は **framework reference** (shared framework) のため、`CopyLocalLockFileAssemblies=true` でも `PostBuild Copy` でも自動 export されない。**解決策**: `ResoniteIO.csproj` の `CopyAspNetCoreSharedFrameworkRuntime` Target で `$(NetCoreRoot)shared/Microsoft.AspNetCore.App/$(BundledNETCoreAppPackageVersion)/*.dll` を **ワイルドカードで全部** TargetDir にコピーし、同じ deny-list で除外する。`Microsoft.NETCore.App` (System.IO.Pipelines 含む) は Resonite ランタイムが既に持っているので include 不要。
- **deny-list 戦略の核心**: 個別 allow-list (`<PluginFiles Include="...Kestrel.Core.dll" />` をひたすら列挙) は新規 transitive 追加のたびに csproj を書き直す保守地獄になるので採用しない。代わりに「`*.dll` を全部入れて Resonite と衝突するものだけ抜く」方針。**ただし `*.dll` をそのまま plugin folder に置くと Resonite 同梱の DLL を全部 overshadow してしまう**ので、Resonite 同梱と version 一致の DLL は明示的に Remove する必要がある (overshadow の効果が無いだけでなく、Default ALC の resolution 順を変えて Resonite 側のロード戦略を阻害する可能性がある)。**version skew があるものだけ overshadow** する。
- 現状の skew リスト (Resonite 同梱 → SDK 10.0.x で plugin folder に同梱して上書きするもの):
  - `Microsoft.AspNetCore.Http.Features.dll` (v5.0 → v10)
  - `Microsoft.Extensions.Configuration.dll` (v9.0 → v10)
  - `Microsoft.Extensions.Configuration.Abstractions.dll` (v9.0 → v10)
  - `Microsoft.Extensions.Configuration.Binder.dll` (v9.0 → v10)
- Resonite が v10 で同梱しており **plugin folder に置かない** DLL (`_ResoniteBundledV10Dll` で deny): SignalR.Common / SignalR.Protocols.Json / Connections.Abstractions / Http.Connections.Common / Extensions.{DependencyInjection,DependencyInjection.Abstractions,Logging,Logging.Abstractions,Options,Primitives,Features,ObjectPool}。詳細な version 一覧は \[\[resonite-bundled-dlls\]\] を参照。
- gRPC ランタイム (Google.\* / Grpc.\*) はワイルドカードに引っかからない命名なので `_AllowedGrpcDll` で **個別 include** する allow-list (Google.Protobuf / Grpc.AspNetCore.Server / Grpc.Core.Api / Grpc.Net.Common)。Google.Protobuf は Resonite 同梱の 3.11.4 と意図的に衝突させ、`PluginAssemblyResolver` 経由で plugin folder 版を優先解決する戦略の一部 (\[\[protobuf-3-11-4-in-resonite\]\])。
- 不要 transport (Windows-only / UDS と関係ない) も deny: `Microsoft.AspNetCore.Server.{HttpSys,IIS,IISIntegration}.dll` / `Microsoft.AspNetCore.Server.Kestrel.Transport.{NamedPipes,Quic}.dll`。同梱しても害は無いが BepInEx の plugin scan ノイズを減らすため除外。
- `Loading/PluginAssemblyResolver` を併用して、Resonite 同梱の **古い Google.Protobuf** より plugin folder 側の Core 同梱版を優先解決する (これを怠ると `TypeLoadException: Could not load type 'Google.Protobuf.IBufferMessage'`)。

**Why:** Step 2 Phase 2 で `ResoniteIO.Core` (Kestrel + UDS) を mod から起動するときに発覚し、Step 2 Phase 4 + Step 3 の Camera 実機検証で SDK shared framework dir 経由のコピー戦略を確定 (commit `71d00a3` / `fdbdb3d` 周辺)。当初は個別 allow-list (`<PluginFiles Include="Microsoft.AspNetCore.Hosting.dll" />` 等を列挙) だったが、新規 transitive が増えるたびに csproj 編集が必要で保守性が悪く、また「列挙漏れ」によるロード失敗の遭遇率が高かったため、`fix/20260520/minimize-plugin-dlls` で `*.dll` ワイルドカード + deny-list に移行 (145 DLL → 128 DLL)。同じタイミングで「Resonite 同梱と version 一致なら同梱しない / skew があれば同梱して overshadow」の判断基準を確立した。

**How to apply:**

- 新しい transitive package 依存を Core に足したら、まず `ls mod/src/ResoniteIO/bin/Release/` で TargetDir に DLL が出ているかを確認する。

- 出ているなら **既存のワイルドカード (`Microsoft.AspNetCore*.dll` / `Microsoft.Extensions.*.dll`) で自動的に plugin folder に入る**ので、csproj を触る必要は基本ない。

- 例外:

  - Google.\* / Grpc.\* / その他ワイルドカードに引っかからない命名 → `_AllowedGrpcDll` (= 個別 allow-list ItemGroup) に追加。
  - Resonite が同名 DLL を同梱している → 下記の確認手順で version を比較し、一致なら `_ResoniteBundledV10Dll` に追加 (= 同梱しない)、skew があれば deny-list に **入れない** (= 同梱して overshadow)。

- 検証手順 (intersection check) — plugin folder と Resonite ディレクトリの DLL 重複を 1 行で確認:

  ```sh
  comm -12 <(ls "$ResonitePath" | sort) <(ls gale/BepInEx/plugins/ResoniteIO | sort)
  ```

  期待される出力は **意図した overshadow target のみ** (現状: Http.Features + Configuration trio の 4 個 + Google.Protobuf。それ以外が出てきたら deny-list 漏れか新規 skew の可能性)。

- 各 DLL の version 確認は host 側で:

  ```sh
  dotnet -e 'System.Reflection.AssemblyName.GetAssemblyName("<path>").Version' # もしくは ILSpy で AssemblyVersion を確認
  ```

  詳細な手順と判断指針は \[\[resonite-bundled-dlls\]\] を参照。

- AssemblyName ベースの確認結果と判断 (skew → 同梱 / 一致 → 除外) を更新したら、本メモと \[\[resonite-bundled-dlls\]\] の両方に反映する。
