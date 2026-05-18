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
using ResoniteIO.Core.Bridge;
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

    // Camera v2: PushedFrameCameraBridge (Channel<CameraFrame>) + RendererFrameInterprocessReceiver
    // (Wine renderer プロセスからの InterprocessLib push 受信)。型は ICameraBridge に
    // 抽象化し、将来 v3 等への差し替え余地を残す。
    private ICameraBridge? _cameraBridge;
    private RendererFrameInterprocessReceiver? _frameReceiver;

    // Display: engine 側 Settings 書き込み Bridge (C7)。SessionHost が DI に取り、
    // DisplayService.Apply / Get の実装を提供する。
    private IDisplayBridge? _displayBridge;

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

            // Camera v2 配線:
            //   renderer plugin (別プロセス)
            //     → InterprocessLib queue
            //       → RendererFrameInterprocessReceiver (engine 側、本 Plugin で構築)
            //         → PushedFrameCameraBridge.Push (Channel<CameraFrame>, latest-wins)
            //           → CameraService.StreamFrames (任意スレッドから pull)
            var pushedBridge = new PushedFrameCameraBridge();
            _cameraBridge = pushedBridge;
            _frameReceiver = new RendererFrameInterprocessReceiver(pushedBridge, _logSink);
            _frameReceiver.Start();

            // Display: engine 側 Settings 書き込み Bridge (C7)。
            _displayBridge = new FrooxEngineDisplayBridge(_logSink);

            _sessionHost = SessionHost.Start(
                _logSink,
                _hostCts.Token,
                _sessionBridge,
                _cameraBridge,
                _displayBridge
            );
            Log.LogInfo($"Session gRPC host bound at: {_sessionHost.SocketPath}");
        }
        catch (Exception ex)
        {
            Log.LogError($"Failed to start Session gRPC host: {ex}");
        }
    }

    // ProcessExit 経路ではログ出力経路がもう信頼できないため例外は飲む。
    private void OnProcessExit(object? sender, EventArgs e)
    {
        // Dispose 順 (v2): Receiver → CameraBridge → SessionBridge → SessionHost。
        //   - Receiver を先に止めないと残 frame が dead bridge に push される
        //   - PushedFrameCameraBridge.Dispose は Channel writer を complete し、
        //     pending な CameraService.StreamFrames を CameraNotReadyException で抜けさせる
        //   - SessionBridge は engine API (FocusedWorld 等) を読むだけなので engine
        //     生存中に dispose しておくのが安全
        //   - SessionHost.Dispose は Kestrel 停止 + UDS unlink まで含む
        try
        {
            _frameReceiver?.Dispose();
        }
        catch { }

        try
        {
            (_cameraBridge as IDisposable)?.Dispose();
        }
        catch { }

        try
        {
            _sessionBridge?.Dispose();
        }
        catch { }

        // _displayBridge は engine API 直叩きで IDisposable 実装無し。明示 dispose 不要。

        try
        {
            _hostCts?.Cancel();
        }
        catch { }

        try
        {
            _sessionHost?.DisposeAsync().AsTask().GetAwaiter().GetResult();
        }
        catch { }

        try
        {
            _assemblyResolver?.Dispose();
        }
        catch { }
    }
}
