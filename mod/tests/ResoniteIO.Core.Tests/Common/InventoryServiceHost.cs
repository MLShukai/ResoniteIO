using System.Net.Sockets;
using Grpc.Net.Client;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Server.Kestrel.Core;
using Microsoft.Extensions.DependencyInjection;
using ResoniteIO.Core.Inventory;
using ResoniteIO.Core.Logging;

namespace ResoniteIO.Core.Tests.Common;

/// <summary>
/// Inventory 単体テスト用の最小 Kestrel + UDS gRPC host。
/// </summary>
/// <remarks>
/// <see cref="InventoryService"/> だけを載せた host を立てて round-trip 検証を可能にする
/// (<see cref="DisplayServiceHost"/> と同 pattern)。<paramref name="bridge"/> を null で渡すと
/// bridge 未登録の <c>Unavailable</c> 経路も検証できる (DI は ctor の default null を使う)。
/// </remarks>
internal sealed class InventoryServiceHost : IAsyncDisposable
{
    private readonly WebApplication _app;
    private bool _disposed;

    public string SocketPath { get; }

    private InventoryServiceHost(WebApplication app, string socketPath)
    {
        _app = app;
        SocketPath = socketPath;
    }

    public static async Task<InventoryServiceHost> StartAsync(IInventoryBridge? bridge = null)
    {
        var socketPath = Path.Combine(
            Path.GetTempPath(),
            $"rio-inventory-test-{Guid.NewGuid():N}.sock"
        );

        var builder = WebApplication.CreateSlimBuilder();
        builder.Services.AddGrpc();
        builder.Services.AddSingleton<ILogSink>(new NullLogSink());
        if (bridge is not null)
        {
            builder.Services.AddSingleton(bridge);
        }
        builder.Services.AddSingleton<InventoryService>();
        builder.WebHost.ConfigureKestrel(opts =>
        {
            opts.ListenUnixSocket(
                socketPath,
                listenOpts => listenOpts.Protocols = HttpProtocols.Http2
            );
        });

        var app = builder.Build();
        app.MapGrpcService<InventoryService>();

        await app.StartAsync().ConfigureAwait(false);

        await TestPolling.WaitUntilAsync(
            () => File.Exists(socketPath),
            TimeSpan.FromSeconds(5),
            $"inventory socket file did not appear at {socketPath}"
        );

        return new InventoryServiceHost(app, socketPath);
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
