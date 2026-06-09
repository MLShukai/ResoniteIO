namespace ResoniteIO.Core.Connection;

/// <summary>
/// 実行中 Mod のメタ情報を Core 層へ供給する値。バージョン定数
/// (<c>PluginMetadata.VERSION</c>) は Mod アセンブリ側にあり Core からは参照できない
/// (Core ← Mod 方向厳守) ため、Mod が DI 経由で本値を注入する。
/// </summary>
/// <param name="Version">csproj <c>&lt;Version&gt;</c> 由来の Mod バージョン文字列。</param>
public sealed record ModInfo(string Version);
