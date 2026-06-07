using Grpc.Core;
using ResoniteIO.Core.Cursor;
using ResoniteIO.Core.Tests.Common;
using ResoniteIO.Core.Tests.Common.Fakes;
using ResoniteIO.V1;
using Xunit;

namespace ResoniteIO.Core.Tests.Cursor;

/// <summary>
/// <see cref="Core.Cursor.CursorService"/> の 2 RPC を実 Kestrel + UDS gRPC で
/// end-to-end に流し、(1) x/y が Bridge に届くこと、(2) Bridge が返した snapshot が
/// <see cref="CursorState"/> に round-trip すること、(3) 正規化範囲チェック
/// (Service 層) と例外 → gRPC Status の翻訳を検証する integration-real テスト。
/// </summary>
/// <remarks>
/// <see cref="GrpcHostHarness"/> は <c>RESONITE_IO_SOCKET</c> env var を読み書きするため
/// <c>"GrpcHostEnv"</c> collection で直列化する (harness の契約)。
/// </remarks>
[Collection("GrpcHostEnv")]
public sealed class CursorServiceTests
{
    private static CursorStateSnapshot SampleState() =>
        new(X: 0.5f, Y: 0.25f, WindowWidth: 1920, WindowHeight: 1080);

    [Fact]
    public async Task SetPosition_forwards_xy_to_bridge_and_round_trips_state()
    {
        var bridge = new CursorBridgeFake { NextState = SampleState() };
        await using var harness = await GrpcHostHarness.StartAsync(cursorBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Cursor.CursorClient(channel);

        var state = await client.SetPositionAsync(
            new CursorSetPositionRequest { X = 0.5f, Y = 0.25f }
        );

        var call = Assert.Single(bridge.Calls);
        Assert.Equal("SetPosition", call.Method);
        Assert.Equal(0.5f, call.X);
        Assert.Equal(0.25f, call.Y);

        Assert.Equal(0.5f, state.X);
        Assert.Equal(0.25f, state.Y);
        Assert.Equal(1920, state.WindowWidth);
        Assert.Equal(1080, state.WindowHeight);
    }

    [Fact]
    public async Task GetPosition_round_trips_state_without_xy()
    {
        var bridge = new CursorBridgeFake { NextState = SampleState() };
        await using var harness = await GrpcHostHarness.StartAsync(cursorBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Cursor.CursorClient(channel);

        var state = await client.GetPositionAsync(new CursorGetPositionRequest());

        var call = Assert.Single(bridge.Calls);
        Assert.Equal("GetPosition", call.Method);
        Assert.Null(call.X);
        Assert.Null(call.Y);

        Assert.Equal(0.5f, state.X);
        Assert.Equal(0.25f, state.Y);
        Assert.Equal(1920, state.WindowWidth);
        Assert.Equal(1080, state.WindowHeight);
    }

    [Theory]
    [InlineData(1.5f, 0.5f)]
    [InlineData(-0.1f, 0.5f)]
    [InlineData(0.5f, 2.0f)]
    [InlineData(0.5f, -0.5f)]
    [InlineData(float.NaN, 0.5f)]
    public async Task SetPosition_out_of_range_returns_InvalidArgument_without_calling_bridge(
        float x,
        float y
    )
    {
        // 仕様: 正規化 [0,1] 範囲外 / NaN は Service 層で InvalidArgument に弾かれ、
        // bridge には到達しない (engine 非依存の検証)。
        var bridge = new CursorBridgeFake { NextState = SampleState() };
        await using var harness = await GrpcHostHarness.StartAsync(cursorBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Cursor.CursorClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.SetPositionAsync(new CursorSetPositionRequest { X = x, Y = y })
        );
        Assert.Equal(StatusCode.InvalidArgument, ex.StatusCode);
        Assert.Empty(bridge.Calls);
    }

    [Fact]
    public async Task SetPosition_without_bridge_returns_Unavailable()
    {
        await using var harness = await GrpcHostHarness.StartAsync(cursorBridge: null);
        using var channel = harness.CreateChannel();
        var client = new V1.Cursor.CursorClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.SetPositionAsync(new CursorSetPositionRequest { X = 0.5f, Y = 0.5f })
        );
        Assert.Equal(StatusCode.Unavailable, ex.StatusCode);
    }

    [Fact]
    public async Task GetPosition_translates_CursorNotReadyException_to_FailedPrecondition()
    {
        var bridge = new CursorBridgeFake
        {
            ThrowOnNextCall = new CursorNotReadyException("window not ready"),
        };
        await using var harness = await GrpcHostHarness.StartAsync(cursorBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Cursor.CursorClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.GetPositionAsync(new CursorGetPositionRequest())
        );
        Assert.Equal(StatusCode.FailedPrecondition, ex.StatusCode);
        Assert.Contains("window not ready", ex.Status.Detail);
    }

    [Fact]
    public async Task SetPosition_translates_generic_exception_to_Internal()
    {
        var bridge = new CursorBridgeFake
        {
            ThrowOnNextCall = new InvalidOperationException("engine fault"),
        };
        await using var harness = await GrpcHostHarness.StartAsync(cursorBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Cursor.CursorClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.SetPositionAsync(new CursorSetPositionRequest { X = 0.5f, Y = 0.5f })
        );
        Assert.Equal(StatusCode.Internal, ex.StatusCode);
    }
}
