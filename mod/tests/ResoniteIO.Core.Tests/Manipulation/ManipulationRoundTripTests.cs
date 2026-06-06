using Grpc.Core;
using ResoniteIO.Core.Manipulation;
using ResoniteIO.Core.Tests.Common;
using ResoniteIO.Core.Tests.Common.Fakes;
using ResoniteIO.V1;
using Xunit;

namespace ResoniteIO.Core.Tests.Manipulation;

/// <summary>
/// <see cref="Core.Manipulation.ManipulationService"/> の 3 RPC (Grab / Release / GetState) を
/// 実 Kestrel + UDS gRPC で end-to-end に流す integration-real テスト。検証対象は
/// <c>proto/resonite_io/v1/manipulation.proto</c> と <see cref="IManipulationBridge"/> の契約:
/// (1) proto request の hand / point / radius が Core selector / POCO へ正しく map されて Bridge に届くこと、
/// (2) Bridge が返した <see cref="GrabOutcome"/> / <see cref="GrabSnapshot"/> が proto state に round-trip すること、
/// (3) radius default 解決 (&lt;=0 → 0.1m) が Core 層で行われ Bridge へ渡ること、
/// (4) 例外 / 未注入 → gRPC Status の翻訳。
/// </summary>
/// <remarks>
/// <see cref="SessionHostHarness"/> は <c>RESONITE_IO_SOCKET</c> env var を読み書きするため
/// <c>"SessionHostEnv"</c> collection で直列化する (harness の契約)。
/// field の取り違えを検出するため、各 RPC で hand / point / radius / object_names に
/// 互いに異なる識別可能な値を使う。
/// </remarks>
[Collection("SessionHostEnv")]
public sealed class ManipulationRoundTripTests
{
    private const float DefaultRadius = 0.1f;

    // ----- Grab: 正常系 (explicit point + radius) -----

