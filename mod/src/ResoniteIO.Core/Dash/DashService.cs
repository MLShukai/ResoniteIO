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

    public override Task<V1.DashTree> GetTree(
        V1.DashGetTreeRequest request,
        ServerCallContext context
    ) =>
        HandleAsync(
            "GetTree",
            (bridge, ct) => bridge.GetTreeAsync(request.InteractableOnly, request.RootRefId, ct),
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

    public override Task<V1.DashScreenList> ListScreens(
        V1.DashListScreensRequest request,
        ServerCallContext context
    ) =>
        HandleAsync(
            "ListScreens",
            (bridge, ct) => bridge.ListScreensAsync(ct),
            MapToProto,
            context
        );

    public override Task<V1.DashActionResult> SetScreen(
        V1.DashSetScreenRequest request,
        ServerCallContext context
    ) =>
        HandleAsync(
            "SetScreen",
            (bridge, ct) =>
            {
                // ref_id / key 両空はクライアントの引数ミス。bridge を起動せず InvalidArgument に翻訳する
                // (既存の ArgumentException → InvalidArgument 経路に乗せる)。
                if (string.IsNullOrEmpty(request.RefId) && string.IsNullOrEmpty(request.Key))
                {
                    throw new ArgumentException("ref_id or key must be provided.");
                }

                return bridge.SetScreenAsync(request.RefId, request.Key, ct);
            },
            MapToProto,
            context
        );

    /// <summary>
    /// 全 RPC 共通の orchestration: bridge 解決 → 例外翻訳付き呼び出し → proto 変換。
    /// 戻り型が 3 種 (<c>DashState</c> / <c>DashTree</c> / <c>DashActionResult</c>) あるので
    /// snapshot 型 <typeparamref name="TSnap"/> と proto 型 <typeparamref name="TProto"/> で
    /// ジェネリック化し、各 override は <paramref name="call"/> と <paramref name="map"/> を差し込むだけ。
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

    private static V1.DashTree MapToProto(DashTreeSnapshot snapshot)
    {
        var tree = new V1.DashTree
        {
            ScreenWidth = snapshot.ScreenWidth,
            ScreenHeight = snapshot.ScreenHeight,
        };

        foreach (var element in snapshot.Elements)
        {
            tree.Elements.Add(MapToProto(element));
        }

        return tree;
    }

    private static V1.DashElement MapToProto(DashElementSnapshot element) =>
        new()
        {
            RefId = element.RefId,
            Type = element.Type,
            SlotName = element.SlotName,
            LocaleKey = element.LocaleKey,
            Label = element.Label,
            Enabled = element.Enabled,
            Interactable = element.Interactable,
            Rect = new V1.DashRect
            {
                X = element.Rect.X,
                Y = element.Rect.Y,
                Width = element.Rect.Width,
                Height = element.Rect.Height,
                IsScreenSpace = element.Rect.IsScreenSpace,
            },
            ParentRefId = element.ParentRefId,
            Depth = element.Depth,
        };

    private static V1.DashScreen MapToProto(DashScreenSnapshot screen) =>
        new()
        {
            RefId = screen.RefId,
            Key = screen.Key,
            Name = screen.Name,
            Label = screen.Label,
            IsCurrent = screen.IsCurrent,
            Enabled = screen.Enabled,
        };

    private static V1.DashScreenList MapToProto(DashScreenListSnapshot snapshot)
    {
        var list = new V1.DashScreenList();

        foreach (var screen in snapshot.Screens)
        {
            list.Screens.Add(MapToProto(screen));
        }

        return list;
    }
}
