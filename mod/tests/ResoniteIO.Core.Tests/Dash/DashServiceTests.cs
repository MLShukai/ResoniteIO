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
/// <see cref="GrpcHostHarness"/> は <c>RESONITE_IO_SOCKET</c> env var を読み書きするため
/// <c>"GrpcHostEnv"</c> collection で直列化する (harness の契約)。
/// </remarks>
[Collection("GrpcHostEnv")]
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
        await using var harness = await GrpcHostHarness.StartAsync(dashBridge: bridge);
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
        await using var harness = await GrpcHostHarness.StartAsync(dashBridge: bridge);
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
        await using var harness = await GrpcHostHarness.StartAsync(dashBridge: bridge);
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
        await using var harness = await GrpcHostHarness.StartAsync(dashBridge: bridge);
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
        await using var harness = await GrpcHostHarness.StartAsync(dashBridge: bridge);
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
        await using var harness = await GrpcHostHarness.StartAsync(dashBridge: bridge);
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
        await using var harness = await GrpcHostHarness.StartAsync(dashBridge: bridge);
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
        await using var harness = await GrpcHostHarness.StartAsync(dashBridge: bridge);
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
        await using var harness = await GrpcHostHarness.StartAsync(dashBridge: null);
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
        await using var harness = await GrpcHostHarness.StartAsync(dashBridge: bridge);
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
        await using var harness = await GrpcHostHarness.StartAsync(dashBridge: bridge);
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
        await using var harness = await GrpcHostHarness.StartAsync(dashBridge: bridge);
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
        await using var harness = await GrpcHostHarness.StartAsync(dashBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Dash.DashClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.HighlightAsync(new DashHighlightRequest { RefId = "ref-1" })
        );
        Assert.Equal(StatusCode.Internal, ex.StatusCode);
    }

    // ----- ListScreens: snapshot の full round-trip -----

    [Fact]
    public async Task ListScreens_round_trips_all_screen_fields_and_preserves_order()
    {
        // 2 screen (全 6 フィールドが互いに異なる値、bool は両極) を入れ、全フィールドの
        // round-trip と列挙順序の保存を検証する (GetTree の element round-trip と同形)。
        var screen0 = new DashScreenSnapshot(
            RefId: "screen-ref-0",
            Key: "Dash.Screens.Worlds",
            Name: "Worlds",
            Label: "Worlds",
            IsCurrent: true,
            Enabled: true
        );
        var screen1 = new DashScreenSnapshot(
            RefId: "screen-ref-1",
            Key: "Dash.Screens.Contacts",
            Name: "Contacts",
            Label: "Contacts",
            IsCurrent: false,
            Enabled: false
        );
        var bridge = new DashBridgeFake
        {
            NextScreenList = new DashScreenListSnapshot(new[] { screen0, screen1 }),
        };
        await using var harness = await GrpcHostHarness.StartAsync(dashBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Dash.DashClient(channel);

        var list = await client.ListScreensAsync(new DashListScreensRequest());

        var call = Assert.Single(bridge.Calls);
        Assert.Equal("ListScreens", call.Method);
        Assert.Equal(2, list.Screens.Count);
        AssertScreenRoundTrips(screen0, list.Screens[0]);
        AssertScreenRoundTrips(screen1, list.Screens[1]);
    }

    [Fact]
    public async Task ListScreens_with_empty_list_round_trips_to_no_screens()
    {
        // 空 screen リスト (理論上のエッジ) はエラーにせず空 repeated として round-trip する。
        var bridge = new DashBridgeFake
        {
            NextScreenList = new DashScreenListSnapshot(Array.Empty<DashScreenSnapshot>()),
        };
        await using var harness = await GrpcHostHarness.StartAsync(dashBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Dash.DashClient(channel);

        var list = await client.ListScreensAsync(new DashListScreensRequest());

        Assert.Equal("ListScreens", Assert.Single(bridge.Calls).Method);
        Assert.Empty(list.Screens);
    }

    private static void AssertScreenRoundTrips(DashScreenSnapshot expected, DashScreen actual)
    {
        Assert.Equal(expected.RefId, actual.RefId);
        Assert.Equal(expected.Key, actual.Key);
        Assert.Equal(expected.Name, actual.Name);
        Assert.Equal(expected.Label, actual.Label);
        Assert.Equal(expected.IsCurrent, actual.IsCurrent);
        Assert.Equal(expected.Enabled, actual.Enabled);
    }

    // ----- SetScreen: request 引数の forward -----

    [Fact]
    public async Task SetScreen_forwards_ref_id_to_bridge_and_round_trips_action_result()
    {
        // ref_id 非空のとき bridge に ref_id (と key) がそのまま届く。
        var bridge = new DashBridgeFake
        {
            NextResult = new DashActionResultSnapshot(
                Ok: true,
                Found: true,
                RefId: "screen-ref-5",
                Detail: ""
            ),
        };
        await using var harness = await GrpcHostHarness.StartAsync(dashBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Dash.DashClient(channel);

        var result = await client.SetScreenAsync(
            new DashSetScreenRequest { RefId = "screen-ref-5", Key = "" }
        );

        var call = Assert.Single(bridge.Calls);
        Assert.Equal("SetScreen", call.Method);
        Assert.Equal("screen-ref-5", call.RefId);
        Assert.Equal("", call.Key);
        AssertActionResultRoundTrips(bridge.NextResult, result);
    }

    [Fact]
    public async Task SetScreen_forwards_key_to_bridge_and_round_trips_action_result()
    {
        // key だけ指定 (ref_id 空) のとき bridge に key がそのまま届く。
        var bridge = new DashBridgeFake
        {
            NextResult = new DashActionResultSnapshot(
                Ok: true,
                Found: true,
                RefId: "screen-ref-after",
                Detail: ""
            ),
        };
        await using var harness = await GrpcHostHarness.StartAsync(dashBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Dash.DashClient(channel);

        var result = await client.SetScreenAsync(
            new DashSetScreenRequest { RefId = "", Key = "Dash.Screens.Settings" }
        );

        var call = Assert.Single(bridge.Calls);
        Assert.Equal("SetScreen", call.Method);
        Assert.Equal("", call.RefId);
        Assert.Equal("Dash.Screens.Settings", call.Key);
        AssertActionResultRoundTrips(bridge.NextResult, result);
    }

    [Fact]
    public async Task SetScreen_round_trips_disabled_screen_detail()
    {
        // disabled screen への遷移は ok=true + detail="screen disabled" で返る (§5.2.4 / D2)。
        // Service は bridge の戻りをそのまま round-trip する (disabled 判定は bridge の責務)。
        var bridge = new DashBridgeFake
        {
            NextResult = new DashActionResultSnapshot(
                Ok: true,
                Found: true,
                RefId: "screen-ref-disabled",
                Detail: "screen disabled"
            ),
        };
        await using var harness = await GrpcHostHarness.StartAsync(dashBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Dash.DashClient(channel);

        var result = await client.SetScreenAsync(
            new DashSetScreenRequest { Key = "Dash.Screens.Contacts" }
        );

        Assert.True(result.Ok);
        Assert.True(result.Found);
        Assert.Equal("screen-ref-disabled", result.RefId);
        Assert.Equal("screen disabled", result.Detail);
    }

    // ----- SetScreen: 両空検査 (§4.4 / D1) -----

    [Fact]
    public async Task SetScreen_with_both_ref_id_and_key_empty_returns_InvalidArgument()
    {
        // ref_id / key 両空は Service 層で弾かれ、bridge を呼ばずに InvalidArgument を返す
        // (§4.4: 未指定はクライアントの引数ミス。`ArgumentException → InvalidArgument`)。
        var bridge = new DashBridgeFake();
        await using var harness = await GrpcHostHarness.StartAsync(dashBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Dash.DashClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.SetScreenAsync(new DashSetScreenRequest { RefId = "", Key = "" })
        );

        Assert.Equal(StatusCode.InvalidArgument, ex.StatusCode);
        // 両空は bridge へ到達しない (Service 層で短絡される)。
        Assert.Empty(bridge.Calls);
    }

    // ----- ListScreens / SetScreen: 例外翻訳が新 RPC でも成立すること -----

    [Fact]
    public async Task ListScreens_without_bridge_returns_Unavailable()
    {
        await using var harness = await GrpcHostHarness.StartAsync(dashBridge: null);
        using var channel = harness.CreateChannel();
        var client = new V1.Dash.DashClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.ListScreensAsync(new DashListScreensRequest())
        );
        Assert.Equal(StatusCode.Unavailable, ex.StatusCode);
    }

    [Fact]
    public async Task SetScreen_without_bridge_returns_Unavailable()
    {
        await using var harness = await GrpcHostHarness.StartAsync(dashBridge: null);
        using var channel = harness.CreateChannel();
        var client = new V1.Dash.DashClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.SetScreenAsync(new DashSetScreenRequest { Key = "Dash.Screens.Home" })
        );
        Assert.Equal(StatusCode.Unavailable, ex.StatusCode);
    }

    [Fact]
    public async Task ListScreens_translates_DashNotReadyException_to_FailedPrecondition()
    {
        var bridge = new DashBridgeFake
        {
            ThrowOnNextCall = new DashNotReadyException("dash not ready"),
        };
        await using var harness = await GrpcHostHarness.StartAsync(dashBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Dash.DashClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.ListScreensAsync(new DashListScreensRequest())
        );
        Assert.Equal(StatusCode.FailedPrecondition, ex.StatusCode);
    }

    [Fact]
    public async Task SetScreen_translates_DashNotReadyException_to_FailedPrecondition()
    {
        var bridge = new DashBridgeFake
        {
            ThrowOnNextCall = new DashNotReadyException("dash not ready"),
        };
        await using var harness = await GrpcHostHarness.StartAsync(dashBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Dash.DashClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.SetScreenAsync(new DashSetScreenRequest { Key = "Dash.Screens.Home" })
        );
        Assert.Equal(StatusCode.FailedPrecondition, ex.StatusCode);
    }
}
