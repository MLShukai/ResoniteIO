using System;
using FrooxEngine;
using ResoniteIO.Core.Connection;
using ResoniteIO.Core.Logging;

namespace ResoniteIO.Bridge;

/// <summary>
/// FrooxEngine の FocusedWorld / LocalUser を Core 層へ露出する Bridge 実装。
/// </summary>
/// <remarks>
/// getter は <c>volatile</c> snapshot を任意スレッドから読むだけ。<c>World.Name</c> /
/// <c>User.UserName</c> は <c>Sync&lt;string&gt;</c> 経由で参照型の代入として publish
/// されるので、読み出しで tearing が起きても crash しない (古い参照が返るだけ)。
/// </remarks>
internal sealed class FrooxEngineConnectionBridge : IConnectionBridge, IDisposable
{
    private readonly WorldManager _worldManager;
    private readonly ILogSink _log;
    private volatile World? _focusedWorld;
    private bool _disposed;

    public FrooxEngineConnectionBridge(Engine engine, ILogSink log)
    {
        ArgumentNullException.ThrowIfNull(engine);
        ArgumentNullException.ThrowIfNull(log);

        _worldManager = engine.WorldManager;
        _log = log;

        // WorldFocused は新規 focus でしか発火しないため、既に focus 済みの状態は
        // event 経由では拾えない。subscribe 前に手で初期 snapshot を採る。
        var initialWorld = _worldManager.FocusedWorld;
        if (initialWorld is not null)
        {
            _focusedWorld = initialWorld;
            LogFocused(initialWorld);
        }

        _worldManager.WorldFocused += OnWorldFocused;
    }

    public string? FocusedWorldName => _focusedWorld?.Name;

    public string? LocalUserName => _focusedWorld?.LocalUser?.UserName;

    private void OnWorldFocused(World world)
    {
        _focusedWorld = world;
        LogFocused(world);
    }

    private void LogFocused(World? world)
    {
        var worldName = world?.Name ?? "<null>";
        var userName = world?.LocalUser?.UserName ?? "<null>";
        _log.LogInfo($"Focused world: {worldName} / LocalUser: {userName}");
    }

    public void Dispose()
    {
        if (_disposed)
        {
            return;
        }
        _disposed = true;

        try
        {
            _worldManager.WorldFocused -= OnWorldFocused;
        }
        catch
        {
            // engine 側が先に破棄されているケース。
        }
    }
}
