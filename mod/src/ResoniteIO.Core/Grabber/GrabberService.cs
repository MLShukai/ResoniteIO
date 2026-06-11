using Grpc.Core;
using ResoniteIO.Core.Logging;
using ResoniteIO.Core.Rpc;

namespace ResoniteIO.Core.Grabber;

/// <summary><c>resonite_io.v1.Grabber</c> サービスの Core 実装。</summary>
/// <remarks>
/// <see cref="IGrabberBridge"/> は optional DI: null なら <c>Unavailable</c> を返し、
/// Core 単体テストや grabber 非対応 engine 構成も成立させる (ContextMenuService と同 pattern)。
/// 例外翻訳は <see cref="GrabberNotReadyException"/> → <c>FailedPrecondition</c>、その他 → <c>Internal</c>。
/// radius の default 解決 (&lt;=0 → 0.1m) は Core 層で行い、解決後の値を Bridge へ渡す。
/// 各 RPC のセマンティクスは <c>proto/resonite_io/v1/grabber.proto</c> 参照。
/// </remarks>
public sealed class GrabberService : V1.Grabber.GrabberBase
{
    /// <summary>radius が &lt;=0 のときに使うサーバ default の grab 判定球半径 (メートル)。</summary>
    private const float DefaultGrabRadius = 0.1f;

    private readonly IGrabberBridge? _bridge;
    private readonly ILogSink _log;

    public GrabberService(ILogSink log, IGrabberBridge? bridge = null)
    {
        _log = log;
        _bridge = bridge;
    }

    public override async Task<V1.GrabberGrabResult> Grab(
        V1.GrabberGrabRequest request,
        ServerCallContext context
    )
    {
        var bridge = RequireBridge("Grab");
        var hand = ToSelector(request.Hand);
        var radius = request.Radius > 0f ? request.Radius : DefaultGrabRadius;

        var outcome = await InvokeBridge(
                "Grab",
                ct => bridge.GrabAsync(hand, radius, ct),
                context.CancellationToken
            )
            .ConfigureAwait(false);

        return new V1.GrabberGrabResult
        {
            Grabbed = outcome.Grabbed,
            State = MapToProtoState(outcome.State),
        };
    }

    public override async Task<V1.GrabberGrabState> Release(
        V1.GrabberReleaseRequest request,
        ServerCallContext context
    )
    {
        var bridge = RequireBridge("Release");
        var hand = ToSelector(request.Hand);

        var snapshot = await InvokeBridge(
                "Release",
                ct => bridge.ReleaseAsync(hand, ct),
                context.CancellationToken
            )
            .ConfigureAwait(false);

        return MapToProtoState(snapshot);
    }

    public override async Task<V1.GrabberGrabState> GetState(
        V1.GrabberGetStateRequest request,
        ServerCallContext context
    )
    {
        var bridge = RequireBridge("GetState");
        var hand = ToSelector(request.Hand);

        var snapshot = await InvokeBridge(
                "GetState",
                ct => bridge.GetStateAsync(hand, ct),
                context.CancellationToken
            )
            .ConfigureAwait(false);

        return MapToProtoState(snapshot);
    }

    private IGrabberBridge RequireBridge(string rpc) =>
        BridgeGuard.Require(_bridge, _log, "Grabber", "IGrabberBridge", rpc);

    private Task<T> InvokeBridge<T>(
        string rpc,
        Func<CancellationToken, Task<T>> call,
        CancellationToken ct
    ) =>
        BridgeFault.InvokeAsync(
            _log,
            "Grabber",
            rpc,
            call,
            ct,
            ex =>
                ex is GrabberNotReadyException notReady
                    ? BridgeFault.Translate(
                        _log,
                        "Grabber",
                        rpc,
                        StatusCode.FailedPrecondition,
                        "bridge not ready",
                        notReady
                    )
                    : null
        );

    private static GrabberHandSelector ToSelector(V1.GrabberHand hand) =>
        hand switch
        {
            V1.GrabberHand.Left => GrabberHandSelector.Left,
            V1.GrabberHand.Right => GrabberHandSelector.Right,
            // UNSPECIFIED / PRIMARY / 未知の値はすべて Primary 扱い。
            _ => GrabberHandSelector.Primary,
        };

    private static V1.GrabberHand ToProtoHand(GrabberHandSelector hand) =>
        hand switch
        {
            GrabberHandSelector.Left => V1.GrabberHand.Left,
            GrabberHandSelector.Right => V1.GrabberHand.Right,
            _ => V1.GrabberHand.Primary,
        };

    private static V1.GrabberGrabState MapToProtoState(GrabSnapshot snapshot)
    {
        var state = new V1.GrabberGrabState
        {
            Hand = ToProtoHand(snapshot.Hand),
            IsHolding = snapshot.IsHolding,
            UnixNanos = UnixNanosClock.Now(),
        };
        state.ObjectNames.AddRange(snapshot.ObjectNames);
        return state;
    }
}
