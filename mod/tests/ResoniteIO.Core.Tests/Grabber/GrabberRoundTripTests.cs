using Grpc.Core;
using ResoniteIO.Core.Grabber;
using ResoniteIO.Core.Tests.Common;
using ResoniteIO.Core.Tests.Common.Fakes;
using ResoniteIO.V1;
using Xunit;

namespace ResoniteIO.Core.Tests.Grabber;

/// <summary>
/// <see cref="Core.Grabber.GrabberService"/> の 3 RPC (Grab / Release / GetState) を
/// 実 Kestrel + UDS gRPC で end-to-end に流す integration-real テスト。検証対象は
/// <c>proto/resonite_io/v1/grabber.proto</c> と <see cref="IGrabberBridge"/> の契約:
/// (1) proto request の hand / radius が Core selector / float へ正しく map されて Bridge に届くこと
/// (Grab は常にデスクトップカーソルレイの hit 点中心の proximity grab で、point 指定は存在しない)、
/// (2) Bridge が返した <see cref="GrabOutcome"/> / <see cref="GrabSnapshot"/> が proto state に round-trip すること、
/// (3) radius default 解決 (&lt;=0 → 0.1m) が Core 層で行われ Bridge へ渡ること、
/// (4) 例外 / 未注入 → gRPC Status の翻訳 (VR モード拒否 = NotReady → FailedPrecondition を含む)。
/// レイ計算 / raycast 自体は engine 表面のためここでは検証しない (実機 e2e / manual で担保)。
/// </summary>
/// <remarks>
/// <see cref="GrpcHostHarness"/> は <c>RESONITE_IO_SOCKET</c> env var を読み書きするため
/// <c>"GrpcHostEnv"</c> collection で直列化する (harness の契約)。
/// field の取り違えを検出するため、各 RPC で hand / radius / object_names に
/// 互いに異なる識別可能な値を使う。
/// </remarks>
[Collection("GrpcHostEnv")]
public sealed class GrabberRoundTripTests
{
    private const float DefaultRadius = 0.1f;

    // ----- Grab: 正常系 (hand + radius round-trip) -----

