using Grpc.Core;
using ResoniteIO.Core.Dash;
using ResoniteIO.Core.Tests.Common;
using ResoniteIO.Core.Tests.Common.Fakes;
using ResoniteIO.V1;
using Xunit;

namespace ResoniteIO.Core.Tests.Dash;

/// <summary>
/// <see cref="Core.Dash.DashService"/> の 7 RPC を実 Kestrel + UDS gRPC で end-to-end に
/// 流し、(1) request の各引数 (ref_id / GetTree フィルタ / scroll delta) が Bridge へ
/// 正しく届くこと、(2) Bridge が返した snapshot が proto message に round-trip すること、
/// (3) 例外 → gRPC Status の翻訳を検証する integration-real テスト。
/// </summary>
/// <remarks>
/// <see cref="SessionHostHarness"/> は <c>RESONITE_IO_SOCKET</c> env var を読み書きするため
/// <c>"SessionHostEnv"</c> collection で直列化する (harness の契約)。
/// </remarks>
[Collection("SessionHostEnv")]
public sealed class DashServiceTests
{
    // ----- Open -----

    [Fact]
    public async Task Open_invokes_bridge_and_round_trips_state()
    {
        var bridge = new DashBridgeFake
        {
            NextState = new DashStateSnapshot(IsOpen: true, OpenLerp: 0.42f),
        };
        await using var harness = await SessionHostHarness.StartAsync(dashBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Dash.DashClient(channel);

        var state = await client.OpenAsync(new DashOpenRequest());

        var call = Assert.Single(bridge.Calls);
        Assert.Equal("Open", call.Method);
        Assert.True(state.IsOpen);
        Assert.Equal(0.42f, state.OpenLerp);
    }

    // ----- Close -----

    [Fact]
    public async Task Close_invokes_bridge_and_round_trips_state()
    {
        var bridge = new DashBridgeFake
        {
            NextState = new DashStateSnapshot(IsOpen: false, OpenLerp: 0.0f),
        };
        await using var harness = await SessionHostHarness.StartAsync(dashBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Dash.DashClient(channel);

        var state = await client.CloseAsync(new DashCloseRequest());

        var call = Assert.Single(bridge.Calls);
        Assert.Equal("Close", call.Method);
        Assert.False(state.IsOpen);
        Assert.Equal(0.0f, state.OpenLerp);
    }

    // ----- GetState -----

    [Fact]
    public async Task GetState_invokes_bridge_and_round_trips_state()
    {
        var bridge = new DashBridgeFake
        {
            NextState = new DashStateSnapshot(IsOpen: true, OpenLerp: 1.0f),
        };
        await using var harness = await SessionHostHarness.StartAsync(dashBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Dash.DashClient(channel);

        var state = await client.GetStateAsync(new DashGetStateRequest());

        var call = Assert.Single(bridge.Calls);
        Assert.Equal("GetState", call.Method);
        Assert.True(state.IsOpen);
        Assert.Equal(1.0f, state.OpenLerp);
    }

    // ----- GetTree: request フィルタの forward -----

    [Fact]
    public async Task GetTree_forwards_interactable_only_and_root_ref_id_to_bridge()
    {
        var bridge = new DashBridgeFake();
        await using var harness = await SessionHostHarness.StartAsync(dashBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Dash.DashClient(channel);

        await client.GetTreeAsync(
            new DashGetTreeRequest { InteractableOnly = true, RootRefId = "slot-1" }
        );

        var call = Assert.Single(bridge.Calls);
        Assert.Equal("GetTree", call.Method);
        Assert.True(call.InteractableOnly);
        Assert.Equal("slot-1", call.RootRefId);
    }

    // ----- GetTree: snapshot の full round-trip -----

    [Fact]
    public async Task GetTree_round_trips_all_element_and_rect_fields()
    {
        // 2 要素 (各フィールド + nested Rect の全フィールドが互いに異なる値) を入れ、
        // 全フィールドの round-trip と要素順序の保存を検証する。
        var element0 = new DashElementSnapshot(
            RefId: "ref-0",
            Type: "Button",
            SlotName: "PlayButton",
            LocaleKey: "Settings.Audio",
            Label: "Play",
            Enabled: true,
            Interactable: true,
            Rect: new DashRectSnapshot(
                X: 1.5f,
                Y: 2.5f,
                Width: 3.5f,
                Height: 4.5f,
                IsScreenSpace: true
            ),
            ParentRefId: "",
            Depth: 0
        );
        var element1 = new DashElementSnapshot(
            RefId: "ref-1",
            Type: "ScrollRect",
            SlotName: "List",
            LocaleKey: "Settings.Graphics",
            Label: "Graphics",
            Enabled: false,
            Interactable: false,
            Rect: new DashRectSnapshot(
                X: 10.0f,
                Y: 20.0f,
                Width: 30.0f,
                Height: 40.0f,
                IsScreenSpace: false
            ),
            ParentRefId: "ref-0",
            Depth: 1
        );
        var bridge = new DashBridgeFake
        {
            NextTree = new DashTreeSnapshot(
                Elements: new[] { element0, element1 },
                ScreenWidth: 1920,
                ScreenHeight: 1080
            ),
        };
        await using var harness = await SessionHostHarness.StartAsync(dashBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Dash.DashClient(channel);

        var tree = await client.GetTreeAsync(new DashGetTreeRequest());

        Assert.Equal(1920, tree.ScreenWidth);
        Assert.Equal(1080, tree.ScreenHeight);
        Assert.Equal(2, tree.Elements.Count);
        AssertElementRoundTrips(element0, tree.Elements[0]);
        AssertElementRoundTrips(element1, tree.Elements[1]);
    }

    private static void AssertElementRoundTrips(DashElementSnapshot expected, DashElement actual)
    {
        Assert.Equal(expected.RefId, actual.RefId);
        Assert.Equal(expected.Type, actual.Type);
        Assert.Equal(expected.SlotName, actual.SlotName);
        Assert.Equal(expected.LocaleKey, actual.LocaleKey);
        Assert.Equal(expected.Label, actual.Label);
        Assert.Equal(expected.Enabled, actual.Enabled);
        Assert.Equal(expected.Interactable, actual.Interactable);
        Assert.Equal(expected.ParentRefId, actual.ParentRefId);
        Assert.Equal(expected.Depth, actual.Depth);

        Assert.Equal(expected.Rect.X, actual.Rect.X);
        Assert.Equal(expected.Rect.Y, actual.Rect.Y);
        Assert.Equal(expected.Rect.Width, actual.Rect.Width);
        Assert.Equal(expected.Rect.Height, actual.Rect.Height);
        Assert.Equal(expected.Rect.IsScreenSpace, actual.Rect.IsScreenSpace);
    }

    // ----- Invoke -----

    [Fact]
    public async Task Invoke_forwards_ref_id_and_round_trips_action_result()
    {
        var bridge = new DashBridgeFake
        {
            NextResult = new DashActionResultSnapshot(
                Ok: true,
                Found: true,
                RefId: "ref-7",
                Detail: "pressed"
            ),
        };
        await using var harness = await SessionHostHarness.StartAsync(dashBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Dash.DashClient(channel);

        var result = await client.InvokeAsync(new DashInvokeRequest { RefId = "ref-7" });

        var call = Assert.Single(bridge.Calls);
        Assert.Equal("Invoke", call.Method);
        Assert.Equal("ref-7", call.RefId);
        AssertActionResultRoundTrips(bridge.NextResult, result);
    }

    // ----- Highlight -----

    [Fact]
    public async Task Highlight_forwards_ref_id_and_round_trips_action_result()
    {
        var bridge = new DashBridgeFake
        {
            NextResult = new DashActionResultSnapshot(
                Ok: true,
                Found: true,
                RefId: "ref-3",
                Detail: "hovered"
            ),
        };
        await using var harness = await SessionHostHarness.StartAsync(dashBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Dash.DashClient(channel);

        var result = await client.HighlightAsync(new DashHighlightRequest { RefId = "ref-3" });

        var call = Assert.Single(bridge.Calls);
        Assert.Equal("Highlight", call.Method);
        Assert.Equal("ref-3", call.RefId);
        AssertActionResultRoundTrips(bridge.NextResult, result);
    }

    // ----- Scroll -----

    [Fact]
    public async Task Scroll_forwards_ref_id_and_deltas_and_round_trips_action_result()
    {
        var bridge = new DashBridgeFake
        {
            NextResult = new DashActionResultSnapshot(
                Ok: false,
                Found: true,
                RefId: "ref-9",
                Detail: "not scrollable"
            ),
        };
        await using var harness = await SessionHostHarness.StartAsync(dashBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Dash.DashClient(channel);

        var result = await client.ScrollAsync(
            new DashScrollRequest
            {
                RefId = "ref-9",
                DeltaX = -1.25f,
                DeltaY = 3.75f,
            }
        );

        var call = Assert.Single(bridge.Calls);
        Assert.Equal("Scroll", call.Method);
        Assert.Equal("ref-9", call.RefId);
        Assert.Equal(-1.25f, call.DeltaX);
        Assert.Equal(3.75f, call.DeltaY);
        AssertActionResultRoundTrips(bridge.NextResult, result);
    }

    private static void AssertActionResultRoundTrips(
        DashActionResultSnapshot expected,
        DashActionResult actual
    )
    {
        Assert.Equal(expected.Ok, actual.Ok);
        Assert.Equal(expected.Found, actual.Found);
        Assert.Equal(expected.RefId, actual.RefId);
        Assert.Equal(expected.Detail, actual.Detail);
    }

    // ----- 例外 → gRPC Status の翻訳 -----

    [Fact]
    public async Task Open_without_bridge_returns_Unavailable()
    {
        // dashBridge=null で起動 → Service は mount されるが bridge 未注入なので
        // 各 RPC は Status.Unavailable を返す (Service 契約)。
        await using var harness = await SessionHostHarness.StartAsync(dashBridge: null);
        using var channel = harness.CreateChannel();
        var client = new V1.Dash.DashClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.OpenAsync(new DashOpenRequest())
        );
        Assert.Equal(StatusCode.Unavailable, ex.StatusCode);
    }

    [Fact]
    public async Task Open_translates_DashNotReadyException_to_FailedPrecondition()
    {
        var bridge = new DashBridgeFake
        {
            ThrowOnNextCall = new DashNotReadyException("dash not ready"),
        };
        await using var harness = await SessionHostHarness.StartAsync(dashBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Dash.DashClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.OpenAsync(new DashOpenRequest())
        );
        Assert.Equal(StatusCode.FailedPrecondition, ex.StatusCode);
        // メッセージは仕様上 propagate される (substring 検証に留める)。
        Assert.Contains("dash not ready", ex.Status.Detail);
    }

    [Fact]
    public async Task Invoke_translates_ArgumentException_to_InvalidArgument()
    {
        var bridge = new DashBridgeFake
        {
            ThrowOnNextCall = new ArgumentException("ref_id must not be empty"),
        };
        await using var harness = await SessionHostHarness.StartAsync(dashBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Dash.DashClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.InvokeAsync(new DashInvokeRequest { RefId = "" })
        );
        Assert.Equal(StatusCode.InvalidArgument, ex.StatusCode);
    }

    [Fact]
    public async Task Scroll_translates_ArgumentOutOfRangeException_to_InvalidArgument()
    {
        // ArgumentOutOfRangeException は ArgumentException のサブクラス。仕様上
        // ArgumentException 系はすべて InvalidArgument に翻訳される。
        var bridge = new DashBridgeFake
        {
            ThrowOnNextCall = new ArgumentOutOfRangeException("deltaY"),
        };
        await using var harness = await SessionHostHarness.StartAsync(dashBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Dash.DashClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.ScrollAsync(new DashScrollRequest { RefId = "ref-1" })
        );
        Assert.Equal(StatusCode.InvalidArgument, ex.StatusCode);
    }

    [Fact]
    public async Task Highlight_translates_generic_exception_to_Internal()
    {
        var bridge = new DashBridgeFake
        {
            ThrowOnNextCall = new InvalidOperationException("engine fault"),
        };
        await using var harness = await SessionHostHarness.StartAsync(dashBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Dash.DashClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.HighlightAsync(new DashHighlightRequest { RefId = "ref-1" })
        );
        Assert.Equal(StatusCode.Internal, ex.StatusCode);
    }
}
