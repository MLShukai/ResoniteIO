---
name: bepinex-transitive-dlls
description: BepInEx mod の bin/ には CopyLocalLockFileAssemblies=true + PostBuild Copy 双方が必要。AspNetCore framework reference は SDK shared framework dir から専用 Target で都度コピーする。
metadata:
  type: feedback
---

BepInEx 6 mod (`Microsoft.NET.Sdk` ベースのライブラリ csproj) で AspNetCore 系の transitive 依存を持つ Core (`Grpc.AspNetCore.Server` 等) を `ProjectReference` する場合:

- 既定では NuGet 由来の transitive DLL は **bin/ に出ない** (deps.json 経由の nuget cache lookup を前提とした挙動)。BepInEx は `AssemblyLoadContext.Default` で plugin フォルダから DLL を解決するため、隣接 DLL が無いと load 失敗。
- 対策 1: csproj に `<CopyLocalLockFileAssemblies>true</>` を追加 → Grpc 系 NuGet DLL が bin/ に出るようになる。
- 対策 2: gale (Thunderstore mod manager) profile に deploy する PostBuild `<Copy>` Target にも、明示的に Grpc 系 DLL を `<PluginFiles Include>` で追加する必要がある (TargetPath だけだと mod 本体だけが deploy される)。Gale が canonical 版を提供する `BepInExResoniteShim` / `BepisResoniteWrapper` は重複させない。
- `Microsoft.AspNetCore.App` は **framework reference** (shared framework) のため、`CopyLocalLockFileAssemblies=true` でも `PostBuild Copy` でも自動 export されない。**解決策**: `ResoniteIO.csproj` の `CopyAspNetCoreSharedFrameworkRuntime` Target で `$(NetCoreRoot)shared/Microsoft.AspNetCore.App/$(BundledNETCoreAppPackageVersion)/*.dll` を `TargetDir` にコピーし、PostBuild の `<PluginFiles Include="$(TargetDir)Microsoft.AspNetCore*.dll" />` + `Microsoft.Extensions.*.dll` + `Microsoft.Net.Http.Headers.dll` で gale に同梱する。`Microsoft.NETCore.App` (System.IO.Pipelines 含む) は Resonite ランタイムが既に持っているので include 不要。Step 2 Phase 4 の実機検証で `Renderite.Host` 側に AspNetCore が無いことを確認した上で確定 (commit `71d00a3` / `fdbdb3d` 周辺)。
- `Loading/PluginAssemblyResolver` を併用して、Resonite 同梱の **古い Google.Protobuf** より plugin folder 側の Core 同梱版を優先解決する (これを怠ると `TypeLoadException: Could not load type 'Google.Protobuf.IBufferMessage'`)。

**Why:** Step 2 Phase 2 で `ResoniteIO.Core` (Kestrel + UDS) を mod から起動するときに発覚。`dotnet build` 単体ではエラーにならず、bin/ を目視して初めて DLL が落ちていることに気付くため見落としやすい。Step 2 Phase 4 + Step 3 の Camera 実機検証を通じて、SDK shared framework dir 経由のコピー戦略で AspNetCore 依存もまるごと安全に持ち込めることが確認できた。

**How to apply:** 新しい transitive package 依存を Core に足したら、必ず `ls mod/src/ResoniteIO/bin/Release/` を確認し、必要なら csproj の PluginFiles ItemGroup に DLL を追加する。framework reference 起因の依存は `CopyAspNetCoreSharedFrameworkRuntime` Target に倣って、対応する `$(NetCoreRoot)shared/<FrameworkName>/<version>/` から `Copy` で TargetDir に持ち込み、その後 PluginFiles で gale に同梱する流れに乗せる。新規 mod-side native dependency を入れるときは Resonite (Renderite.Host) 側に同名 DLL が既にあるか先に decompile / `ls` で確認すると version skew 事故を避けられる。
