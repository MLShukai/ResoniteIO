using Grpc.Core;
using ResoniteIO.Core.Dash;
using ResoniteIO.Core.Tests.Common;
using ResoniteIO.Core.Tests.Common.Fakes;
using ResoniteIO.V1;
using Xunit;

namespace ResoniteIO.Core.Tests.Dash;

/// <summary>
/// <see cref="Core.Dash.DashService"/> の 9 RPC (Open / Close / GetState / ListTabs /
/// SetTab / ListControls / Invoke / Scroll / Highlight) を実 Kestrel + UDS gRPC で
/// end-to-end に流し、(1) request の各引数 (ref_id / locale_key / include_disabled /
/// scroll delta) が Bridge へ正しく届くこと、(2) Bridge が返した snapshot が proto
/// message に full-field round-trip すること、(3) 例外 → gRPC Status の翻訳、
/// (4) bridge 未注入時の Unavailable を検証する integration-real テスト。
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

    // ----- ListTabs: snapshot の full round-trip -----

    [Fact]
    public async Task ListTabs_round_trips_all_tab_fields_and_preserves_order()
    {
        // 2 tab (全 6 フィールドが互いに異なる値、bool は両極、locale_key は set/empty
        // 両方) を入れ、全フィールドの round-trip と列挙順序の保存を検証する。
        var tab0 = new DashTabSnapshot(
            RefId: "tab-ref-0",
            LocaleKey: "Dash.Screens.Worlds",
            Name: "Worlds",
            Label: "ワールド",
            IsCurrent: true,
            Enabled: true
        );
        var tab1 = new DashTabSnapshot(
            RefId: "tab-ref-1",
            LocaleKey: "",
            Name: "Contacts",
            Label: "Contacts",
            IsCurrent: false,
            Enabled: false
        );
        var bridge = new DashBridgeFake
        {
            NextTabList = new DashTabListSnapshot(new[] { tab0, tab1 }),
        };
        await using var harness = await GrpcHostHarness.StartAsync(dashBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Dash.DashClient(channel);

        var list = await client.ListTabsAsync(new DashListTabsRequest());

        var call = Assert.Single(bridge.Calls);
        Assert.Equal("ListTabs", call.Method);
        Assert.Equal(2, list.Tabs.Count);
        AssertTabRoundTrips(tab0, list.Tabs[0]);
        AssertTabRoundTrips(tab1, list.Tabs[1]);
    }

    [Fact]
    public async Task ListTabs_with_empty_list_round_trips_to_no_tabs()
    {
        // 空 tab リスト (理論上のエッジ) はエラーにせず空 repeated として round-trip する。
        var bridge = new DashBridgeFake
        {
            NextTabList = new DashTabListSnapshot(Array.Empty<DashTabSnapshot>()),
        };
        await using var harness = await GrpcHostHarness.StartAsync(dashBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Dash.DashClient(channel);

        var list = await client.ListTabsAsync(new DashListTabsRequest());

        Assert.Equal("ListTabs", Assert.Single(bridge.Calls).Method);
        Assert.Empty(list.Tabs);
    }

    // ----- SetTab -----

    [Fact]
    public async Task SetTab_forwards_ref_id_and_locale_key_to_bridge_and_round_trips_result()
    {
        // ref_id と locale_key の両方が bridge にそのまま届くこと。Service は
        // 片方が空でももう一方が非空なら bridge を呼ぶ (両空のみ短絡)。
        var bridge = new DashBridgeFake
        {
            NextResult = new DashActionResultSnapshot(
                Ok: true,
                Found: true,
                RefId: "tab-ref-resolved",
                Detail: ""
            ),
        };
        await using var harness = await GrpcHostHarness.StartAsync(dashBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Dash.DashClient(channel);

        var result = await client.SetTabAsync(
            new DashSetTabRequest { RefId = "tab-ref-5", LocaleKey = "Dash.Screens.Settings" }
        );

        var call = Assert.Single(bridge.Calls);
        Assert.Equal("SetTab", call.Method);
        Assert.Equal("tab-ref-5", call.RefId);
        Assert.Equal("Dash.Screens.Settings", call.LocaleKey);
        AssertActionResultRoundTrips(bridge.NextResult, result);
    }

    [Fact]
    public async Task SetTab_with_only_locale_key_forwards_empty_ref_id_to_bridge()
    {
        // ref_id 空 + locale_key 非空 は有効な指定。Service は短絡せず bridge を呼び、
        // 空 ref_id をそのまま渡す (locale_key fallback の解決は bridge の責務)。
        var bridge = new DashBridgeFake();
        await using var harness = await GrpcHostHarness.StartAsync(dashBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Dash.DashClient(channel);

        await client.SetTabAsync(
            new DashSetTabRequest { RefId = "", LocaleKey = "Dash.Screens.Home" }
        );

        var call = Assert.Single(bridge.Calls);
        Assert.Equal("SetTab", call.Method);
        Assert.Equal("", call.RefId);
        Assert.Equal("Dash.Screens.Home", call.LocaleKey);
    }

    [Fact]
    public async Task SetTab_round_trips_soft_fail_not_found_result()
    {
        // 未解決 tab は例外でなく found=false / ok=false の soft-fail で返る。
        // Service は bridge の戻りをそのまま round-trip する (解決は bridge の責務)。
        var bridge = new DashBridgeFake
        {
            NextResult = new DashActionResultSnapshot(
                Ok: false,
                Found: false,
                RefId: "",
                Detail: "tab not found"
            ),
        };
        await using var harness = await GrpcHostHarness.StartAsync(dashBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Dash.DashClient(channel);

        var result = await client.SetTabAsync(new DashSetTabRequest { RefId = "missing" });

        Assert.False(result.Ok);
        Assert.False(result.Found);
        Assert.Equal("", result.RefId);
        Assert.Equal("tab not found", result.Detail);
    }

    // ----- SetTab: 両空検査 (Service 層で短絡) -----

    [Fact]
    public async Task SetTab_with_both_ref_id_and_locale_key_empty_returns_InvalidArgument()
    {
        // ref_id / locale_key 両空はクライアントの引数ミス。Service 層で弾かれ、
        // bridge を呼ばずに InvalidArgument を返す (ArgumentException → InvalidArgument)。
        var bridge = new DashBridgeFake();
        await using var harness = await GrpcHostHarness.StartAsync(dashBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Dash.DashClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.SetTabAsync(new DashSetTabRequest { RefId = "", LocaleKey = "" })
        );

        Assert.Equal(StatusCode.InvalidArgument, ex.StatusCode);
        // 両空は bridge へ到達しない (Service 層で短絡される)。
        Assert.Empty(bridge.Calls);
    }

    // ----- ListControls: request 引数の forward + snapshot の full round-trip -----

    [Fact]
    public async Task ListControls_forwards_include_disabled_true_to_bridge()
    {
        var bridge = new DashBridgeFake();
        await using var harness = await GrpcHostHarness.StartAsync(dashBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Dash.DashClient(channel);

        await client.ListControlsAsync(new DashListControlsRequest { IncludeDisabled = true });

        var call = Assert.Single(bridge.Calls);
        Assert.Equal("ListControls", call.Method);
        Assert.True(call.IncludeDisabled);
    }

    [Fact]
    public async Task ListControls_forwards_include_disabled_false_to_bridge()
    {
        // default(false) も明示的に bridge へ届くこと (true との対で forward を確かめる)。
        var bridge = new DashBridgeFake();
        await using var harness = await GrpcHostHarness.StartAsync(dashBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Dash.DashClient(channel);

        await client.ListControlsAsync(new DashListControlsRequest { IncludeDisabled = false });

        var call = Assert.Single(bridge.Calls);
        Assert.Equal("ListControls", call.Method);
        Assert.False(call.IncludeDisabled);
    }

    [Fact]
    public async Task ListControls_round_trips_button_and_scroll_control_fields()
    {
        // button row (locale_key set, depth 0, parent 空) と scroll row (locale_key empty,
        // depth 1, parent set, disabled) の 2 種を入れ、全 7 フィールドの round-trip と
        // 列挙順序の保存を検証する。control_type が "button" / "scroll" に正規化済みで
        // 来ること、locale_key の set/empty、parent_ref_id/depth、enabled を確認。
        var button = new DashControlSnapshot(
            RefId: "ctl-button-0",
            ControlType: "button",
            Label: "Play",
            LocaleKey: "Dash.Action.Play",
            Enabled: true,
            ParentRefId: "",
            Depth: 0
        );
        var scroll = new DashControlSnapshot(
            RefId: "ctl-scroll-1",
            ControlType: "scroll",
            Label: "",
            LocaleKey: "",
            Enabled: false,
            ParentRefId: "ctl-button-0",
            Depth: 1
        );
        var bridge = new DashBridgeFake
        {
            NextControlList = new DashControlListSnapshot(new[] { button, scroll }),
        };
        await using var harness = await GrpcHostHarness.StartAsync(dashBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Dash.DashClient(channel);

        var list = await client.ListControlsAsync(new DashListControlsRequest());

        var call = Assert.Single(bridge.Calls);
        Assert.Equal("ListControls", call.Method);
        Assert.Equal(2, list.Controls.Count);
        AssertControlRoundTrips(button, list.Controls[0]);
        AssertControlRoundTrips(scroll, list.Controls[1]);
    }

    [Fact]
    public async Task ListControls_with_empty_list_round_trips_to_no_controls()
    {
        // 空 / 未解決 tab は soft で空リストを返す (bridge 契約)。Service は空 repeated に変換。
        var bridge = new DashBridgeFake
        {
            NextControlList = new DashControlListSnapshot(Array.Empty<DashControlSnapshot>()),
        };
        await using var harness = await GrpcHostHarness.StartAsync(dashBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Dash.DashClient(channel);

        var list = await client.ListControlsAsync(new DashListControlsRequest());

        Assert.Equal("ListControls", Assert.Single(bridge.Calls).Method);
        Assert.Empty(list.Controls);
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
                RefId: "ctl-7",
                Detail: "pressed"
            ),
        };
        await using var harness = await GrpcHostHarness.StartAsync(dashBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Dash.DashClient(channel);

        var result = await client.InvokeAsync(new DashInvokeRequest { RefId = "ctl-7" });

        var call = Assert.Single(bridge.Calls);
        Assert.Equal("Invoke", call.Method);
        Assert.Equal("ctl-7", call.RefId);
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
                RefId: "ctl-9",
                Detail: "not scrollable"
            ),
        };
        await using var harness = await GrpcHostHarness.StartAsync(dashBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Dash.DashClient(channel);

        var result = await client.ScrollAsync(
            new DashScrollRequest
            {
                RefId = "ctl-9",
                DeltaX = -1.25f,
                DeltaY = 3.75f,
            }
        );

        var call = Assert.Single(bridge.Calls);
        Assert.Equal("Scroll", call.Method);
        Assert.Equal("ctl-9", call.RefId);
        Assert.Equal(-1.25f, call.DeltaX);
        Assert.Equal(3.75f, call.DeltaY);
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
                RefId: "ctl-3",
                Detail: "hovered"
            ),
        };
        await using var harness = await GrpcHostHarness.StartAsync(dashBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Dash.DashClient(channel);

        var result = await client.HighlightAsync(new DashHighlightRequest { RefId = "ctl-3" });

        var call = Assert.Single(bridge.Calls);
        Assert.Equal("Highlight", call.Method);
        Assert.Equal("ctl-3", call.RefId);
        AssertActionResultRoundTrips(bridge.NextResult, result);
    }

    // ----- 例外 → gRPC Status の翻訳 (read RPC と action RPC を両方カバー) -----

    [Fact]
    public async Task ListTabs_translates_DashNotReadyException_to_FailedPrecondition()
    {
        var bridge = new DashBridgeFake
        {
            ThrowOnNextCall = new DashNotReadyException("dash not ready"),
        };
        await using var harness = await GrpcHostHarness.StartAsync(dashBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Dash.DashClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.ListTabsAsync(new DashListTabsRequest())
        );
        Assert.Equal(StatusCode.FailedPrecondition, ex.StatusCode);
        // メッセージは仕様上 propagate される (substring 検証に留める)。
        Assert.Contains("dash not ready", ex.Status.Detail);
    }

    [Fact]
    public async Task Invoke_translates_DashNotReadyException_to_FailedPrecondition()
    {
        var bridge = new DashBridgeFake
        {
            ThrowOnNextCall = new DashNotReadyException("dash not ready"),
        };
        await using var harness = await GrpcHostHarness.StartAsync(dashBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Dash.DashClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.InvokeAsync(new DashInvokeRequest { RefId = "ctl-1" })
        );
        Assert.Equal(StatusCode.FailedPrecondition, ex.StatusCode);
    }

    [Fact]
    public async Task ListControls_translates_ArgumentException_to_InvalidArgument()
    {
        var bridge = new DashBridgeFake { ThrowOnNextCall = new ArgumentException("bad argument") };
        await using var harness = await GrpcHostHarness.StartAsync(dashBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Dash.DashClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.ListControlsAsync(new DashListControlsRequest())
        );
        Assert.Equal(StatusCode.InvalidArgument, ex.StatusCode);
    }

    [Fact]
    public async Task Scroll_translates_ArgumentException_to_InvalidArgument()
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
            await client.ScrollAsync(new DashScrollRequest { RefId = "ctl-1" })
        );
        Assert.Equal(StatusCode.InvalidArgument, ex.StatusCode);
    }

    [Fact]
    public async Task GetState_translates_generic_exception_to_Internal()
    {
        var bridge = new DashBridgeFake
        {
            ThrowOnNextCall = new InvalidOperationException("engine fault"),
        };
        await using var harness = await GrpcHostHarness.StartAsync(dashBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Dash.DashClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.GetStateAsync(new DashGetStateRequest())
        );
        Assert.Equal(StatusCode.Internal, ex.StatusCode);
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
            await client.HighlightAsync(new DashHighlightRequest { RefId = "ctl-1" })
        );
        Assert.Equal(StatusCode.Internal, ex.StatusCode);
    }

    // ----- bridge 未注入時の Unavailable (代表 RPC を網羅) -----

    [Fact]
    public async Task GetState_without_bridge_returns_Unavailable()
    {
        await using var harness = await GrpcHostHarness.StartAsync(dashBridge: null);
        using var channel = harness.CreateChannel();
        var client = new V1.Dash.DashClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.GetStateAsync(new DashGetStateRequest())
        );
        Assert.Equal(StatusCode.Unavailable, ex.StatusCode);
    }

    [Fact]
    public async Task ListTabs_without_bridge_returns_Unavailable()
    {
        await using var harness = await GrpcHostHarness.StartAsync(dashBridge: null);
        using var channel = harness.CreateChannel();
        var client = new V1.Dash.DashClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.ListTabsAsync(new DashListTabsRequest())
        );
        Assert.Equal(StatusCode.Unavailable, ex.StatusCode);
    }

    [Fact]
    public async Task ListControls_without_bridge_returns_Unavailable()
    {
        await using var harness = await GrpcHostHarness.StartAsync(dashBridge: null);
        using var channel = harness.CreateChannel();
        var client = new V1.Dash.DashClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.ListControlsAsync(new DashListControlsRequest())
        );
        Assert.Equal(StatusCode.Unavailable, ex.StatusCode);
    }

    [Fact]
    public async Task Invoke_without_bridge_returns_Unavailable()
    {
        await using var harness = await GrpcHostHarness.StartAsync(dashBridge: null);
        using var channel = harness.CreateChannel();
        var client = new V1.Dash.DashClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.InvokeAsync(new DashInvokeRequest { RefId = "ctl-1" })
        );
        Assert.Equal(StatusCode.Unavailable, ex.StatusCode);
    }

    [Fact]
    public async Task SetTab_without_bridge_returns_Unavailable()
    {
        // 両空検査より先に bridge 未注入の Unavailable guard が効くことを確かめるため、
        // 有効な selector (locale_key 非空) を渡す。
        await using var harness = await GrpcHostHarness.StartAsync(dashBridge: null);
        using var channel = harness.CreateChannel();
        var client = new V1.Dash.DashClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.SetTabAsync(new DashSetTabRequest { LocaleKey = "Dash.Screens.Home" })
        );
        Assert.Equal(StatusCode.Unavailable, ex.StatusCode);
    }

    // ----- round-trip assertion helpers -----

    private static void AssertTabRoundTrips(DashTabSnapshot expected, DashTab actual)
    {
        Assert.Equal(expected.RefId, actual.RefId);
        Assert.Equal(expected.LocaleKey, actual.LocaleKey);
        Assert.Equal(expected.Name, actual.Name);
        Assert.Equal(expected.Label, actual.Label);
        Assert.Equal(expected.IsCurrent, actual.IsCurrent);
        Assert.Equal(expected.Enabled, actual.Enabled);
    }

    private static void AssertControlRoundTrips(DashControlSnapshot expected, DashControl actual)
    {
        Assert.Equal(expected.RefId, actual.RefId);
        Assert.Equal(expected.ControlType, actual.ControlType);
        Assert.Equal(expected.Label, actual.Label);
        Assert.Equal(expected.LocaleKey, actual.LocaleKey);
        Assert.Equal(expected.Enabled, actual.Enabled);
        Assert.Equal(expected.ParentRefId, actual.ParentRefId);
        Assert.Equal(expected.Depth, actual.Depth);
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
}
