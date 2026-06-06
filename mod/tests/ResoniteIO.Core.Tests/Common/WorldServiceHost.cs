using System.Net.Sockets;
using Grpc.Net.Client;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Server.Kestrel.Core;
using Microsoft.Extensions.DependencyInjection;
using ResoniteIO.Core.Logging;
using ResoniteIO.Core.World;

namespace ResoniteIO.Core.Tests.Common;

/// <summary>
/// World 単体テスト用の最小 Kestrel + UDS gRPC host。
/// </summary>
/// <remarks>
/// <para>
/// Step 6 の並行作業時点で <c>SessionHost.cs</c> への World mount は別エージェントが
/// 進めている。本 helper は test 専用に <see cref="WorldService"/> だけを載せた host を
/// 立て、SessionHost 統合と独立に round-trip を検証する (<see cref="DisplayServiceHost"/>
/// と同じ隔離戦略)。
/// </para>
/// <para>
/// bridge を渡さない (null) 場合も <see cref="WorldService"/> は mount するが
/// bridge 未注入になるため、各 RPC は Service 契約に従い <c>Unavailable</c> を返す。
/// </para>
/// </remarks>
internal sealed class WorldServiceHost : IAsyncDisposable
{
    private readonly WebApplication _app;
    private bool _disposed;

    public string SocketPath { get; }

    private WorldServiceHost(WebApplication app, string socketPath)
    {
        _app = app;
        SocketPath = socketPath;
    }

    public static async Task<WorldServiceHost> StartAsync(IWorldBridge? bridge = null)
    {
        var socketPath = Path.Combine(
            Path.GetTempPath(),
            $"rio-world-test-{Guid.NewGuid():N}.sock"
        );

        var builder = WebApplication.CreateSlimBuilder();
        builder.Services.AddGrpc();
        builder.Services.AddSingleton<ILogSink>(new NullLogSink());
        if (bridge is not null)
        {
            builder.Services.AddSingleton(bridge);
        }
        builder.Services.AddSingleton<WorldService>();
        builder.WebHost.ConfigureKestrel(opts =>
        {
            opts.ListenUnixSocket(
                socketPath,
                listenOpts => listenOpts.Protocols = HttpProtocols.Http2
            );
        });

        var app = builder.Build();
        app.MapGrpcService<WorldService>();

        await app.StartAsync().ConfigureAwait(false);

        await TestPolling.WaitUntilAsync(
            () => File.Exists(socketPath),
            TimeSpan.FromSeconds(5),
            $"world socket file did not appear at {socketPath}"
        );

        return new WorldServiceHost(app, socketPath);
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
