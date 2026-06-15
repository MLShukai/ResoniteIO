using System.Diagnostics;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Server.Kestrel.Core;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using ResoniteIO.Core.Auth;
using ResoniteIO.Core.Camera;
using ResoniteIO.Core.Connection;
using ResoniteIO.Core.ContextMenu;
using ResoniteIO.Core.Cursor;
using ResoniteIO.Core.Dash;
using ResoniteIO.Core.Display;
using ResoniteIO.Core.Grabber;
using ResoniteIO.Core.Info;
using ResoniteIO.Core.Inventory;
using ResoniteIO.Core.Lifecycle;
using ResoniteIO.Core.Locomotion;
using ResoniteIO.Core.Logging;
using ResoniteIO.Core.Microphone;
using ResoniteIO.Core.Session;
using ResoniteIO.Core.Speaker;
using ResoniteIO.Core.World;

namespace ResoniteIO.Core.Hosting;

/// <summary>
/// Kestrel + UDS 上で ResoniteIO の全モダリティ gRPC service を hosting する lifecycle。
/// </summary>
/// <remarks>
/// <para>
/// 全モダリティ (<see cref="ConnectionService"/> / <see cref="CameraService"/> 等) の
/// gRPC service を 1 つの UDS endpoint に集約するプロセス全体の host。
/// 新しいモダリティを追加するときも本クラスから <c>MapGrpcService&lt;NewService&gt;()</c>
/// する (UDS は 1 本に固定し、client は modality ごとに stub を切り替える)。
/// </para>
/// <para>
/// socket path 解決順: <c>RESONITE_IO_SOCKET</c> (フルパス) →
/// <c>RESONITE_IO_SOCKET_DIR</c> 配下の <c>resonite-{pid}.sock</c> →
/// <c>$HOME/.resonite-io/resonite-{pid}.sock</c>。デフォルトを <c>$HOME</c> 配下にする
/// のは Steam pressure-vessel が <c>/home/$USER</c> を sandbox に pass-through するため:
/// mod (sandbox 内) とホスト/コンテナ Python client が同じ inode に到達できる
/// (Docker は <c>${HOME}/.resonite-io</c> を <c>/home/dev/.resonite-io</c> に bind し
/// username 差を吸収)。
/// </para>
/// </remarks>
public sealed class GrpcHost : IAsyncDisposable
{
    private const string SocketFilePrefix = "resonite-";
    private const string SocketFileSuffix = ".sock";

    private readonly WebApplication _app;
    private readonly ILogSink _log;
    private readonly Task _runTask;
    private bool _disposed;

    /// <summary>
    /// bind 済み UDS のフルパス。<see cref="Start"/> 復帰時点で filesystem 上に
    /// socket が現れている保証があり、client は race 無しに connect できる。
    /// </summary>
    public string SocketPath { get; }

    private GrpcHost(WebApplication app, ILogSink log, string socketPath, Task runTask)
    {
        _app = app;
        _log = log;
        SocketPath = socketPath;
        _runTask = runTask;
    }

