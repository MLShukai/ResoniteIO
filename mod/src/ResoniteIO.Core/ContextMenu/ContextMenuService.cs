using Grpc.Core;
using ResoniteIO.Core.Logging;

#pragma warning disable CA1031 // catch (Exception) は Bridge 側の任意例外を gRPC Status に翻訳するために必要

namespace ResoniteIO.Core.ContextMenu;

/// <summary><c>resonite_io.v1.ContextMenu</c> サービスの Core 実装。</summary>
/// <remarks>
/// <see cref="IContextMenuBridge"/> は optional DI: null なら <c>Unavailable</c> を返し、
/// Core 単体テストや context menu 非対応 engine 構成も成立させる (DisplayService と同 pattern)。
/// 例外翻訳は <see cref="ContextMenuNotReadyException"/> → <c>FailedPrecondition</c>、
/// <see cref="ArgumentOutOfRangeException"/> (不正 index) → <c>InvalidArgument</c>、その他 → <c>Internal</c>。
/// </remarks>
public sealed class ContextMenuService : V1.ContextMenu.ContextMenuBase
{
    private readonly IContextMenuBridge? _bridge;
    private readonly ILogSink _log;

    public ContextMenuService(ILogSink log, IContextMenuBridge? bridge = null)
    {
        _log = log;
        _bridge = bridge;
    }

    public override Task<V1.ContextMenuState> Open(
        V1.ContextMenuOpenRequest request,
        ServerCallContext context
    ) =>
        HandleAsync(
            "Open",
            request.Hand,
            (bridge, hand, ct) => bridge.OpenAsync(hand, ct),
            context
        );

    public override Task<V1.ContextMenuState> Close(
        V1.ContextMenuCloseRequest request,
        ServerCallContext context
    ) =>
        HandleAsync(
            "Close",
            request.Hand,
            (bridge, hand, ct) => bridge.CloseAsync(hand, ct),
            context
        );

    public override Task<V1.ContextMenuState> GetState(
        V1.ContextMenuGetStateRequest request,
        ServerCallContext context
    ) =>
        HandleAsync(
            "GetState",
            request.Hand,
            (bridge, hand, ct) => bridge.GetStateAsync(hand, ct),
            context
        );

    public override Task<V1.ContextMenuState> Highlight(
        V1.ContextMenuHighlightRequest request,
        ServerCallContext context
    ) =>
        HandleAsync(
            "Highlight",
            request.Hand,
            (bridge, hand, ct) => bridge.HighlightAsync(hand, request.Index, ct),
            context
        );

    public override Task<V1.ContextMenuState> Invoke(
        V1.ContextMenuInvokeRequest request,
        ServerCallContext context
    ) =>
        HandleAsync(
            "Invoke",
            request.Hand,
            (bridge, hand, ct) => bridge.InvokeAsync(hand, request.Index, ct),
            context
        );

    /// <summary>
    /// 全 RPC 共通の orchestration: bridge 解決 → hand 変換 → 例外翻訳付き呼び出し →
    /// proto 変換。各 override はこの helper に <paramref name="call"/> を差し込むだけ。
    /// </summary>
    private async Task<V1.ContextMenuState> HandleAsync(
        string rpc,
        V1.ContextMenuHand hand,
        Func<
            IContextMenuBridge,
            ContextMenuHandSelector,
            CancellationToken,
            Task<ContextMenuStateSnapshot>
        > call,
        ServerCallContext context
    )
    {
        var bridge = RequireBridge(rpc);
        var selector = ToSelector(hand);

        var snapshot = await InvokeBridge(
                rpc,
                ct => call(bridge, selector, ct),
                context.CancellationToken
            )
            .ConfigureAwait(false);

        return ToProto(snapshot);
    }

    private IContextMenuBridge RequireBridge(string rpc)
    {
        if (_bridge is null)
        {
            _log.LogWarning(
                $"ContextMenu.{rpc} called but no IContextMenuBridge is registered; returning Unavailable."
            );
            // "bridge not configured" は server-side configuration issue で transient ではないが、
            // gRPC 慣習として "server-side not ready" に Unavailable を使う (client retry policy にも friendly)。
            throw new RpcException(
                new Status(StatusCode.Unavailable, "ContextMenu bridge is not configured.")
            );
        }

        return _bridge;
    }

    private async Task<ContextMenuStateSnapshot> InvokeBridge(
        string rpc,
        Func<CancellationToken, Task<ContextMenuStateSnapshot>> call,
        CancellationToken ct
    )
    {
        try
        {
            return await call(ct).ConfigureAwait(false);
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (ContextMenuNotReadyException ex)
        {
            _log.LogInfo($"ContextMenu.{rpc}: bridge not ready: {ex.Message}");
            throw new RpcException(new Status(StatusCode.FailedPrecondition, ex.Message));
        }
        catch (ArgumentOutOfRangeException ex)
        {
            _log.LogInfo($"ContextMenu.{rpc}: invalid index: {ex.Message}");
            throw new RpcException(new Status(StatusCode.InvalidArgument, ex.Message));
        }
        catch (Exception ex)
        {
            _log.LogError($"ContextMenu.{rpc}: bridge faulted: {ex}");
            throw new RpcException(
                new Status(StatusCode.Internal, $"ContextMenu bridge faulted: {ex.Message}")
            );
        }
    }

    private static ContextMenuHandSelector ToSelector(V1.ContextMenuHand hand) =>
        hand switch
        {
            V1.ContextMenuHand.Left => ContextMenuHandSelector.Left,
            V1.ContextMenuHand.Right => ContextMenuHandSelector.Right,
            // UNSPECIFIED / PRIMARY / 未知の値はすべて Primary 扱い。
            _ => ContextMenuHandSelector.Primary,
        };

    private static V1.ContextMenuState ToProto(ContextMenuStateSnapshot snapshot)
    {
        var state = new V1.ContextMenuState
        {
            IsOpen = snapshot.IsOpen,
            HighlightedIndex = snapshot.HighlightedIndex,
        };

        foreach (var item in snapshot.Items)
        {
            state.Items.Add(
                new V1.ContextMenuItem
                {
                    Index = item.Index,
                    Label = item.Label,
                    Enabled = item.Enabled,
                    HasIcon = item.HasIcon,
                    ColorR = item.ColorR,
                    ColorG = item.ColorG,
                    ColorB = item.ColorB,
                    ColorA = item.ColorA,
                }
            );
        }

        return state;
    }
}
