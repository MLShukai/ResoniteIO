using Grpc.Core;
using ResoniteIO.Core.Logging;
using ResoniteIO.Core.Rpc;

namespace ResoniteIO.Core.Dash;

/// <summary><c>resonite_io.v1.Dash</c> サービスの Core 実装。</summary>
/// <remarks>
/// <see cref="IDashBridge"/> は optional DI: null なら <c>Unavailable</c> を返し、
/// Core 単体テストや dash 非対応 engine 構成も成立させる (ContextMenuService と同 pattern)。
/// 例外翻訳は <see cref="DashNotReadyException"/> → <c>FailedPrecondition</c>、
/// <see cref="ArgumentException"/> (不正引数) → <c>InvalidArgument</c>、その他 → <c>Internal</c>。
/// </remarks>
public sealed class DashService : V1.Dash.DashBase
{
    private readonly IDashBridge? _bridge;
    private readonly ILogSink _log;

    public DashService(ILogSink log, IDashBridge? bridge = null)
    {
        _log = log;
        _bridge = bridge;
    }

    public override Task<V1.DashState> Open(
        V1.DashOpenRequest request,
        ServerCallContext context
    ) => HandleAsync("Open", (bridge, ct) => bridge.OpenAsync(ct), MapToProto, context);

    public override Task<V1.DashState> Close(
        V1.DashCloseRequest request,
        ServerCallContext context
    ) => HandleAsync("Close", (bridge, ct) => bridge.CloseAsync(ct), MapToProto, context);

    public override Task<V1.DashState> GetState(
        V1.DashGetStateRequest request,
        ServerCallContext context
    ) => HandleAsync("GetState", (bridge, ct) => bridge.GetStateAsync(ct), MapToProto, context);

    public override Task<V1.DashTabList> ListTabs(
        V1.DashListTabsRequest request,
        ServerCallContext context
    ) => HandleAsync("ListTabs", (bridge, ct) => bridge.ListTabsAsync(ct), MapToProto, context);

    public override Task<V1.DashActionResult> SetTab(
        V1.DashSetTabRequest request,
        ServerCallContext context
    ) =>
        HandleAsync(
            "SetTab",
            (bridge, ct) =>
            {
                // ref_id / locale_key 両空はクライアントの引数ミス。bridge を起動せず
                // InvalidArgument に翻訳する (既存の ArgumentException → InvalidArgument 経路に乗せる)。
                if (string.IsNullOrEmpty(request.RefId) && string.IsNullOrEmpty(request.LocaleKey))
                {
                    throw new ArgumentException("ref_id or locale_key must be provided.");
                }

                return bridge.SetTabAsync(request.RefId, request.LocaleKey, ct);
            },
            MapToProto,
            context
        );

    public override Task<V1.DashControlList> ListControls(
        V1.DashListControlsRequest request,
        ServerCallContext context
    ) =>
        HandleAsync(
            "ListControls",
            (bridge, ct) => bridge.ListControlsAsync(request.IncludeDisabled, ct),
            MapToProto,
            context
        );

    public override Task<V1.DashActionResult> Invoke(
        V1.DashInvokeRequest request,
        ServerCallContext context
    ) =>
        HandleAsync(
            "Invoke",
            (bridge, ct) => bridge.InvokeAsync(request.RefId, ct),
            MapToProto,
            context
        );

    public override Task<V1.DashActionResult> Scroll(
        V1.DashScrollRequest request,
        ServerCallContext context
    ) =>
        HandleAsync(
            "Scroll",
            (bridge, ct) => bridge.ScrollAsync(request.RefId, request.DeltaX, request.DeltaY, ct),
            MapToProto,
            context
        );

    public override Task<V1.DashActionResult> Highlight(
        V1.DashHighlightRequest request,
        ServerCallContext context
    ) =>
        HandleAsync(
            "Highlight",
            (bridge, ct) => bridge.HighlightAsync(request.RefId, ct),
            MapToProto,
            context
        );

    /// <summary>
    /// 全 RPC 共通の orchestration: bridge 解決 → 例外翻訳付き呼び出し → proto 変換。
    /// 戻り型が複数 (<c>DashState</c> / <c>DashTabList</c> / <c>DashControlList</c> /
    /// <c>DashActionResult</c>) あるので snapshot 型 <typeparamref name="TSnap"/> と
    /// proto 型 <typeparamref name="TProto"/> でジェネリック化し、各 override は
    /// <paramref name="call"/> と <paramref name="map"/> を差し込むだけ。
    /// </summary>
    private async Task<TProto> HandleAsync<TSnap, TProto>(
        string rpc,
        Func<IDashBridge, CancellationToken, Task<TSnap>> call,
        Func<TSnap, TProto> map,
        ServerCallContext context
    )
    {
        var bridge = BridgeGuard.Require(_bridge, _log, "Dash", "IDashBridge", rpc);

        var snapshot = await BridgeFault
            .InvokeAsync(
                _log,
                "Dash",
                rpc,
                ct => call(bridge, ct),
                context.CancellationToken,
                Translate
            )
            .ConfigureAwait(false);

        return map(snapshot);

        RpcException? Translate(Exception ex)
        {
            switch (ex)
            {
                case DashNotReadyException notReady:
                    return BridgeFault.Translate(
                        _log,
                        "Dash",
                        rpc,
                        StatusCode.FailedPrecondition,
                        "bridge not ready",
                        notReady
                    );
                case ArgumentException invalid:
                    return BridgeFault.Translate(
                        _log,
                        "Dash",
                        rpc,
                        StatusCode.InvalidArgument,
                        "invalid argument",
                        invalid
                    );
                default:
                    return null;
            }
        }
    }

    private static V1.DashState MapToProto(DashStateSnapshot snapshot) =>
        new() { IsOpen = snapshot.IsOpen, OpenLerp = snapshot.OpenLerp };

    private static V1.DashActionResult MapToProto(DashActionResultSnapshot snapshot) =>
        new()
        {
            Ok = snapshot.Ok,
            Found = snapshot.Found,
            RefId = snapshot.RefId,
            Detail = snapshot.Detail,
        };

    private static V1.DashTab MapToProto(DashTabSnapshot tab) =>
        new()
        {
            RefId = tab.RefId,
            LocaleKey = tab.LocaleKey,
            Name = tab.Name,
            Label = tab.Label,
            IsCurrent = tab.IsCurrent,
            Enabled = tab.Enabled,
        };

    private static V1.DashTabList MapToProto(DashTabListSnapshot snapshot)
    {
        var list = new V1.DashTabList();

        foreach (var tab in snapshot.Tabs)
        {
            list.Tabs.Add(MapToProto(tab));
        }

        return list;
    }

    private static V1.DashControl MapToProto(DashControlSnapshot control) =>
        new()
        {
            RefId = control.RefId,
            ControlType = control.ControlType,
            Label = control.Label,
            LocaleKey = control.LocaleKey,
            Enabled = control.Enabled,
            ParentRefId = control.ParentRefId,
            Depth = control.Depth,
        };

    private static V1.DashControlList MapToProto(DashControlListSnapshot snapshot)
    {
        var list = new V1.DashControlList();

        foreach (var control in snapshot.Controls)
        {
            list.Controls.Add(MapToProto(control));
        }

        return list;
    }
}