    /// <summary>
    /// Kestrel の listen 完了を同期的に待ってから返す。停止は dispose または
    /// <paramref name="cancellationToken"/> 経由。
    /// </summary>
    /// <remarks>
    /// Bridge 引数は全て optional (モダリティ未提供構成や Core 単体テストとの両立)。
    /// null Bridge を持つ Service は呼ばれた時点で <c>Unavailable</c> を返し、
    /// 未注入モダリティは起動時に WARN を 1 行ずつ列挙する。
    /// socket path を解決できない場合 (<c>HOME</c> 未設定等) は
    /// <see cref="InvalidOperationException"/>。
    /// </remarks>
    public static GrpcHost Start(
        ILogSink log,
        CancellationToken cancellationToken,
        IConnectionBridge? bridge = null,
        ICameraBridge? cameraBridge = null,
        IDisplayBridge? displayBridge = null,
        ILocomotionBridge? locomotionBridge = null,
        ISpeakerBridge? speakerBridge = null,
        IMicrophoneBridge? microphoneBridge = null,
        IContextMenuBridge? contextMenuBridge = null,
        IDashBridge? dashBridge = null,
        IWorldBridge? worldBridge = null,
        IGrabberBridge? grabberBridge = null,
        IInventoryBridge? inventoryBridge = null,
        ICursorBridge? cursorBridge = null,
        IInfoBridge? infoBridge = null,
        ISessionBridge? sessionBridge = null,
        IAuthBridge? authBridge = null,
        ILifecycleBridge? lifecycleBridge = null
    )
    {
        ArgumentNullException.ThrowIfNull(log);

        var socketPath = ResolveSocketPath();

        var socketDir = Path.GetDirectoryName(socketPath);
        if (!string.IsNullOrEmpty(socketDir))
        {
            Directory.CreateDirectory(socketDir);
            PurgeStaleSockets(socketDir, Process.GetCurrentProcess().Id, log);
        }

        TryUnlink(socketPath);

        var builder = WebApplication.CreateSlimBuilder();
        // Camera が 4K で 64MB クラスの RGBA8 raw フレームを流すため上限を外す
        // (proto 側では上限を設けない方針 — Plan §1)。
        builder.Services.AddGrpc(o =>
        {
            o.MaxReceiveMessageSize = int.MaxValue;
            o.MaxSendMessageSize = int.MaxValue;
        });
        builder.Services.AddSingleton(log);

        // 注入された Bridge だけを DI 登録し、未注入のモダリティ名を listen 成功後の
        // WARN 用に控える。登録順 = WARN 出力順なので呼び出し順を変えない。
        var missing = new List<string>();
        void Register<T>(T? b, string modality)
            where T : class
        {
            if (b is not null)
            {
                builder.Services.AddSingleton(b);
            }
            else
            {
                missing.Add(modality);
            }
        }

        Register(bridge, "Connection");
        Register(infoBridge, "Info");
        Register(cameraBridge, "Camera");
        Register(displayBridge, "Display");
        Register(locomotionBridge, "Locomotion");
        Register(speakerBridge, "Speaker");
        Register(microphoneBridge, "Microphone");
        Register(contextMenuBridge, "ContextMenu");
        Register(dashBridge, "Dash");
        Register(worldBridge, "World");
        Register(grabberBridge, "Grabber");
        Register(inventoryBridge, "Inventory");
        Register(cursorBridge, "Cursor");
        Register(sessionBridge, "Session");
        Register(authBridge, "Auth");
        Register(lifecycleBridge, "Lifecycle");

        builder.WebHost.ConfigureKestrel(opts =>
        {
            opts.ListenUnixSocket(
                socketPath,
                listenOpts => listenOpts.Protocols = HttpProtocols.Http2
            );
        });

        var app = builder.Build();
        app.MapGrpcService<ConnectionService>();
        app.MapGrpcService<InfoService>();
        app.MapGrpcService<CameraService>();
        app.MapGrpcService<DisplayService>();
        app.MapGrpcService<LocomotionService>();
        app.MapGrpcService<SpeakerService>();
        app.MapGrpcService<MicrophoneService>();
        app.MapGrpcService<ContextMenuService>();
        app.MapGrpcService<DashService>();
        app.MapGrpcService<WorldService>();
        app.MapGrpcService<GrabberService>();
        app.MapGrpcService<InventoryService>();
        app.MapGrpcService<CursorService>();
        app.MapGrpcService<SessionService>();
        app.MapGrpcService<AuthService>();
        app.MapGrpcService<LifecycleService>();

        log.LogInfo($"GrpcHost binding UDS at {socketPath}");

        // Sync-wait on StartAsync so SocketPath is guaranteed accept-ready on return.
        try
        {
            app.StartAsync(cancellationToken).GetAwaiter().GetResult();
        }
        catch (Exception ex)
        {
            log.LogError($"GrpcHost failed to start Kestrel: {ex}");
            TryUnlink(socketPath);
            app.DisposeAsync().AsTask().GetAwaiter().GetResult();
            throw;
        }

        log.LogInfo($"GrpcHost listening on {socketPath}");

        foreach (var modality in missing)
        {
            log.LogWarning($"{modality} modality is not configured.");
        }

        var runTask = Task.Run(
            async () =>
            {
                try
                {
                    await app.WaitForShutdownAsync(cancellationToken).ConfigureAwait(false);
                }
                catch (OperationCanceledException) { }
                catch (Exception ex)
                {
                    log.LogError($"GrpcHost runTask faulted: {ex}");
                }
            },
            CancellationToken.None
        );

        return new GrpcHost(app, log, socketPath, runTask);
    }