    [Fact]
    public async Task Grab_forwards_hand_and_radius_and_round_trips_state()
    {
        // 仕様: Grab は hand + radius のみを運ぶ (カーソルレイの hit 点が grab 中心になるため
        // point 指定は存在しない)。request LEFT / radius 0.25 を Bridge がそのまま受け取り、
        // 成功した state (Grabbed=true / IsHolding=true / hand=LEFT / unix_nanos>0) が round-trip すること。
        var bridge = new FakeGrabberBridge
        {
            GrabSucceeds = true,
            GrabbedObjectNames = new[] { "Cube" },
        };
        await using var harness = await GrpcHostHarness.StartAsync(grabberBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Grabber.GrabberClient(channel);

        var result = await client.GrabAsync(
            new GrabberGrabRequest { Hand = GrabberHand.Left, Radius = 0.25f }
        );

        var call = Assert.Single(bridge.Calls);
        Assert.Equal("Grab", call.Method);
        Assert.Equal(GrabberHandSelector.Left, call.Hand);
        Assert.Equal(0.25f, call.Radius);

        Assert.True(result.Grabbed);
        Assert.True(result.State.IsHolding);
        Assert.Equal(GrabberHand.Left, result.State.Hand);
        Assert.Equal(new[] { "Cube" }, result.State.ObjectNames);
        Assert.True(result.State.UnixNanos > 0);
    }

    // ----- Grab: radius <=0 → default 0.1m に解決 -----

    [Fact]
    public async Task Grab_with_zero_radius_resolves_to_server_default()
    {
        // 仕様: radius <=0 のとき Service が 0.1m に解決してから Bridge へ渡す。
        var bridge = new FakeGrabberBridge();
        await using var harness = await GrpcHostHarness.StartAsync(grabberBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Grabber.GrabberClient(channel);

        await client.GrabAsync(new GrabberGrabRequest { Hand = GrabberHand.Primary, Radius = 0f });

        var call = Assert.Single(bridge.Calls);
        Assert.Equal(DefaultRadius, call.Radius);
    }

    [Fact]
    public async Task Grab_with_negative_radius_resolves_to_server_default()
    {
        // 仕様: 負の radius も <=0 として 0.1m に解決される。
        var bridge = new FakeGrabberBridge();
        await using var harness = await GrpcHostHarness.StartAsync(grabberBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Grabber.GrabberClient(channel);

        await client.GrabAsync(new GrabberGrabRequest { Hand = GrabberHand.Primary, Radius = -1f });

        var call = Assert.Single(bridge.Calls);
        Assert.Equal(DefaultRadius, call.Radius);
    }

    [Fact]
    public async Task Grab_with_positive_radius_passes_through_unchanged()
    {
        // 仕様: 正の radius はそのまま Bridge へ渡る (default に置き換わらない)。
        var bridge = new FakeGrabberBridge();
        await using var harness = await GrpcHostHarness.StartAsync(grabberBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Grabber.GrabberClient(channel);

        await client.GrabAsync(
            new GrabberGrabRequest { Hand = GrabberHand.Primary, Radius = 0.42f }
        );

        var call = Assert.Single(bridge.Calls);
        Assert.Equal(0.42f, call.Radius);
    }

    // ----- Grab: レイ miss / 範囲に grabbable 無し → OK + grabbed=false (エラーにしない) -----

    [Fact]
    public async Task Grab_when_nothing_grabbable_returns_false_without_error()
    {
        // 仕様: カーソルレイが何にも当たらない (miss)、または hit 点の radius 内に
        // grabbable が無いとき、Grabbed=false を返すだけでエラーにはしない (gRPC status は OK)。
        var bridge = new FakeGrabberBridge { GrabSucceeds = false };
        await using var harness = await GrpcHostHarness.StartAsync(grabberBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Grabber.GrabberClient(channel);

        var result = await client.GrabAsync(
            new GrabberGrabRequest { Hand = GrabberHand.Left, Radius = 0.1f }
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
        var bridge = new FakeGrabberBridge
        {
            GrabSucceeds = true,
            GrabbedObjectNames = new[] { "Held" },
        };
        await using var harness = await GrpcHostHarness.StartAsync(grabberBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Grabber.GrabberClient(channel);

        await client.GrabAsync(new GrabberGrabRequest { Hand = GrabberHand.Left, Radius = 0.1f });
        var state = await client.ReleaseAsync(
            new GrabberReleaseRequest { Hand = GrabberHand.Left }
        );

        Assert.Equal(2, bridge.Calls.Count);
        var releaseCall = bridge.Calls[1];
        Assert.Equal("Release", releaseCall.Method);
        Assert.Equal(GrabberHandSelector.Left, releaseCall.Hand);

        Assert.False(state.IsHolding);
        Assert.Equal(GrabberHand.Left, state.Hand);
        Assert.Empty(state.ObjectNames);
        Assert.True(state.UnixNanos > 0);
    }

    // ----- GetState: 現在の保持状態を読む (object_names round-trip) -----

    [Fact]
    public async Task GetState_returns_current_snapshot_with_multiple_object_names()
    {
        // 仕様: GetState は操作せず現在の保持状態を返す。複数 distinct な object_names が
        // 順序込みで round-trip すること。
        var bridge = new FakeGrabberBridge();
        bridge.SeedHeld(GrabberHandSelector.Right, new[] { "Alpha", "Beta", "Gamma" });
        await using var harness = await GrpcHostHarness.StartAsync(grabberBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Grabber.GrabberClient(channel);

        var state = await client.GetStateAsync(
            new GrabberGetStateRequest { Hand = GrabberHand.Right }
        );

        var call = Assert.Single(bridge.Calls);
        Assert.Equal("GetState", call.Method);
        Assert.Equal(GrabberHandSelector.Right, call.Hand);

        Assert.True(state.IsHolding);
        Assert.Equal(GrabberHand.Right, state.Hand);
        Assert.Equal(new[] { "Alpha", "Beta", "Gamma" }, state.ObjectNames);
        Assert.True(state.UnixNanos > 0);
    }

    // ----- hand 列挙の map (proto enum → Core selector → proto enum) -----

    [Theory]
    [InlineData(GrabberHand.Unspecified, GrabberHandSelector.Primary)]
    [InlineData(GrabberHand.Primary, GrabberHandSelector.Primary)]
    [InlineData(GrabberHand.Left, GrabberHandSelector.Left)]
    [InlineData(GrabberHand.Right, GrabberHandSelector.Right)]
    public async Task GetState_maps_proto_hand_to_core_selector(
        GrabberHand protoHand,
        GrabberHandSelector expected
    )
    {
        // 仕様: UNSPECIFIED(0) / PRIMARY(1) → Primary、LEFT(2) → Left、RIGHT(3) → Right。
        var bridge = new FakeGrabberBridge();
        await using var harness = await GrpcHostHarness.StartAsync(grabberBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Grabber.GrabberClient(channel);

        await client.GetStateAsync(new GrabberGetStateRequest { Hand = protoHand });

        var call = Assert.Single(bridge.Calls);
        Assert.Equal(expected, call.Hand);
    }

    [Theory]
    [InlineData(GrabberHandSelector.Primary, GrabberHand.Primary)]
    [InlineData(GrabberHandSelector.Left, GrabberHand.Left)]
    [InlineData(GrabberHandSelector.Right, GrabberHand.Right)]
    public async Task GetState_maps_core_selector_to_proto_hand_on_returned_state(
        GrabberHandSelector snapshotHand,
        GrabberHand expectedProtoHand
    )
    {
        // 仕様: 返却 state の hand は解決後の selector を proto enum へ map (Unspecified にはならない)。
        // Bridge が返す snapshot の Hand をそのまま返す経路を検証するため、対応する手を seed する。
        var bridge = new FakeGrabberBridge();
        bridge.SeedHeld(snapshotHand, new[] { "X" });
        var requestHand = snapshotHand switch
        {
            GrabberHandSelector.Left => GrabberHand.Left,
            GrabberHandSelector.Right => GrabberHand.Right,
            _ => GrabberHand.Primary,
        };
        await using var harness = await GrpcHostHarness.StartAsync(grabberBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Grabber.GrabberClient(channel);

        var state = await client.GetStateAsync(new GrabberGetStateRequest { Hand = requestHand });

        Assert.Equal(expectedProtoHand, state.Hand);
    }

    // ----- 例外 / 未注入 → gRPC Status の翻訳 -----

    [Fact]
    public async Task Grab_without_bridge_returns_Unavailable()
    {
        // grabberBridge=null で起動 → Service は mount されるが bridge 未注入なので
        // 各 RPC は Status.Unavailable を返す (Service 契約)。
        await using var harness = await GrpcHostHarness.StartAsync(grabberBridge: null);
        using var channel = harness.CreateChannel();
        var client = new V1.Grabber.GrabberClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.GrabAsync(new GrabberGrabRequest())
        );
        Assert.Equal(StatusCode.Unavailable, ex.StatusCode);
    }

    [Fact]
    public async Task Grab_in_vr_mode_returns_FailedPrecondition_mentioning_desktop()
    {
        // 仕様: VR モード (screen 非 active) では Bridge が
        // GrabberNotReadyException("Grab requires desktop (screen) mode; VR is active.")
        // を投げ、Service が FailedPrecondition に翻訳する (新規例外型は追加しない契約)。
        // message は完全一致ではなく substring "desktop" のみ pin する。
        var bridge = new FakeGrabberBridge
        {
            ThrowOnNextCall = new GrabberNotReadyException(
                "Grab requires desktop (screen) mode; VR is active."
            ),
        };
        await using var harness = await GrpcHostHarness.StartAsync(grabberBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Grabber.GrabberClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.GrabAsync(new GrabberGrabRequest())
        );
        Assert.Equal(StatusCode.FailedPrecondition, ex.StatusCode);
        Assert.Contains("desktop", ex.Status.Detail);
    }

    [Fact]
    public async Task Grab_translates_GrabberNotReadyException_to_FailedPrecondition()
    {
        var bridge = new FakeGrabberBridge
        {
            ThrowOnNextCall = new GrabberNotReadyException("local user not ready"),
        };
        await using var harness = await GrpcHostHarness.StartAsync(grabberBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Grabber.GrabberClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.GrabAsync(new GrabberGrabRequest())
        );
        Assert.Equal(StatusCode.FailedPrecondition, ex.StatusCode);
        // メッセージは仕様上 propagate される (substring 検証に留める)。
        Assert.Contains("local user not ready", ex.Status.Detail);
    }

    [Fact]
    public async Task Release_translates_GrabberNotReadyException_to_FailedPrecondition()
    {
        var bridge = new FakeGrabberBridge
        {
            ThrowOnNextCall = new GrabberNotReadyException("handler not ready"),
        };
        await using var harness = await GrpcHostHarness.StartAsync(grabberBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Grabber.GrabberClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.ReleaseAsync(new GrabberReleaseRequest())
        );
        Assert.Equal(StatusCode.FailedPrecondition, ex.StatusCode);
    }
}
