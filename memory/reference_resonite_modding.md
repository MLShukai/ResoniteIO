---
name: Resonite modding wiki 抜粋
description: modding.resonite.net (公式 wiki) から抽出した Resonite mod 開発の前提知識・URL・コード雛形のリファレンス。
type: reference
---

公式 wiki [modding.resonite.net](https://modding.resonite.net/) を 2026-05-13 時点で巡回して抽出。
**多くのページが "work in progress" であり**、実装詳細は BepInEx 本家 / lethal.wiki / `decompiled/` を読みに行くのが速い。本メモはエントリポイントと既知の挙動の固定知識として使う。

このリポジトリの規約（[CLAUDE.md](../../CLAUDE.md)）はすでに公式 wiki の手順と整合済み（`bep6resonite` テンプレート使用、`tcli` local tool、`BepInEx/plugins/ResoniteIO/` への配置、`OnEngineReady` 購読、`PluginMetadata.*` 自動生成）。本メモは wiki 側の "なぜ" と "どこに何があるか" を補完するために置いている。

## エコシステム全体像

- mod loader は **BepisLoader**。BepInEx をベースにした Resonite 向けディストリビューション。
- 配布は **Thunderstore Resonite community** ([thunderstore.io/c/resonite/](https://thunderstore.io/c/resonite/))。Gale / r2modmanPlus / Thunderstore Mod Manager で BepisLoader ごとインストールするのがエンドユーザー向け推奨経路。
- ソース: [github.com/ResoniteModding](https://github.com/ResoniteModding) (BepisLoader / docs / Templates 等)
- Discord: [discord.gg/vCDJK9xyvm](https://discord.gg/vCDJK9xyvm)
- ライセンス上の立場: 公式 wiki は "an independent project and are not affiliated with Resonite or Yellow Dog Man Studios S.r.o." と明記。Resonite 本体に対しては非公式コミュニティ。
- mod 利用そのものは慣習的に黙認〜歓迎（\[\[../../resonite_io_plan\]\] §7 と整合）。

## ロード機構

- Windows: **HookFxr** で .NET ホストにフック。手動セットアップ時は Resonite ディレクトリ直下の `hookfxr.ini` で `enable=false` → `enable=true` に書き換える。
- Linux: `LinuxBootstrap.sh` を BepisLoader 提供版で差し替え、`BepisLoader.dll` を読み込ませる。Steam Linux ネイティブ FrooxEngine 構成（Proton 経由 Renderite）は本リポジトリの想定環境（[CLAUDE.md](../../CLAUDE.md)「Resonite クライアント」節）。
- ロード後、BepisLoader が以下のディレクトリを規約として持つ:

```text
<Resonite>/BepInEx/
├── plugins/          # 通常の mod (.dll)。本プロジェクトは plugins/ResoniteIO/
├── patchers/         # プリロードパッチ (BasePatcher 派生)
├── config/           # 設定ファイル (.cfg)
└── LogOutput.log     # ランタイムログ (just log で tail)
```

- 補助ライブラリ:
  - `BepisLocaleLoader` — i18n
  - `BepisModSettings` — ゲーム内設定 UI
  - HarmonyX（pip-in パッチ）
  - `BepisResoniteWrapper`（`ResoniteHooks` を提供）

## 開発スタック（公式テンプレート準拠）

- 必須: **.NET SDK 10.0** + IDE (VS Code / Visual Studio / Rider)
- BepisLoader を Resonite に入れた状態（実機確認用）
- 推奨: デコンパイラ（ILSpy / dnSpy / dotPeek / `ilspycmd`）。本リポジトリは `just decompile` で `decompiled/` に展開する。

### テンプレートのインストール

```sh
dotnet new install BepInEx.Templates::2.0.0-be.* \
  --nuget-source https://nuget-modding.resonite.net/v3/index.json
```

NuGet フィードは `https://nuget-modding.resonite.net/v3/index.json`（本プロジェクトの `mod/NuGet.config` も同じはず）。

### プロジェクト生成

```sh
dotnet new bep6resonite \
  --name MyPluginName \
  --authors "MyName" \
  --packageId net.myname.mypluginname \
  --repositoryUrl "https://github.com/..."
```

オプション: `-ve`（version）/ `-au`（authors）/ `-r`（repo）/ `-p`（packageId）/ `-g`（git init）。

生成物:

- `<Project>/Plugin.cs` — メインコード
- `<Project>.csproj` — `<Authors>` `<Version>` `<Product>` `<PackageId>` `<RepositoryUrl>` から `PluginMetadata.*` が build-time 生成される（`BepInEx.ResonitePluginInfoProps` の役割）
- `thunderstore.toml` — Thunderstore packaging
- `icon.png` — 256×256 推奨

ゲームパス検出（テンプレート側のロジック）の優先順位:

1. `ResonitePath` 環境変数
2. Steam インストール検出
3. NuGet パッケージ参照（dummy 解決）

→ 本リポジトリは `.env` 経由で `ResonitePath` を強制している（CLAUDE.md「実行環境の注意点」）。

## Plugin.cs の最小骨格

```csharp
using BepInEx;
using BepInEx.Logging;
using BepInEx.NET.Common;
using ResoniteModding.BepInExResoniteShim;

[ResonitePlugin(PluginMetadata.GUID, PluginMetadata.NAME, PluginMetadata.VERSION)]
[BepInDependency(BepInExResoniteShim.PluginMetadata.GUID,
                 BepInDependency.DependencyFlags.HardDependency)]
public class Plugin : BasePlugin
{
    internal static new ManualLogSource Log = null!;

    public override void Load()
    {
        Log = base.Log;
        ResoniteHooks.OnEngineReady += OnEngineReady;
    }

    private void OnEngineReady()
    {
        // ここで Engine.Current / FrooxEngine の API に安全アクセス可能
    }
}
```

ポイント:

- `BasePlugin` 継承、`Load()` をオーバーライド。
- `[ResonitePlugin]` の引数はテンプレートが csproj から生成する `PluginMetadata` 定数を参照する（ハードコードしない）。
- **`ResoniteHooks.OnEngineReady` が最重要フック**。`Engine.Current` を含む FrooxEngine API はここから先でないと安全に触れない。プラグインの初期化処理の大部分はここに置く。
- `BepInDependency` で `BepInExResoniteShim`（`ResoniteHooks` の提供元）への依存を明示する。

\[\[../../resonite_io_plan\]\] Step 2 以降で UDS gRPC server を立てる際も、bind は `OnEngineReady` 内で行うのが正解。FrooxEngine の更新スレッドをブロックしない別スレッドで server を回すのは [CLAUDE.md](../../CLAUDE.md) の「C# 側コーディング規約」と整合。

## ロギング

- `ManualLogSource` (`BepInEx.Logging`) を使う。`base.Log` で取得して `Log.LogInfo / LogDebug / LogWarning / LogError` を呼ぶ。
- 出力先は `<Resonite>/BepInEx/LogOutput.log`。本リポジトリでは `just log` で tail する。
- 詳細な使い方は wiki が WIP のため、必要なら lethal.wiki "Using Logging" / BepInEx 公式を参照。

## 設定 (Configuration)

- BepInEx 標準: `Config.Bind<T>(section, key, default, description)` で `ConfigEntry<T>` を取得。
- `ConfigDescription` + `AcceptableValueRange<T>` 等で UI / バリデーションが効く。
- 永続化先: `<Resonite>/BepInEx/config/<plugin>.cfg`（テキスト編集可）。
- ゲーム内設定 UI は `BepisModSettings` が提供。
- wiki 本文は WIP。実装は lethal.wiki "Using configuration files" 参照推奨。

## Patching (HarmonyX)

- `BasePlugin.Load()` の中で `Harmony harmony = new Harmony(PluginMetadata.GUID); harmony.PatchAll();` の形が定石。
- `[HarmonyPatch(typeof(...), nameof(...))]` + `Prefix` / `Postfix` / `Transpiler` static method。
- wiki 本文は WIP。詳細は BepInEx "Patching methods during runtime" を参照。FrooxEngine 内部 API のシグネチャは `decompiled/` で確認する。

## Prepatching

- `BepInEx.NET.Common.Patcher.BasePatcher` を継承し、`TargetDLLs` を列挙、`Patch(AssemblyDefinition)` でアセンブリそのものを書き換える。
- 配置先は `<Resonite>/BepInEx/patchers/`（`plugins/` ではない）。
- ランタイム前に走るので、Harmony で取れない型構造の改変や private アクセサ展開（publicizer 的用途）に使う。
- wiki 本文は WIP。BepInEx "Using preloader patchers" 参照。

## Dependencies

- `[BepInDependency(GUID, DependencyFlags.HardDependency | SoftDependency)]` で BepInEx 側の依存解決。
- Thunderstore 側は `thunderstore.toml` の `[package].dependencies = ["author-Mod-1.2.3"]` で表現する（厳密な書式はテンプレート生成物を参照）。
- wiki 本文は WIP。

## Hot Reload

- wiki 本文は WIP。現状、BepisLoader 単体で in-process hot reload が公式提供されているか不明。
- 実用フローは [CLAUDE.md](../../CLAUDE.md) の通り「`just deploy-mod` → Resonite 再起動 → `just log` で確認」。

## Localization (BepisLocaleLoader)

csproj:

```xml
<PackageReference Include="ResoniteModding.BepisLocaleLoader" Version="1.*" />
```

Plugin 側:

```csharp
[BepInDependency(BepisLocaleLoader.PluginMetadata.GUID,
                 BepInDependency.DependencyFlags.HardDependency)]
```

ファイル配置: `<Plugin>/Locale/{en,ja,...}.json`

```json
{
  "localeCode": "en-US",
  "authors": ["name"],
  "messages": {
    "Settings.dev.author.plugin": "Plugin Name",
    "Settings.dev.author.plugin.config.Key": "Config Item Label"
  }
}
```

キー命名: `Settings.dev.<author>.<plugin>.<category>.<key>`。

API: `"key".T()` で文字列取得、`new ConfigLocale("Settings.key", "Settings.description")` で `ConfigDescription` を i18n 化、動的追加は `LocaleLoader.AddLocaleString()`。

## Packaging / Publishing

- `tcli` (Thunderstore CLI) を local tool として保持し、csproj の `PackTS` MSBuild target が `tcli build` をラップする想定（本プロジェクトの構成と一致）。
- 主要コマンド:
  - `dotnet tcli build` — zip 生成のみ
  - `dotnet build -c Release -t:PackTS -v d` — `PackTS` 経由でビルド + zip 化（本プロジェクトの `just mod-pack`）
  - `dotnet build -c Release -t:PackTS -p:PublishTS=true` — Thunderstore に publish。`TCLI_AUTH_TOKEN` 環境変数が必要
- `thunderstore.toml` で namespace（チーム名）/ name / versionNumber / description / dependencies / icon / readme / DLL+PDB 出力先 / repository / communities / categories を定義。
- 手動 zip 構成（fallback）:

```text
<package>.zip
├── manifest.json
├── README.md
├── icon.png       (256×256)
├── LICENSE
├── CHANGELOG.md   (optional)
└── plugins/
    └── <ModName>/
        ├── <ModName>.dll
        └── <ModName>.pdb
```

- Thunderstore に publish するには事前に [チーム作成](https://thunderstore.io/settings/teams/create/) が必要。

## Updating

- 単純に csproj `<Version>` を上げて再 publish するだけ（tcli が manifest version_number を同期）。
- 制約: **同じコミュニティ・同じチームから上書きする必要がある**。チーム/コミュニティを変えると別 mod 扱い。
- 手動 publish の場合は `manifest.json` の `version_number` を上げて再 zip → アップロード。

## Troubleshooting (公式が言及しているもの)

- ログ: `<Resonite>/BepInEx/LogOutput.log` を最初に見る。
- mod が読まれない: BepInEx コンソール、依存関係解決失敗、`BepInEx/plugins/` 配置位置の 3 点を確認。
- パフォーマンス劣化: mod を 1 つずつ無効化して二分探索、競合確認。
- クラッシュ: 直近追加 mod を外す、Steam で整合性検証。
- Discord で問い合わせる際は Resonite version / mod 一覧 / エラーメッセージを添える。

## ページマップ

| URL                                         | 状態                                 |
| ------------------------------------------- | ------------------------------------ |
| `/getting-started/installation/`            | 充実                                 |
| `/getting-started/using-mods/`              | 充実                                 |
| `/getting-started/troubleshooting/`         | 簡素                                 |
| `/getting-started/overview/`                | 簡素                                 |
| `/creating-a-mod/initial-setup/`            | 充実（ツールリンク多数）             |
| `/creating-a-mod/creating-a-project/`       | 充実（テンプレートコマンド）         |
| `/creating-a-mod/writing-code/`             | 中程度（コード雛形あり、詳細は外部） |
| `/creating-a-mod/packaging-and-publishing/` | 充実                                 |
| `/creating-a-mod/updating/`                 | 簡素                                 |
| `/guides/logging/`                          | **WIP**（lethal.wiki 参照）          |
| `/guides/configuration/`                    | **WIP**（lethal.wiki 参照）          |
| `/guides/patching/`                         | **WIP**（BepInEx 本家参照）          |
| `/guides/prepatching/`                      | **WIP**（BepInEx 本家参照）          |
| `/guides/dependency/`                       | **WIP**                              |
| `/guides/hot-reload/`                       | **WIP**                              |
| `/guides/localization/`                     | 充実                                 |

外部参照のうち頻繁に当たる先:

- BepInEx 公式 docs（patching / prepatching / configuration の一次情報）
- lethal.wiki（BepInEx 系 mod の実例ベース解説）
- `decompiled/`（FrooxEngine 内部 API のシグネチャ確認）
