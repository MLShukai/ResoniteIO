using Grpc.Core;
using ResoniteIO.Core.Lifecycle;
using ResoniteIO.Core.Tests.Common;
using Xunit;

namespace ResoniteIO.Core.Tests.Lifecycle;

/// <summary>
/// <see cref="Core.Lifecycle.LifecycleService"/> の <c>Shutdown</c> RPC を実 Kestrel + UDS gRPC
/// で end-to-end に流す integration-real テスト。(1) bridge の <see cref="ShutdownOutcome"/> が
/// proto <c>ShutdownResponse.accepted</c> に round-trip すること (accepted=true/false の両方)、
/// (2) bridge 未注入時の <c>Unavailable</c> を検証する。
/// </summary>
/// <remarks>
/// <see cref="GrpcHostHarness"/> は <c>RESONITE_IO_SOCKET</c> env var を読み書きするため
/// <c>"GrpcHostEnv"</c> collection で直列化する (harness の契約)。
/// </remarks>
[Collection("GrpcHostEnv")]
public sealed class LifecycleRoundTripTests
{
    /// <summary>自前 ABC <see cref="ILifecycleBridge"/> の inline fake (testing-strategy 準拠)。</summary>
    private sealed class FakeLifecycleBridge : ILifecycleBridge
    {
        public bool AcceptResult { get; init; } = true;
        public int Calls { get; private set; }

        public ShutdownOutcome RequestShutdown()
        {
            Calls++;
            return new ShutdownOutcome(AcceptResult);
        }
    }

    [Fact]
    public async Task Shutdown_RoundTripsAcceptedTrue_AndInvokesBridgeOnce()
    {
        var bridge = new FakeLifecycleBridge { AcceptResult = true };
        await using var harness = await GrpcHostHarness.StartAsync(lifecycleBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Lifecycle.LifecycleClient(channel);

        var response = await client.ShutdownAsync(new V1.ShutdownRequest());

        Assert.True(response.Accepted);
        Assert.Equal(1, bridge.Calls);
    }

    [Fact]
    public async Task Shutdown_RoundTripsAcceptedFalse_WhenAlreadyShuttingDown()
    {
        var bridge = new FakeLifecycleBridge { AcceptResult = false };
        await using var harness = await GrpcHostHarness.StartAsync(lifecycleBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Lifecycle.LifecycleClient(channel);

        var response = await client.ShutdownAsync(new V1.ShutdownRequest());

        Assert.False(response.Accepted);
    }

    [Fact]
    public async Task Shutdown_WithoutBridge_ReturnsUnavailable()
    {
        await using var harness = await GrpcHostHarness.StartAsync(lifecycleBridge: null);
        using var channel = harness.CreateChannel();
        var client = new V1.Lifecycle.LifecycleClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.ShutdownAsync(new V1.ShutdownRequest())
        );
        Assert.Equal(StatusCode.Unavailable, ex.StatusCode);
    }
}
