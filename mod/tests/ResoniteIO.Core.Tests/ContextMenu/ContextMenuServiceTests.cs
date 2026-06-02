using Grpc.Core;
using ResoniteIO.Core.ContextMenu;
using ResoniteIO.Core.Tests.Common;
using ResoniteIO.Core.Tests.Common.Fakes;
using ResoniteIO.V1;
using Xunit;

namespace ResoniteIO.Core.Tests.ContextMenu;

/// <summary>
/// <see cref="Core.ContextMenu.ContextMenuService"/> の 5 RPC を実 Kestrel + UDS gRPC
/// で end-to-end に流し、(1) hand / index が Core selector へ正しく map されて Bridge に届くこと、
/// (2) Bridge が返した snapshot が <see cref="ContextMenuState"/> に round-trip すること、
/// (3) 例外 → gRPC Status の翻訳を検証する integration-real テスト。
/// </summary>
/// <remarks>
/// <see cref="SessionHostHarness"/> は <c>RESONITE_IO_SOCKET</c> env var を読み書きするため
/// <c>"SessionHostEnv"</c> collection で直列化する (harness の契約)。
/// </remarks>
[Collection("SessionHostEnv")]
public sealed class ContextMenuServiceTests
{
    /// <summary>2 項目 + ハイライト中の state を返す Bridge を立て、各 RPC が全 field を
    /// round-trip することを確認するための共通 snapshot。</summary>
    private static ContextMenuStateSnapshot SampleState() =>
        new(
            IsOpen: true,
            Items: new[]
            {
                new ContextMenuItemSnapshot(
                    Index: 0,
                    Label: "Move",
                    Enabled: true,
                    HasIcon: true,
                    ColorR: 0.1f,
                    ColorG: 0.2f,
                    ColorB: 0.3f,
                    ColorA: 1.0f
                ),
                new ContextMenuItemSnapshot(
                    Index: 1,
                    Label: "Undo",
                    Enabled: false,
                    HasIcon: false,
                    ColorR: 0.4f,
                    ColorG: 0.5f,
                    ColorB: 0.6f,
                    ColorA: 0.7f
                ),
            },
            HighlightedIndex: 1
        );

    private static void AssertRoundTrips(ContextMenuStateSnapshot expected, ContextMenuState actual)
    {
        Assert.Equal(expected.IsOpen, actual.IsOpen);
        Assert.Equal(expected.HighlightedIndex, actual.HighlightedIndex);
        Assert.Equal(expected.Items.Count, actual.Items.Count);

        for (var i = 0; i < expected.Items.Count; i++)
        {
            var e = expected.Items[i];
            var a = actual.Items[i];
            Assert.Equal(e.Index, a.Index);
            Assert.Equal(e.Label, a.Label);
            Assert.Equal(e.Enabled, a.Enabled);
            Assert.Equal(e.HasIcon, a.HasIcon);
            Assert.Equal(e.ColorR, a.ColorR);
            Assert.Equal(e.ColorG, a.ColorG);
            Assert.Equal(e.ColorB, a.ColorB);
            Assert.Equal(e.ColorA, a.ColorA);
        }
    }

    // ----- Open -----

