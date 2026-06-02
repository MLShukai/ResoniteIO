using Grpc.Core;
using ResoniteIO.Core.Logging;

namespace ResoniteIO.Core.Locomotion;

/// <summary><c>resonite_io.v1.Locomotion</c> サービスの Core 実装。</summary>
/// <remarks>
/// <see cref="ILocomotionBridge"/> は optional DI: null なら <c>Unavailable</c>
/// を返す (Core 単体テスト + locomotion 非対応 engine 構成を成立させる、
/// CameraService と同 pattern)。Bridge 側の任意例外は <c>Drive</c> / <c>Reset</c>
/// 両 RPC で <c>Internal</c> に翻訳する。各 RPC のセマンティクスは
/// <c>proto/resonite_io/v1/locomotion.proto</c> 参照。
/// </remarks>
public sealed class LocomotionService : V1.Locomotion.LocomotionBase
{
    private readonly ILocomotionBridge? _bridge;
    private readonly ILogSink _log;

    public LocomotionService(ILogSink log, ILocomotionBridge? bridge = null)
    {
        _log = log;
        _bridge = bridge;
    }

    public override async Task<V1.LocomotionDriveSummary> Drive(
        IAsyncStreamReader<V1.LocomotionCommand> requestStream,
        ServerCallContext context
    )
    {
        if (_bridge is null)
        {
            _log.LogWarning(
                "Locomotion.Drive called but no ILocomotionBridge is registered; "
                    + "returning Unavailable."
            );
            // "bridge not configured" は server-side configuration issue で transient ではないが、
            // gRPC 慣習として "server-side not ready" に Unavailable を使う (client retry policy にも friendly)。
            throw new RpcException(
                new Status(StatusCode.Unavailable, "Locomotion bridge is not configured.")
            );
        }

        var ct = context.CancellationToken;
        long received = 0;

        // Cancel 経路は Grpc.AspNetCore + Kestrel UDS で OperationCanceledException
        // / IOException / 別系例外+ct のどれで表面化するか実装依存なため、
        // when 句で 1 つの Cancelled bucket に集約する (詳細:
        // feedback_grpc_client_cancel_exception_surface.md)。
#pragma warning disable CA1031 // catch (Exception) は Bridge 例外を NotifyDisconnect(Errored) に翻訳するため必要
        try
        {
            while (await requestStream.MoveNext(ct).ConfigureAwait(false))
            {
                var cmd = MapFromProto(requestStream.Current);
                _bridge.SetState(cmd);
                received++;
            }
        }
        catch (Exception ex)
            when (ex is OperationCanceledException
                || ex is IOException
                || ct.IsCancellationRequested
            )
        {
            _log.LogDebug(
                $"Locomotion.Drive cancelled after {received} command(s) "
                    + $"({ex.GetType().Name}): {ex.Message}"
            );
            _bridge.NotifyDisconnect(LocomotionDisconnectReason.Cancelled);
            throw;
        }
        catch (Exception ex)
        {
            _log.LogError($"Locomotion.Drive faulted after {received} command(s): {ex}");
            _bridge.NotifyDisconnect(LocomotionDisconnectReason.Errored);
            throw new RpcException(
                new Status(StatusCode.Internal, $"Locomotion stream faulted: {ex.Message}")
            );
        }
#pragma warning restore CA1031

        // MoveNext returned false = client が CompleteAsync で graceful close。
        _bridge.NotifyDisconnect(LocomotionDisconnectReason.Graceful);

        var unixNanos = UnixNanosClock.Now();
        _log.LogDebug($"Locomotion.Drive end: applied {received} command(s)");

        return new V1.LocomotionDriveSummary
        {
            ReceivedCount = received,
            DroppedCount = 0L,
            UnixNanos = unixNanos,
        };
    }

    public override Task<V1.LocomotionResetSummary> Reset(
        V1.LocomotionResetRequest request,
        ServerCallContext context
    )
    {
        if (_bridge is null)
        {
            _log.LogWarning(
                "Locomotion.Reset called but no ILocomotionBridge is registered; "
                    + "returning Unavailable."
            );
            throw new RpcException(
                new Status(StatusCode.Unavailable, "Locomotion bridge is not configured.")
            );
        }

        // 全 false → 全 reset の展開規約は LocomotionResetRequest proto docstring 参照。
        var flags = ToFlags(request);
        if (flags == LocomotionResetFlags.None)
        {
            flags = LocomotionResetFlags.All;
        }

#pragma warning disable CA1031 // catch (Exception) は Bridge 側の任意例外を gRPC Status に翻訳するために必要
        try
        {
            _bridge.Reset(flags);
        }
        catch (Exception ex)
        {
            _log.LogError($"Locomotion.Reset: bridge faulted: {ex}");
            throw new RpcException(
                new Status(StatusCode.Internal, $"Locomotion bridge faulted: {ex.Message}")
            );
        }
#pragma warning restore CA1031

        var unixNanos = UnixNanosClock.Now();
        _log.LogDebug($"Locomotion.Reset applied flags={flags}");

        return Task.FromResult(
            new V1.LocomotionResetSummary
            {
                Move = flags.HasFlag(LocomotionResetFlags.Move),
                Look = flags.HasFlag(LocomotionResetFlags.Look),
                Crouch = flags.HasFlag(LocomotionResetFlags.Crouch),
                Jump = flags.HasFlag(LocomotionResetFlags.Jump),
                UnixNanos = unixNanos,
            }
        );
    }

    private static LocomotionResetFlags ToFlags(V1.LocomotionResetRequest request)
    {
        var flags = LocomotionResetFlags.None;
        if (request.Move)
        {
            flags |= LocomotionResetFlags.Move;
        }
        if (request.Look)
        {
            flags |= LocomotionResetFlags.Look;
        }
        if (request.Crouch)
        {
            flags |= LocomotionResetFlags.Crouch;
        }
        if (request.Jump)
        {
            flags |= LocomotionResetFlags.Jump;
        }
        return flags;
    }

    private static LocomotionInput MapFromProto(V1.LocomotionCommand proto) =>
        new(
            MoveForward: proto.MoveForward,
            MoveRight: proto.MoveRight,
            MoveUp: proto.MoveUp,
            YawRate: proto.YawRate,
            PitchRate: proto.PitchRate,
            Jump: proto.Jump,
            Velocity: proto.Velocity,
            Crouch: proto.Crouch,
            UnixNanos: proto.UnixNanos
        );
}
