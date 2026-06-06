using System.Net.Sockets;
using Grpc.Net.Client;
using ResoniteIO.Core.Camera;
using ResoniteIO.Core.ContextMenu;
using ResoniteIO.Core.Cursor;
using ResoniteIO.Core.Dash;
using ResoniteIO.Core.Display;
using ResoniteIO.Core.Inventory;
using ResoniteIO.Core.Locomotion;
using ResoniteIO.Core.Manipulation;
using ResoniteIO.Core.Microphone;
using ResoniteIO.Core.Session;
using ResoniteIO.Core.Speaker;

namespace ResoniteIO.Core.Tests.Common;

/// <summary>
/// テスト用に <see cref="SessionHost"/> を tmp_path UDS 上で起動・停止する harness。
/// </summary>
/// <remarks>
/// <c>RESONITE_IO_SOCKET</c> env var を読み書きするため、これを使うテストクラスは
/// xunit collection <c>"SessionHostEnv"</c> で直列化する必要がある。
/// </remarks>
internal sealed class SessionHostHarness : IAsyncDisposable
{
    public string SocketPath { get; }
    public SessionHost Host { get; }

    private readonly CancellationTokenSource _cts;
    private readonly string? _previousEnv;
    private bool _disposed;

    private SessionHostHarness(
        string socketPath,
        SessionHost host,
        CancellationTokenSource cts,
        string? previousEnv
    )
    {
        SocketPath = socketPath;
        Host = host;
        _cts = cts;
        _previousEnv = previousEnv;
    }

    public static Task<SessionHostHarness> StartAsync(
        ISessionBridge? bridge = null,
        ICameraBridge? cameraBridge = null,
        IDisplayBridge? displayBridge = null,
        ILocomotionBridge? locomotionBridge = null,
        ISpeakerBridge? speakerBridge = null,
        IMicrophoneBridge? microphoneBridge = null,
        IContextMenuBridge? contextMenuBridge = null,
        IDashBridge? dashBridge = null,
        IManipulationBridge? manipulationBridge = null,
        IInventoryBridge? inventoryBridge = null,
        ICursorBridge? cursorBridge = null
    ) =>
        StartAsync(
            Path.Combine(Path.GetTempPath(), $"rio-test-{Guid.NewGuid():N}.sock"),
            bridge,
            cameraBridge,
            displayBridge,
            locomotionBridge,
            speakerBridge,
            microphoneBridge,
            contextMenuBridge,
            dashBridge,
            manipulationBridge,
            inventoryBridge,
            cursorBridge
        );

    public static async Task<SessionHostHarness> StartAsync(
        string socketPath,
        ISessionBridge? bridge = null,
        ICameraBridge? cameraBridge = null,
        IDisplayBridge? displayBridge = null,
        ILocomotionBridge? locomotionBridge = null,
        ISpeakerBridge? speakerBridge = null,
        IMicrophoneBridge? microphoneBridge = null,
        IContextMenuBridge? contextMenuBridge = null,
        IDashBridge? dashBridge = null,
        IManipulationBridge? manipulationBridge = null,
        IInventoryBridge? inventoryBridge = null,
        ICursorBridge? cursorBridge = null
    )
    {
        var previousEnv = Environment.GetEnvironmentVariable("RESONITE_IO_SOCKET");
        Environment.SetEnvironmentVariable("RESONITE_IO_SOCKET", socketPath);

        var cts = new CancellationTokenSource();
        SessionHost host;
        try
        {
            host = SessionHost.Start(
                new NullLogSink(),
                cts.Token,
                bridge,
                cameraBridge,
                displayBridge,
                locomotionBridge,
                speakerBridge,
                microphoneBridge,
                contextMenuBridge,
                dashBridge,
                manipulationBridge: manipulationBridge,
                inventoryBridge: inventoryBridge,
                cursorBridge: cursorBridge
            );
        }
        catch
        {
            Environment.SetEnvironmentVariable("RESONITE_IO_SOCKET", previousEnv);
            cts.Dispose();
            throw;
        }

        await TestPolling.WaitUntilAsync(
            () => File.Exists(socketPath),
            TimeSpan.FromSeconds(5),
            $"socket file did not appear at {socketPath}"
        );

        return new SessionHostHarness(socketPath, host, cts, previousEnv);
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

        _cts.Cancel();
        try
        {
            await Host.DisposeAsync();
        }
        catch { }
        _cts.Dispose();

        Environment.SetEnvironmentVariable("RESONITE_IO_SOCKET", _previousEnv);
        try
        {
            File.Delete(SocketPath);
        }
        catch { }
    }
}
