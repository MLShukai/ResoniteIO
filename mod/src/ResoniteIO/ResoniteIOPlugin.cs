using System;
using System.IO;
using System.Threading;
using BepInEx;
using BepInEx.Logging;
using BepInEx.NET.Common;
using BepInExResoniteShim;
using BepisResoniteWrapper;
using FrooxEngine;
using ResoniteIO.Bridge;
using ResoniteIO.Core.Camera;
using ResoniteIO.Core.Display;
using ResoniteIO.Core.Session;
using ResoniteIO.Loading;
using ResoniteIO.Logging;

namespace ResoniteIO;

/// <summary>BepisLoader 経由で Resonite に読み込まれる mod のエントリポイント。</summary>
/// <remarks>
/// PluginMetadata の各値は csproj から BepInEx.ResonitePluginInfoProps が build-time に
/// 生成するため、本クラスでは決して定数を二重管理しない。
/// </remarks>
[ResonitePlugin(
    PluginMetadata.GUID,
    PluginMetadata.NAME,
    PluginMetadata.VERSION,
    PluginMetadata.AUTHORS,
    PluginMetadata.REPOSITORY_URL
)]
[BepInDependency(
    BepInExResoniteShim.PluginMetadata.GUID,
    BepInDependency.DependencyFlags.HardDependency
)]
public sealed class ResoniteIOPlugin : BasePlugin
{
    internal static new ManualLogSource Log = null!;

    private PluginAssemblyResolver? _assemblyResolver;
    private BepInExLogSink? _logSink;
    private CancellationTokenSource? _hostCts;
    private SessionHost? _sessionHost;
    private FrooxEngineSessionBridge? _sessionBridge;

    private ICameraBridge? _cameraBridge;
    private RendererFrameInterprocessReceiver? _frameReceiver;
    private IDisplayBridge? _displayBridge;
    private FrooxEngineLocomotionBridge? _locomotionBridge;

    /// <remarks>
    /// 重要: PluginAssemblyResolver attach **以前** に <c>ResoniteIO.Core</c> 配下の型
    /// (<see cref="BepInExLogSink"/> 等) を参照しない。参照すると <c>ResoniteIO.Core.dll</c>
    /// が早期ロードされ、resolver が発火する前に Resonite 同梱の旧 <c>Google.Protobuf</c>
    /// が解決され、後の SessionHost 起動で
    /// <c>TypeLoadException: Could not load type 'Google.Protobuf.IBufferMessage'</c>
    /// となる。<see cref="BepInExLogSink"/> の生成は <see cref="OnEngineReady"/> に遅延する。
    /// FrooxEngine 触りも未初期化リスクのため OnEngineReady 側に置く。
    /// </remarks>
    public override void Load()
    {
        Log = base.Log;

        // resolver は Core 型に触れる前に attach する必要があるため、ManualLogSource を
        // 直接渡し ILogSink を経由しない (上記 remarks 参照)。
        var pluginDirectory =
            Path.GetDirectoryName(typeof(ResoniteIOPlugin).Assembly.Location) ?? string.Empty;
        if (!string.IsNullOrEmpty(pluginDirectory))
        {
            _assemblyResolver = new PluginAssemblyResolver(pluginDirectory, Log);
        }

        ResoniteHooks.OnEngineReady += OnEngineReady;
        Log.LogInfo($"{PluginMetadata.NAME} {PluginMetadata.VERSION} loaded");
    }

