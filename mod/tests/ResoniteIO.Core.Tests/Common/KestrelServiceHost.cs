using System.Net.Sockets;
using Grpc.Net.Client;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Server.Kestrel.Core;
using Microsoft.Extensions.DependencyInjection;
using ResoniteIO.Core.Logging;

namespace ResoniteIO.Core.Tests.Common;

/// <summary>
/// 単機能 gRPC Service の round-trip テスト用に、Kestrel + 実 UDS で in-process server を
/// 立てる共通基盤。<typeparamref name="TService"/> だけを mount した host を起動し、
/// 実 wire を通したラウンドトリップ検証を可能にする。
/// </summary>
/// <remarks>
/// <para>
/// 各モダリティ用の <c>XxxServiceHost</c> は本クラスを継承し、socket 接頭辞と bridge の
/// DI 登録 (固有部分) だけを <see cref="StartCoreAsync"/> に渡す。Kestrel 起動 /
/// channel 生成 / dispose の同形ボイラープレートはここに集約する。
/// </para>
/// <para>
/// <c>SessionHost</c> 統合経路 (複数 Service を mount し env var で socket を解決する)
/// は <see cref="SessionHostHarness"/> が担当する。本クラスは単一 Service を隔離して
/// 検証する用途に限定する。
/// </para>
/// </remarks>
internal abstract class KestrelServiceHost<TService> : IAsyncDisposable
    where TService : class
{
    private readonly WebApplication _app;
    private bool _disposed;

    public string SocketPath { get; }

    private protected KestrelServiceHost(WebApplication app, string socketPath)
    {
        _app = app;
        SocketPath = socketPath;
    }

    /// <summary>
    /// <typeparamref name="TService"/> だけを載せた Kestrel + UDS host を起動する。
    /// </summary>
    /// <param name="socketLabel">
    /// socket file 名の接頭辞 (例: <c>display</c>)。モダリティ間で衝突しないようにする。
    /// </param>
    /// <param name="configureBridge">
    /// bridge を DI 登録する固有処理。bridge を渡さない (null 経路) 構成では何もしない
    /// delegate を渡せばよい。
    /// </param>
    private protected static async Task<(WebApplication app, string socketPath)> StartCoreAsync(
        string socketLabel,
        Action<IServiceCollection> configureBridge
    )
    {
        var socketPath = Path.Combine(
            Path.GetTempPath(),
            $"rio-{socketLabel}-test-{Guid.NewGuid():N}.sock"
        );

        var builder = WebApplication.CreateSlimBuilder();
        builder.Services.AddGrpc();
        builder.Services.AddSingleton<ILogSink>(new NullLogSink());
        configureBridge(builder.Services);
        builder.Services.AddSingleton<TService>();
        builder.WebHost.ConfigureKestrel(opts =>
        {
            opts.ListenUnixSocket(
                socketPath,
                listenOpts => listenOpts.Protocols = HttpProtocols.Http2
            );
        });

        var app = builder.Build();
        app.MapGrpcService<TService>();

        await app.StartAsync().ConfigureAwait(false);

        await TestPolling.WaitUntilAsync(
            () => File.Exists(socketPath),
            TimeSpan.FromSeconds(5),
            $"{socketLabel} socket file did not appear at {socketPath}"
        );

        return (app, socketPath);
    }

    public GrpcChannel CreateChannel()
    {
        return GrpcChannel.ForAddress(
            "http://localhost",
            new GrpcChannelOptions
            {
                HttpHandler = new SocketsHttpHandler
                {
                    ConnectCallback = async (_, ct) =>
                    {
                        var sock = new Socket(
                            AddressFamily.Unix,
                            SocketType.Stream,
                            ProtocolType.Unspecified
                        );
                        await sock.ConnectAsync(new UnixDomainSocketEndPoint(SocketPath), ct)
                            .ConfigureAwait(false);
                        return new NetworkStream(sock, ownsSocket: true);
                    },
                },
            }
        );
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
        catch { }

        await _app.DisposeAsync().ConfigureAwait(false);

        try
        {
            File.Delete(SocketPath);
        }
        catch { }
    }
}
