using System.Net.Sockets;
using Grpc.Net.Client;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Server.Kestrel.Core;
using Microsoft.Extensions.DependencyInjection;
using ResoniteIO.Core.Display;
using ResoniteIO.Core.Logging;

namespace ResoniteIO.Core.Tests.Common;

/// <summary>
/// Display 単体テスト用の最小 Kestrel + UDS gRPC host。
/// </summary>
/// <remarks>
/// <para>
/// Wave 2 では <c>SessionHost.cs</c> に <see cref="DisplayService"/> を mount しない
/// (Plan 同期点制約)。本 helper は test 専用に <see cref="DisplayService"/> だけを
/// 載せた host を立てて round-trip 検証を可能にする。Wave 4 / C8 で
/// <c>SessionHost</c> に mount された後は本 helper は不要になるが、
/// Display 単体の挙動を <see cref="Camera.CameraService"/> 等から隔離する利点もある
/// ので残しておく価値はある (Wave 4+ の整理判断)。
/// </para>
/// <para>
/// 命名は <c>SessionHostHarness</c> と並列。ただし Display の単機能版なので
/// dispose もシンプル (env var lookup や 並列実行の collection 制約は不要)。
/// </para>
/// </remarks>
internal sealed class DisplayServiceHost : IAsyncDisposable
{
    private readonly WebApplication _app;
    private bool _disposed;

    public string SocketPath { get; }

    private DisplayServiceHost(WebApplication app, string socketPath)
    {
        _app = app;
        SocketPath = socketPath;
    }

    public static async Task<DisplayServiceHost> StartAsync(IDisplayBridge bridge)
    {
        ArgumentNullException.ThrowIfNull(bridge);

        var socketPath = Path.Combine(
            Path.GetTempPath(),
            $"rio-display-test-{Guid.NewGuid():N}.sock"
        );

        var builder = WebApplication.CreateSlimBuilder();
        builder.Services.AddGrpc();
        builder.Services.AddSingleton<ILogSink>(new NullLogSink());
        builder.Services.AddSingleton(bridge);
        builder.Services.AddSingleton<DisplayService>();
        builder.WebHost.ConfigureKestrel(opts =>
        {
            opts.ListenUnixSocket(
                socketPath,
                listenOpts => listenOpts.Protocols = HttpProtocols.Http2
            );
        });

        var app = builder.Build();
        app.MapGrpcService<DisplayService>();

        await app.StartAsync().ConfigureAwait(false);

        await TestPolling.WaitUntilAsync(
            () => File.Exists(socketPath),
            TimeSpan.FromSeconds(5),
            $"display socket file did not appear at {socketPath}"
        );

        return new DisplayServiceHost(app, socketPath);
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
