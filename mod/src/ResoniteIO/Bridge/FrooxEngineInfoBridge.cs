using System;
using FrooxEngine;
using ResoniteIO.Core.Info;
using ResoniteIO.Core.Logging;

namespace ResoniteIO.Bridge;

/// <summary>
/// FrooxEngine の version / platform / Wine 判定を Core 層へ露出する Bridge 実装。
/// </summary>
/// <remarks>
/// 4 値 (mod_version / engine_version / platform / is_wine) は engine 初期化完了後
/// 不変 (<c>DetectWine()</c> は <c>Engine.Initialize</c> 内で完了し、mod の
/// OnEngineReady 時点で確定) なので、ctor で 1 回 snapshot を確定し以後はそれを
/// 返すだけ。event 購読・Dispose は不要で、任意スレッドから読める。
/// </remarks>
internal sealed class FrooxEngineInfoBridge : IInfoBridge
{
    private readonly ServerInfoSnapshot _snapshot;

    public FrooxEngineInfoBridge(Engine engine, string modVersion, ILogSink log)
    {
        ArgumentNullException.ThrowIfNull(engine);
        ArgumentNullException.ThrowIfNull(modVersion);
        ArgumentNullException.ThrowIfNull(log);

        _snapshot = new ServerInfoSnapshot(
            modVersion,
            engine.VersionString,
            MapPlatform(engine.Platform),
            engine.IsWine
        );
        log.LogInfo(
            $"Server info: mod={_snapshot.ModVersion} engine={_snapshot.EngineVersion} "
                + $"platform={_snapshot.Platform} wine={_snapshot.IsWine}"
        );
    }

    public ServerInfoSnapshot ReadServerInfo() => _snapshot;

    /// <summary><see cref="Platform"/> → Core enum の明示変換。未知値は <c>Unspecified</c>。</summary>
    private static ServerPlatform MapPlatform(Platform platform) =>
        platform switch
        {
            Platform.Windows => ServerPlatform.Windows,
            Platform.OSX => ServerPlatform.Osx,
            Platform.Linux => ServerPlatform.Linux,
            Platform.Android => ServerPlatform.Android,
            Platform.Other => ServerPlatform.Other,
            _ => ServerPlatform.Unspecified,
        };
}