    [Fact]
    public async Task Grab_with_explicit_point_and_radius_forwards_exact_values_and_round_trips_state()
    {
        // request LEFT / point (1,2,3) / radius 0.25 を Bridge がそのまま受け取り、
        // 成功した state (IsHolding=true / hand=LEFT / unix_nanos>0) が round-trip すること。
        var bridge = new FakeManipulationBridge
        {
            GrabSucceeds = true,
            GrabbedObjectNames = new[] { "Cube" },
        };
        await using var harness = await SessionHostHarness.StartAsync(manipulationBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Manipulation.ManipulationClient(channel);

        var result = await client.GrabAsync(
            new ManipulationGrabRequest
            {
                Hand = ManipulationHand.Left,
                Point = new WorldPoint
                {
                    X = 1f,
                    Y = 2f,
                    Z = 3f,
                },
                Radius = 0.25f,
            }
        );

        var call = Assert.Single(bridge.Calls);
        Assert.Equal("Grab", call.Method);
        Assert.Equal(ManipulationHandSelector.Left, call.Hand);
        Assert.Equal(new ManipulationPoint(1f, 2f, 3f), call.Point);
        Assert.Equal(0.25f, call.Radius);

        Assert.True(result.Grabbed);
        Assert.True(result.State.IsHolding);
        Assert.Equal(ManipulationHand.Left, result.State.Hand);
        Assert.Equal(new[] { "Cube" }, result.State.ObjectNames);
        Assert.True(result.State.UnixNanos > 0);
    }

    // ----- Grab: point 未設定 → null -----

    [Fact]
    public async Task Grab_without_point_forwards_null_point_to_bridge()
    {
        // proto WorldPoint 不在 → Bridge は null point を受け取る (= 手の現在位置を使う契約)。
        var bridge = new FakeManipulationBridge();
        await using var harness = await SessionHostHarness.StartAsync(manipulationBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Manipulation.ManipulationClient(channel);

        await client.GrabAsync(
            new ManipulationGrabRequest { Hand = ManipulationHand.Right, Radius = 0.3f }
        );

        var call = Assert.Single(bridge.Calls);
        Assert.Null(call.Point);
        Assert.Equal(ManipulationHandSelector.Right, call.Hand);
    }

    // ----- Grab: radius <=0 → default 0.1m に解決 -----

    [Fact]
    public async Task Grab_with_zero_radius_resolves_to_server_default()
    {
        // 仕様: radius <=0 のとき Service が 0.1m に解決してから Bridge へ渡す。
        var bridge = new FakeManipulationBridge();
        await using var harness = await SessionHostHarness.StartAsync(manipulationBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Manipulation.ManipulationClient(channel);

        await client.GrabAsync(
            new ManipulationGrabRequest { Hand = ManipulationHand.Primary, Radius = 0f }
        );

        var call = Assert.Single(bridge.Calls);
        Assert.Equal(DefaultRadius, call.Radius);
    }

    [Fact]
    public async Task Grab_with_negative_radius_resolves_to_server_default()
    {
        // 仕様: 負の radius も <=0 として 0.1m に解決される。
        var bridge = new FakeManipulationBridge();
        await using var harness = await SessionHostHarness.StartAsync(manipulationBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Manipulation.ManipulationClient(channel);

        await client.GrabAsync(
            new ManipulationGrabRequest { Hand = ManipulationHand.Primary, Radius = -1f }
        );

        var call = Assert.Single(bridge.Calls);
        Assert.Equal(DefaultRadius, call.Radius);
    }

    [Fact]
    public async Task Grab_with_positive_radius_passes_through_unchanged()
    {
        // 仕様: 正の radius はそのまま Bridge へ渡る (default に置き換わらない)。
        var bridge = new FakeManipulationBridge();
        await using var harness = await SessionHostHarness.StartAsync(manipulationBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Manipulation.ManipulationClient(channel);

        await client.GrabAsync(
            new ManipulationGrabRequest { Hand = ManipulationHand.Primary, Radius = 0.42f }
        );

        var call = Assert.Single(bridge.Calls);
        Assert.Equal(0.42f, call.Radius);
    }

    // ----- Grab: 掴めない → Grabbed=false だがエラーにしない -----

    [Fact]
    public async Task Grab_when_nothing_grabbable_returns_false_without_error()
    {
        // 仕様: 範囲に grabbable が無いとき Grabbed=false を返すだけでエラーにはしない。
        var bridge = new FakeManipulationBridge { GrabSucceeds = false };
        await using var harness = await SessionHostHarness.StartAsync(manipulationBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Manipulation.ManipulationClient(channel);

        var result = await client.GrabAsync(
            new ManipulationGrabRequest { Hand = ManipulationHand.Left, Radius = 0.1f }
        );

        Assert.False(result.Grabbed);
        Assert.False(result.State.IsHolding);
        Assert.Empty(result.State.ObjectNames);
        Assert.True(result.State.UnixNanos > 0);
    }

    // ----- Release: 保持解除 -----

    [Fact]
    public async Task Release_calls_bridge_for_hand_and_returns_not_holding_state()
    {
        // Grab で掴んだ後 Release すると、同じ手で ReleaseAsync が呼ばれ IsHolding=false に戻る。
        var bridge = new FakeManipulationBridge
        {
            GrabSucceeds = true,
            GrabbedObjectNames = new[] { "Held" },
        };
        await using var harness = await SessionHostHarness.StartAsync(manipulationBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Manipulation.ManipulationClient(channel);

        await client.GrabAsync(
            new ManipulationGrabRequest { Hand = ManipulationHand.Left, Radius = 0.1f }
        );
        var state = await client.ReleaseAsync(
            new ManipulationReleaseRequest { Hand = ManipulationHand.Left }
        );

        Assert.Equal(2, bridge.Calls.Count);
        var releaseCall = bridge.Calls[1];
        Assert.Equal("Release", releaseCall.Method);
        Assert.Equal(ManipulationHandSelector.Left, releaseCall.Hand);

        Assert.False(state.IsHolding);
        Assert.Equal(ManipulationHand.Left, state.Hand);
        Assert.Empty(state.ObjectNames);
        Assert.True(state.UnixNanos > 0);
    }

    // ----- GetState: 現在の保持状態を読む (object_names round-trip) -----

    [Fact]
    public async Task GetState_returns_current_snapshot_with_multiple_object_names()
    {
        // 仕様: GetState は操作せず現在の保持状態を返す。複数 distinct な object_names が
        // 順序込みで round-trip すること。
        var bridge = new FakeManipulationBridge();
        bridge.SeedHeld(ManipulationHandSelector.Right, new[] { "Alpha", "Beta", "Gamma" });
        await using var harness = await SessionHostHarness.StartAsync(manipulationBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Manipulation.ManipulationClient(channel);

        var state = await client.GetStateAsync(
            new ManipulationGetStateRequest { Hand = ManipulationHand.Right }
        );

        var call = Assert.Single(bridge.Calls);
        Assert.Equal("GetState", call.Method);
        Assert.Equal(ManipulationHandSelector.Right, call.Hand);

        Assert.True(state.IsHolding);
        Assert.Equal(ManipulationHand.Right, state.Hand);
        Assert.Equal(new[] { "Alpha", "Beta", "Gamma" }, state.ObjectNames);
        Assert.True(state.UnixNanos > 0);
    }

    // ----- hand 列挙の map (proto enum → Core selector → proto enum) -----

    [Theory]
    [InlineData(ManipulationHand.Unspecified, ManipulationHandSelector.Primary)]
    [InlineData(ManipulationHand.Primary, ManipulationHandSelector.Primary)]
    [InlineData(ManipulationHand.Left, ManipulationHandSelector.Left)]
    [InlineData(ManipulationHand.Right, ManipulationHandSelector.Right)]
    public async Task GetState_maps_proto_hand_to_core_selector(
        ManipulationHand protoHand,
        ManipulationHandSelector expected
    )
    {
        // 仕様: UNSPECIFIED(0) / PRIMARY(1) → Primary、LEFT(2) → Left、RIGHT(3) → Right。
        var bridge = new FakeManipulationBridge();
        await using var harness = await SessionHostHarness.StartAsync(manipulationBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Manipulation.ManipulationClient(channel);

        await client.GetStateAsync(new ManipulationGetStateRequest { Hand = protoHand });

        var call = Assert.Single(bridge.Calls);
        Assert.Equal(expected, call.Hand);
    }

    [Theory]
    [InlineData(ManipulationHandSelector.Primary, ManipulationHand.Primary)]
    [InlineData(ManipulationHandSelector.Left, ManipulationHand.Left)]
    [InlineData(ManipulationHandSelector.Right, ManipulationHand.Right)]
    public async Task GetState_maps_core_selector_to_proto_hand_on_returned_state(
        ManipulationHandSelector snapshotHand,
        ManipulationHand expectedProtoHand
    )
    {
        // 仕様: 返却 state の hand は解決後の selector を proto enum へ map (Unspecified にはならない)。
        // Bridge が返す snapshot の Hand をそのまま返す経路を検証するため、対応する手を seed する。
        var bridge = new FakeManipulationBridge();
        bridge.SeedHeld(snapshotHand, new[] { "X" });
        var requestHand = snapshotHand switch
        {
            ManipulationHandSelector.Left => ManipulationHand.Left,
            ManipulationHandSelector.Right => ManipulationHand.Right,
            _ => ManipulationHand.Primary,
        };
        await using var harness = await SessionHostHarness.StartAsync(manipulationBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Manipulation.ManipulationClient(channel);

        var state = await client.GetStateAsync(
            new ManipulationGetStateRequest { Hand = requestHand }
        );

        Assert.Equal(expectedProtoHand, state.Hand);
    }

    // ----- 例外 / 未注入 → gRPC Status の翻訳 -----

    [Fact]
    public async Task Grab_without_bridge_returns_Unavailable()
    {
        // manipulationBridge=null で起動 → Service は mount されるが bridge 未注入なので
        // 各 RPC は Status.Unavailable を返す (Service 契約)。
        await using var harness = await SessionHostHarness.StartAsync(manipulationBridge: null);
        using var channel = harness.CreateChannel();
        var client = new V1.Manipulation.ManipulationClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.GrabAsync(new ManipulationGrabRequest())
        );
        Assert.Equal(StatusCode.Unavailable, ex.StatusCode);
    }

    [Fact]
    public async Task Grab_translates_ManipulationNotReadyException_to_FailedPrecondition()
    {
        var bridge = new FakeManipulationBridge
        {
            ThrowOnNextCall = new ManipulationNotReadyException("local user not ready"),
        };
        await using var harness = await SessionHostHarness.StartAsync(manipulationBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Manipulation.ManipulationClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.GrabAsync(new ManipulationGrabRequest())
        );
        Assert.Equal(StatusCode.FailedPrecondition, ex.StatusCode);
        // メッセージは仕様上 propagate される (substring 検証に留める)。
        Assert.Contains("local user not ready", ex.Status.Detail);
    }

    [Fact]
    public async Task Release_translates_ManipulationNotReadyException_to_FailedPrecondition()
    {
        var bridge = new FakeManipulationBridge
        {
            ThrowOnNextCall = new ManipulationNotReadyException("handler not ready"),
        };
        await using var harness = await SessionHostHarness.StartAsync(manipulationBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Manipulation.ManipulationClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.ReleaseAsync(new ManipulationReleaseRequest())
        );
        Assert.Equal(StatusCode.FailedPrecondition, ex.StatusCode);
    }
}
