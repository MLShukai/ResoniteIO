namespace ResoniteIO.Core.Info;

/// <summary>
/// server が動作する OS プラットフォーム (proto <c>ServerPlatform</c> から独立した Core 層 enum)。
/// </summary>
public enum ServerPlatform
{
    Unspecified,
    Windows,
    Osx,
    Linux,
    Android,
    Other,
}

/// <summary>
/// 実行中の mod / engine のメタ情報 (proto <c>ServerInfo</c> から独立した Core 層 POCO)。
/// </summary>
/// <param name="ModVersion">csproj <c>&lt;Version&gt;</c> 由来の mod バージョン文字列。</param>
/// <param name="EngineVersion">engine のバージョン文字列 (<c>Engine.VersionString</c>)。</param>
/// <param name="Platform">Resonite クライアントが動作する OS プラットフォーム。</param>
/// <param name="IsWine">Wine/Proton 上で動作しているか (<c>Engine.IsWine</c>)。</param>
/// <param name="ResonitePid">
/// engine プロセス (Resonite.exe) の host PID (<c>Environment.ProcessId</c>)。engine はネイティブ
/// Linux で動くため host kernel PID で、pgrep/os.kill に使える。不明なら 0。
/// </param>
/// <param name="RendererPid">
/// renderer プロセス (Renderite.Renderer.exe) の host PID
/// (<c>RenderSystem.RendererProcess</c>)。headless / renderer 無しなら 0。engine の直接の子なので
/// Proton 下では launcher/wrapper の PID のことがある。mod-init 時点の値で renderer 再起動は非追跡。
/// </param>
public sealed record ServerInfoSnapshot(
    string ModVersion,
    string EngineVersion,
    ServerPlatform Platform,
    bool IsWine,
    int ResonitePid,
    int RendererPid
);

/// <summary>Mod 側 (FrooxEngine) が実装し DI で注入する server メタ情報供給の抽象。</summary>
/// <remarks>
/// 4 値は engine 初期化完了 (mod の OnEngineReady) 時点で確定し以後不変なので、
/// 実装は起動時に 1 回確定した不変 snapshot を返せばよい。任意スレッドから呼んでよい。
/// </remarks>
public interface IInfoBridge
{
    /// <summary>実行中 server の不変 snapshot を読む (副作用なし・任意スレッド可)。</summary>
    ServerInfoSnapshot ReadServerInfo();
}