    public async ValueTask DisposeAsync()
    {
        if (_disposed)
        {
            return;
        }
        _disposed = true;

        try
        {
            await _app.StopAsync().ConfigureAwait(false);
        }
        catch (Exception ex)
        {
            _log.LogWarning($"GrpcHost.StopAsync threw: {ex.GetType().Name}: {ex.Message}");
        }

        try
        {
            await _runTask.ConfigureAwait(false);
        }
        catch (OperationCanceledException) { }
        catch (Exception ex)
        {
            _log.LogWarning($"GrpcHost run task threw: {ex.GetType().Name}: {ex.Message}");
        }

        await _app.DisposeAsync().ConfigureAwait(false);
        TryUnlink(SocketPath);
    }

    private static string ResolveSocketPath()
    {
        var explicitPath = Environment.GetEnvironmentVariable("RESONITE_IO_SOCKET");
        if (!string.IsNullOrEmpty(explicitPath))
        {
            return explicitPath;
        }

        var pid = Process.GetCurrentProcess().Id;
        var socketName = $"resonite-{pid}.sock";

        var socketDir = Environment.GetEnvironmentVariable("RESONITE_IO_SOCKET_DIR");
        if (!string.IsNullOrEmpty(socketDir))
        {
            return Path.Combine(socketDir, socketName);
        }

        var home = Environment.GetEnvironmentVariable("HOME");
        if (!string.IsNullOrEmpty(home))
        {
            return Path.Combine(home, ".resonite-io", socketName);
        }

        throw new InvalidOperationException(
            "Cannot resolve UDS path: set RESONITE_IO_SOCKET, RESONITE_IO_SOCKET_DIR, "
                + "or ensure HOME is set."
        );
    }

    private static void TryUnlink(string path)
    {
        try
        {
            File.Delete(path);
        }
        catch (FileNotFoundException) { }
        catch (DirectoryNotFoundException) { }
        catch
        {
            // best-effort: 削除失敗でも次回起動時に上書きされる。
        }
    }

    // SIGKILL 等で前回の DisposeAsync / Plugin.OnProcessExit を踏まずに死んだ場合、
    // resonite-{pid}.sock が残留する。次回起動時に死んだ PID 由来のものだけ掃除する
    // ことで、host_agent.py の resonite-stop が SIGKILL に踏み切っても自己回復する。
    private static void PurgeStaleSockets(string directory, int currentPid, ILogSink log)
    {
        if (!Directory.Exists(directory))
        {
            return;
        }

        var removed = 0;
        foreach (
            var path in Directory.EnumerateFiles(
                directory,
                $"{SocketFilePrefix}*{SocketFileSuffix}"
            )
        )
        {
            var name = Path.GetFileName(path);
            var pidPart = name.Substring(
                SocketFilePrefix.Length,
                name.Length - SocketFilePrefix.Length - SocketFileSuffix.Length
            );

            if (!int.TryParse(pidPart, out var pid))
            {
                continue;
            }

            if (pid != currentPid && IsProcessAlive(pid))
            {
                continue;
            }

            TryUnlink(path);
            removed++;
        }

        if (removed > 0)
        {
            log.LogInfo($"Removed {removed} stale UDS socket file(s) under {directory}");
        }
    }

    private static bool IsProcessAlive(int pid)
    {
        if (pid <= 0)
        {
            return false;
        }

        try
        {
            using var proc = Process.GetProcessById(pid);
            return !proc.HasExited;
        }
        catch (ArgumentException)
        {
            return false;
        }
        catch (InvalidOperationException)
        {
            return false;
        }
    }
}