    /// <remarks>
    /// BepInEx 6 <c>BasePlugin</c> に Unload hook が無いため、停止は
    /// <see cref="AppDomain.ProcessExit"/> 経由の best-effort。
    /// </remarks>
    private void OnEngineReady()
    {
        Log.LogInfo("Engine ready — starting Session gRPC host");
        try
        {
            _hostCts = new CancellationTokenSource();
            AppDomain.CurrentDomain.ProcessExit += OnProcessExit;
            // Core 型に触れる最初のポイント。Load() で attach 済みの resolver により
            // plugin folder 同梱の Core.dll / Google.Protobuf.dll が優先される。
            _logSink = new BepInExLogSink(Log);
            _sessionBridge = new FrooxEngineSessionBridge(Engine.Current, _logSink);

            var pushedBridge = new PushedFrameCameraBridge();
            _cameraBridge = pushedBridge;
            _frameReceiver = new RendererFrameInterprocessReceiver(pushedBridge, _logSink);
            _frameReceiver.Start();

            _displayBridge = new FrooxEngineDisplayBridge(_logSink);

            _locomotionBridge = new FrooxEngineLocomotionBridge(Engine.Current, _logSink);

            _sessionHost = SessionHost.Start(
                _logSink,
                _hostCts.Token,
                _sessionBridge,
                _cameraBridge,
                _displayBridge,
                _locomotionBridge
            );
            Log.LogInfo($"Session gRPC host bound at: {_sessionHost.SocketPath}");
        }
        catch (Exception ex)
        {
            // partial-failure 回復: ここに到達した時点で先行 ctor / Start が成功した
            // resource (receiver / bridge 群 / cts / 部分起動済み host) が leak しうるため、
            // ProcessExit と同じ Dispose chain を best-effort で回す。
            Log.LogError($"Failed to start Session gRPC host: {ex}");
            SafeShutdown();
        }
    }

    private void OnProcessExit(object? sender, EventArgs e) => SafeShutdown();

    // OnEngineReady catch / OnProcessExit の両方から呼ばれる共通 Dispose chain。
    // 二重呼び出し対策として各 field は Dispose 後に null 化する。
    private void SafeShutdown()
    {
        // Dispose 順: receiver → camera → display → locomotion → session(bridge)
        //   → cts → sessionHost → assemblyResolver。
        // 上流から順に止めることで、下流が残 input を dead bridge に push する race を防ぐ:
        //   - Receiver を先に止めて残 frame が dead CameraBridge に届かないようにする。
        //   - PushedFrameCameraBridge.Dispose は Channel writer を complete し pending な
        //     CameraService.StreamFrames を CameraNotReadyException で抜けさせる。
        //   - LocomotionBridge.Dispose は engine 側 ExternalInput を 0 戻しして idle 化する。
        //   - 最後に SessionHost を止めて全 gRPC service を畳む。
        SafeDispose(_frameReceiver, nameof(_frameReceiver));
        _frameReceiver = null;

        SafeDispose(_cameraBridge as IDisposable, nameof(_cameraBridge));
        _cameraBridge = null;

        SafeDispose(_displayBridge as IDisposable, nameof(_displayBridge));
        _displayBridge = null;

        SafeDispose(_locomotionBridge, nameof(_locomotionBridge));
        _locomotionBridge = null;

        SafeDispose(_sessionBridge, nameof(_sessionBridge));
        _sessionBridge = null;

        // CancellationTokenSource は Cancel + Dispose の 2 段なので inline で扱う。
        try
        {
            _hostCts?.Cancel();
            _hostCts?.Dispose();
        }
        catch (Exception ex)
        {
            try
            {
                Log?.LogWarning(
                    $"SafeDispose({nameof(_hostCts)}) threw: {ex.GetType().Name}: {ex.Message}"
                );
            }
            catch
            {
                // log path may be dead during ProcessExit
            }
        }
        _hostCts = null;

        // SessionHost は IAsyncDisposable のため sync 化して扱う (ProcessExit の制約)。
        try
        {
            _sessionHost?.DisposeAsync().AsTask().GetAwaiter().GetResult();
        }
        catch (Exception ex)
        {
            try
            {
                Log?.LogWarning(
                    $"SafeDispose({nameof(_sessionHost)}) threw: {ex.GetType().Name}: {ex.Message}"
                );
            }
            catch
            {
                // log path may be dead during ProcessExit
            }
        }
        _sessionHost = null;

        SafeDispose(_assemblyResolver, nameof(_assemblyResolver));
        _assemblyResolver = null;
    }

    // ProcessExit 経路では log sink がもう信頼できないので、log は best-effort。
    internal static void SafeDispose(IDisposable? disposable, string label)
    {
        if (disposable is null)
        {
            return;
        }
        try
        {
            disposable.Dispose();
        }
        catch (Exception ex)
        {
            try
            {
                Log?.LogWarning($"SafeDispose({label}) threw: {ex.GetType().Name}: {ex.Message}");
            }
            catch
            {
                // log path may be dead during ProcessExit
            }
        }
    }
}
