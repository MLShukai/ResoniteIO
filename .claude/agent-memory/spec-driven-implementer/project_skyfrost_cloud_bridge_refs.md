---
name: skyfrost-cloud-bridge-refs
description: Mod bridges that touch SkyFrost cloud / engine records need extra game-DLL <Reference> entries in ResoniteIO.csproj.
metadata:
  type: project
---

Mod 側 Bridge が SkyFrost cloud API (`engine.Cloud.Sessions/Records/Contacts`) や
engine record (`engine.RecordManager.FetchRecord`, `WorldStartSettings.Record`) を
触る場合、`mod/src/ResoniteIO/ResoniteIO.csproj` の GamePath `<Reference>` ブロックに
明示参照を足す必要がある。FrooxEngine.dll / Elements.Core.dll は元から参照済みだが、
以下は **未参照**なので追加しないと `CS0012: type defined in an assembly not referenced` で落ちる:

- `SkyFrost.Base` (SessionsManager / RecordsManager / ContactManager / SkyFrostInterface / CloudResult)
- `SkyFrost.Base.Models` (SessionInfo / SearchParameters / SearchResults / Record / SessionAccessLevel / OwnerType) — 上と同じ `SkyFrost.Base` namespace
- `FrooxEngine.Store` (`FrooxEngine.Store.Record` — RecordManager.FetchRecord の戻り値 & WorldStartSettings.Record)

いずれも `<Private>False</Private>` (engine 同梱を再利用、plugin folder に同梱しない)。

**Why:** Step 6 (World modality) の Bridge 実装で確認。csproj は使う game DLL を 1 本ずつ
HintPath 参照する方式で、transitive な自動解決はしない。

**How to apply:** cloud / record / contact / session を読む新規 Bridge を書いたら、
build 前に上記 3 つ (該当するもの) が csproj に居るか確認する。devcontainer では game DLL は
`/resonite/` (= `$(GamePath)`、ResonitePath=/resonite) に在る。`dotnet build ResoniteIO.csproj -c Release`
を mod 単体で回せば Core 変更を待たずに compile 検証できる ($HOME に game dir が無くても /resonite で解決)。

関連: \[\[bridge-engine-thread-dispatch\]\]
