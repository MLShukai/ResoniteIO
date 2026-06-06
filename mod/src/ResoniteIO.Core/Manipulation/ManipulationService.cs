using Grpc.Core;
using ResoniteIO.Core.Logging;

#pragma warning disable CA1031 // catch (Exception) は Bridge 側の任意例外を gRPC Status に翻訳するために必要

namespace ResoniteIO.Core.Manipulation;

/// <summary><c>resonite_io.v1.Manipulation</c> サービスの Core 実装。</summary>
/// <remarks>
/// <see cref="IManipulationBridge"/> は optional DI: null なら <c>Unavailable</c> を返し、
/// Core 単体テストや manipulation 非対応 engine 構成も成立させる (ContextMenuService と同 pattern)。
/// 例外翻訳は <see cref="ManipulationNotReadyException"/> → <c>FailedPrecondition</c>、その他 → <c>Internal</c>。
/// radius の default 解決 (&lt;=0 → 0.1m) は Core 層で行い、解決後の値を Bridge へ渡す。
/// 各 RPC のセマンティクスは <c>proto/resonite_io/v1/manipulation.proto</c> 参照。
/// </remarks>
public sealed class ManipulationService : V1.Manipulation.ManipulationBase
{
    /// <summary>radius が &lt;=0 のときに使うサーバ default の grab 判定球半径 (メートル)。</summary>
    private const float DefaultGrabRadius = 0.1f;

    private readonly IManipulationBridge? _bridge;
    private readonly ILogSink _log;

    public ManipulationService(ILogSink log, IManipulationBridge? bridge = null)
    {
        _log = log;
        _bridge = bridge;
    }

    public override async Task<V1.ManipulationGrabResult> Grab(
        V1.ManipulationGrabRequest request,
        ServerCallContext context
    )
    {
        var bridge = RequireBridge("Grab");
        var hand = ToSelector(request.Hand);
        var point = ToPoint(request);
        var radius = request.Radius > 0f ? request.Radius : DefaultGrabRadius;

        var outcome = await InvokeBridge(
                "Grab",
                ct => bridge.GrabAsync(hand, point, radius, ct),
                context.CancellationToken
            )
            .ConfigureAwait(false);

        return new V1.ManipulationGrabResult
        {
            Grabbed = outcome.Grabbed,
            State = MapToProtoState(outcome.State),
        };
    }

    public override async Task<V1.ManipulationGrabState> Release(
        V1.ManipulationReleaseRequest request,
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

    public override async Task<V1.ManipulationGrabState> GetState(
        V1.ManipulationGetStateRequest request,
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

    private IManipulationBridge RequireBridge(string rpc)
    {
        if (_bridge is null)
        {
            _log.LogWarning(
                $"Manipulation.{rpc} called but no IManipulationBridge is registered; "
                    + "returning Unavailable."
            );
            // "bridge not configured" は server-side configuration issue で transient ではないが、
            // gRPC 慣習として "server-side not ready" に Unavailable を使う (client retry policy にも friendly)。
            throw new RpcException(
                new Status(StatusCode.Unavailable, "Manipulation bridge is not configured.")
            );
        }

        return _bridge;
    }

    private async Task<T> InvokeBridge<T>(
        string rpc,
        Func<CancellationToken, Task<T>> call,
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
        catch (ManipulationNotReadyException ex)
        {
            _log.LogInfo($"Manipulation.{rpc}: bridge not ready: {ex.Message}");
            throw new RpcException(new Status(StatusCode.FailedPrecondition, ex.Message));
        }
        catch (Exception ex)
        {
            _log.LogError($"Manipulation.{rpc}: bridge faulted: {ex}");
            throw new RpcException(
                new Status(StatusCode.Internal, $"Manipulation bridge faulted: {ex.Message}")
            );
        }
    }

    private static ManipulationHandSelector ToSelector(V1.ManipulationHand hand) =>
        hand switch
        {
            V1.ManipulationHand.Left => ManipulationHandSelector.Left,
            V1.ManipulationHand.Right => ManipulationHandSelector.Right,
            // UNSPECIFIED / PRIMARY / 未知の値はすべて Primary 扱い。
            _ => ManipulationHandSelector.Primary,
        };

    private static ManipulationPoint? ToPoint(V1.ManipulationGrabRequest request)
    {
        if (request.Point is null)
        {
            return null;
        }

        var p = request.Point;
        return new ManipulationPoint(p.X, p.Y, p.Z);
    }

    private static V1.ManipulationHand ToProtoHand(ManipulationHandSelector hand) =>
        hand switch
        {
            ManipulationHandSelector.Left => V1.ManipulationHand.Left,
            ManipulationHandSelector.Right => V1.ManipulationHand.Right,
            _ => V1.ManipulationHand.Primary,
        };

    private static V1.ManipulationGrabState MapToProtoState(GrabSnapshot snapshot)
    {
        var state = new V1.ManipulationGrabState
        {
            Hand = ToProtoHand(snapshot.Hand),
            IsHolding = snapshot.IsHolding,
            UnixNanos = UnixNanosClock.Now(),
        };

        foreach (var name in snapshot.ObjectNames)
        {
            state.ObjectNames.Add(name);
        }

        return state;
    }
}
