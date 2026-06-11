using Grpc.Core;
using ResoniteIO.Core.Cursor;
using ResoniteIO.Core.Tests.Common;
using ResoniteIO.Core.Tests.Common.Fakes;
using ResoniteIO.V1;
using Xunit;

namespace ResoniteIO.Core.Tests.Cursor;

/// <summary>
/// <see cref="Core.Cursor.CursorService"/> の 3 RPC (SetPosition / GetPosition / Release)
/// を実 Kestrel + UDS gRPC で end-to-end に流し、(1) x/y が Bridge に届くこと、
/// (2) Bridge が返した snapshot (保持状態 <c>held</c> を含む) が
/// <see cref="CursorState"/> に round-trip すること、(3) 正規化範囲チェック
/// (Service 層) と例外 → gRPC Status の翻訳を検証する integration-real テスト。
/// </summary>
/// <remarks>
/// <see cref="GrpcHostHarness"/> は <c>RESONITE_IO_SOCKET</c> env var を読み書きするため
/// <c>"GrpcHostEnv"</c> collection で直列化する (harness の契約)。
/// 保持の実体 (cursor lock / Harmony 偽装) は FrooxEngine 側の責務であり、
/// ここでは Service ↔ Bridge IF の契約のみを検証する (実機検証は e2e)。
/// </remarks>
[Collection("GrpcHostEnv")]
public sealed class CursorServiceTests
{
    private static CursorStateSnapshot SampleState(bool held) =>
        new(X: 0.5f, Y: 0.25f, WindowWidth: 1920, WindowHeight: 1080, Held: held);

    [Fact]
    public async Task SetPosition_forwards_xy_to_bridge_and_round_trips_held_state()
    {
        // 仕様: SetPosition は保持を確立し、反映後の状態 (held=true) を返す。
        var bridge = new CursorBridgeFake { NextState = SampleState(held: true) };
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
        Assert.True(state.Held);
    }

    [Fact]
    public async Task GetPosition_round_trips_held_state_without_xy()
    {
        // 仕様: GetPosition は副作用なしで現在の位置・解像度・保持状態を返す。
        // 保持中の bridge を模して held=true が wire を透過することを観測する。
        var bridge = new CursorBridgeFake { NextState = SampleState(held: true) };
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
        Assert.True(state.Held);
    }

    [Fact]
    public async Task GetPosition_reports_held_false_when_not_holding()
    {
        // 仕様: 未保持 (Release 後 / world focus 切替後を含む) は held=false。
        var bridge = new CursorBridgeFake { NextState = SampleState(held: false) };
        await using var harness = await GrpcHostHarness.StartAsync(cursorBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Cursor.CursorClient(channel);

        var state = await client.GetPositionAsync(new CursorGetPositionRequest());

        Assert.False(state.Held);
    }

    [Fact]
    public async Task Release_forwards_to_bridge_and_round_trips_unheld_state()
    {
        // 仕様: Release は保持を解除し、解除後の状態 (held=false) を返す。
        var bridge = new CursorBridgeFake { NextState = SampleState(held: false) };
        await using var harness = await GrpcHostHarness.StartAsync(cursorBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Cursor.CursorClient(channel);

        var state = await client.ReleaseAsync(new CursorReleaseRequest());

        var call = Assert.Single(bridge.Calls);
        Assert.Equal("Release", call.Method);
        Assert.Null(call.X);
        Assert.Null(call.Y);

        Assert.Equal(0.5f, state.X);
        Assert.Equal(0.25f, state.Y);
        Assert.Equal(1920, state.WindowWidth);
        Assert.Equal(1080, state.WindowHeight);
        Assert.False(state.Held);
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
        var bridge = new CursorBridgeFake { NextState = SampleState(held: false) };
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
    public async Task Release_without_bridge_returns_Unavailable()
    {
        await using var harness = await GrpcHostHarness.StartAsync(cursorBridge: null);
        using var channel = harness.CreateChannel();
        var client = new V1.Cursor.CursorClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.ReleaseAsync(new CursorReleaseRequest())
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
    public async Task Release_translates_CursorNotReadyException_to_FailedPrecondition()
    {
        // 仕様: 保持機構が利用不能 (focused world なし / engine internals 変化) の
        // Release は CursorNotReadyException → FailedPrecondition に翻訳される。
        var bridge = new CursorBridgeFake
        {
            ThrowOnNextCall = new CursorNotReadyException("cursor hold unavailable"),
        };
        await using var harness = await GrpcHostHarness.StartAsync(cursorBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Cursor.CursorClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.ReleaseAsync(new CursorReleaseRequest())
        );
        Assert.Equal(StatusCode.FailedPrecondition, ex.StatusCode);
        Assert.Contains("cursor hold unavailable", ex.Status.Detail);
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