    [Fact]
    public async Task Open_forwards_hand_to_bridge_and_round_trips_state()
    {
        var bridge = new ContextMenuBridgeFake { NextState = SampleState() };
        await using var harness = await SessionHostHarness.StartAsync(contextMenuBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.ContextMenu.ContextMenuClient(channel);

        var state = await client.OpenAsync(
            new ContextMenuOpenRequest { Hand = ContextMenuHand.Left }
        );

        var call = Assert.Single(bridge.Calls);
        Assert.Equal("Open", call.Method);
        Assert.Equal(ContextMenuHandSelector.Left, call.Hand);
        Assert.Null(call.Index);
        AssertRoundTrips(SampleState(), state);
    }

    // ----- Close -----

    [Fact]
    public async Task Close_forwards_hand_to_bridge_and_round_trips_state()
    {
        var closedState = new ContextMenuStateSnapshot(
            IsOpen: false,
            Items: Array.Empty<ContextMenuItemSnapshot>(),
            HighlightedIndex: -1
        );
        var bridge = new ContextMenuBridgeFake { NextState = closedState };
        await using var harness = await SessionHostHarness.StartAsync(contextMenuBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.ContextMenu.ContextMenuClient(channel);

        var state = await client.CloseAsync(
            new ContextMenuCloseRequest { Hand = ContextMenuHand.Right }
        );

        var call = Assert.Single(bridge.Calls);
        Assert.Equal("Close", call.Method);
        Assert.Equal(ContextMenuHandSelector.Right, call.Hand);
        Assert.Null(call.Index);
        Assert.False(state.IsOpen);
        Assert.Empty(state.Items);
        Assert.Equal(-1, state.HighlightedIndex);
    }

    // ----- GetState -----

    [Fact]
    public async Task GetState_forwards_hand_to_bridge_and_round_trips_state()
    {
        var bridge = new ContextMenuBridgeFake { NextState = SampleState() };
        await using var harness = await SessionHostHarness.StartAsync(contextMenuBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.ContextMenu.ContextMenuClient(channel);

        var state = await client.GetStateAsync(
            new ContextMenuGetStateRequest { Hand = ContextMenuHand.Primary }
        );

        var call = Assert.Single(bridge.Calls);
        Assert.Equal("GetState", call.Method);
        Assert.Equal(ContextMenuHandSelector.Primary, call.Hand);
        Assert.Null(call.Index);
        AssertRoundTrips(SampleState(), state);
    }

    // ----- Highlight -----

    [Fact]
    public async Task Highlight_forwards_hand_and_index_to_bridge_and_round_trips_state()
    {
        var bridge = new ContextMenuBridgeFake { NextState = SampleState() };
        await using var harness = await SessionHostHarness.StartAsync(contextMenuBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.ContextMenu.ContextMenuClient(channel);

        var state = await client.HighlightAsync(
            new ContextMenuHighlightRequest { Hand = ContextMenuHand.Left, Index = 1 }
        );

        var call = Assert.Single(bridge.Calls);
        Assert.Equal("Highlight", call.Method);
        Assert.Equal(ContextMenuHandSelector.Left, call.Hand);
        Assert.Equal(1, call.Index);
        AssertRoundTrips(SampleState(), state);
    }

    // ----- Invoke -----

    [Fact]
    public async Task Invoke_forwards_hand_and_index_to_bridge_and_round_trips_state()
    {
        var bridge = new ContextMenuBridgeFake { NextState = SampleState() };
        await using var harness = await SessionHostHarness.StartAsync(contextMenuBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.ContextMenu.ContextMenuClient(channel);

        var state = await client.InvokeAsync(
            new ContextMenuInvokeRequest { Hand = ContextMenuHand.Right, Index = 0 }
        );

        var call = Assert.Single(bridge.Calls);
        Assert.Equal("Invoke", call.Method);
        Assert.Equal(ContextMenuHandSelector.Right, call.Hand);
        Assert.Equal(0, call.Index);
        AssertRoundTrips(SampleState(), state);
    }

    // ----- hand 列挙の map (proto enum → Core selector) -----

    [Theory]
    [InlineData(ContextMenuHand.Unspecified, ContextMenuHandSelector.Primary)]
    [InlineData(ContextMenuHand.Primary, ContextMenuHandSelector.Primary)]
    [InlineData(ContextMenuHand.Left, ContextMenuHandSelector.Left)]
    [InlineData(ContextMenuHand.Right, ContextMenuHandSelector.Right)]
    public async Task GetState_maps_proto_hand_to_core_selector(
        ContextMenuHand protoHand,
        ContextMenuHandSelector expected
    )
    {
        // 仕様: UNSPECIFIED(0) / PRIMARY(1) → Primary、LEFT(2) → Left、RIGHT(3) → Right。
        var bridge = new ContextMenuBridgeFake();
        await using var harness = await SessionHostHarness.StartAsync(contextMenuBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.ContextMenu.ContextMenuClient(channel);

        await client.GetStateAsync(new ContextMenuGetStateRequest { Hand = protoHand });

        var call = Assert.Single(bridge.Calls);
        Assert.Equal(expected, call.Hand);
    }

    // ----- 例外 → gRPC Status の翻訳 -----

    [Fact]
    public async Task Open_without_bridge_returns_Unavailable()
    {
        // contextMenuBridge=null で起動 → Service は mount されるが bridge 未注入なので
        // 各 RPC は Status.Unavailable を返す (Service 契約)。
        await using var harness = await SessionHostHarness.StartAsync(contextMenuBridge: null);
        using var channel = harness.CreateChannel();
        var client = new V1.ContextMenu.ContextMenuClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.OpenAsync(new ContextMenuOpenRequest())
        );
        Assert.Equal(StatusCode.Unavailable, ex.StatusCode);
    }

    [Fact]
    public async Task Open_translates_ContextMenuNotReadyException_to_FailedPrecondition()
    {
        var bridge = new ContextMenuBridgeFake
        {
            ThrowOnNextCall = new ContextMenuNotReadyException("local user not ready"),
        };
        await using var harness = await SessionHostHarness.StartAsync(contextMenuBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.ContextMenu.ContextMenuClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.OpenAsync(new ContextMenuOpenRequest())
        );
        Assert.Equal(StatusCode.FailedPrecondition, ex.StatusCode);
        // メッセージは仕様上 propagate される (substring 検証に留める)。
        Assert.Contains("local user not ready", ex.Status.Detail);
    }

    [Fact]
    public async Task Highlight_translates_ArgumentOutOfRangeException_to_InvalidArgument()
    {
        var bridge = new ContextMenuBridgeFake
        {
            ThrowOnNextCall = new ArgumentOutOfRangeException("index"),
        };
        await using var harness = await SessionHostHarness.StartAsync(contextMenuBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.ContextMenu.ContextMenuClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.HighlightAsync(new ContextMenuHighlightRequest { Index = 99 })
        );
        Assert.Equal(StatusCode.InvalidArgument, ex.StatusCode);
    }

    [Fact]
    public async Task Invoke_translates_generic_exception_to_Internal()
    {
        var bridge = new ContextMenuBridgeFake
        {
            ThrowOnNextCall = new InvalidOperationException("engine fault"),
        };
        await using var harness = await SessionHostHarness.StartAsync(contextMenuBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.ContextMenu.ContextMenuClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.InvokeAsync(new ContextMenuInvokeRequest { Index = 0 })
        );
        Assert.Equal(StatusCode.Internal, ex.StatusCode);
    }
}
