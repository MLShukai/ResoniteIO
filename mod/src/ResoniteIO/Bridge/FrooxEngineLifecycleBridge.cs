using System;
using System.Threading.Tasks;
using FrooxEngine;
using ResoniteIO.Core.Lifecycle;
using ResoniteIO.Core.Logging;

namespace ResoniteIO.Bridge;

/// <summary>
/// FrooxEngine の <see cref="Engine.RequestShutdown"/> を介したグレースフル終了を
/// 露出する <see cref="ILifecycleBridge"/> 実装。
/// </summary>
/// <remarks>
/// <para>
/// <b>再入の罠を避けるための fire-and-forget 設計。</b> <see cref="Engine.RequestShutdown"/> は
/// blocking かつ自己破壊的で、<c>OnShutdown</c> 発火 → <c>Task.WhenAll(...).Wait(~1s)</c> →
/// <c>EnvironmentShutdownCallback()</c> でプロセスを畳む。これが <c>AppDomain.ProcessExit</c> →
/// <c>ResoniteIOPlugin.SafeShutdown</c> → <c>GrpcHost.DisposeAsync</c> →
/// <c>app.StopAsync()</c> を誘発するため、gRPC ハンドラのスレッド上で同期呼び出しすると、
/// ハンドラが stack 上にいる最中に gRPC server を畳んで応答ロスト / stop デッドロックを招く。
/// </para>
/// <para>
/// そこで本実装は <see cref="Engine.RequestShutdown"/> を engine update tick 上に
/// <c>World.RunSynchronously</c> で <b>enqueue するだけで即座に返る</b> (await しない)。
/// これにより RPC ハンドラは <c>ShutdownResponse</c> を先に返して ACK を flush でき、engine は
/// 次 tick で終了処理を走らせる。流れ: handler return → ACK flush → engine-tick RequestShutdown
/// → ProcessExit → SafeShutdown → in-flight handler が居ない状態で GrpcHost stop。
/// </para>
/// <para>
/// <see cref="Engine.ShutdownRequested"/> が既に <c>true</c> なら no-op で
/// <c>Accepted=false</c> を返す (<see cref="Engine.RequestShutdown"/> 自体も idempotent)。
/// engine 状態を保持せず IDisposable でもない。
/// </para>
/// </remarks>
internal sealed class FrooxEngineLifecycleBridge : ILifecycleBridge
{
    private readonly Engine _engine;
    private readonly ILogSink _log;

    public FrooxEngineLifecycleBridge(Engine engine, ILogSink log)
    {
        ArgumentNullException.ThrowIfNull(engine);
        ArgumentNullException.ThrowIfNull(log);

        _engine = engine;
        _log = log;
    }

    public ShutdownOutcome RequestShutdown()
    {
        if (_engine.ShutdownRequested)
        {
            _log.LogInfo("Lifecycle.Shutdown: engine already shutting down (no-op).");
            return new ShutdownOutcome(Accepted: false);
        }

        _log.LogInfo("Lifecycle.Shutdown: scheduling Engine.RequestShutdown on the engine tick.");

        var world = _engine.WorldManager?.FocusedWorld;
        if (world is not null)
        {
            world.RunSynchronously(InvokeShutdown);
        }
        else
        {
            // 早期 boot などで focused world が無いエッジ: RequestShutdown は bool を立てて
            // callback を発火するだけなので off-tick でも致命的でない (best-effort)。
            _log.LogWarning(
                "Lifecycle.Shutdown: no focused world; requesting shutdown off the engine tick."
            );
            _ = Task.Run(InvokeShutdown);
        }

        return new ShutdownOutcome(Accepted: true);
    }

    private void InvokeShutdown()
    {
        try
        {
            _engine.RequestShutdown();
        }
        catch (Exception ex)
        {
            _log.LogError($"Engine.RequestShutdown threw: {ex}");
        }
    }
}
