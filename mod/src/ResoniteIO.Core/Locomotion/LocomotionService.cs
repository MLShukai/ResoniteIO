using Grpc.Core;
using ResoniteIO.Core.Bridge;
using ResoniteIO.Core.Logging;

#pragma warning disable CA1031 // catch (Exception) は Bridge 側の任意例外を gRPC Status に翻訳するために必要

namespace ResoniteIO.Core.Locomotion;

/// <summary><c>resonite_io.v1.Locomotion</c> サービスの Core 実装。</summary>
/// <remarks>
/// <see cref="ILocomotionBridge"/> は optional DI: null なら <c>Unavailable</c> を返し、
/// Core 単体テストや locomotion 非対応 engine 構成も成立させる (CameraService と
/// 同 pattern)。Bridge 例外は <see cref="LocomotionNotReadyException"/> →
/// <c>FailedPrecondition</c>、それ以外 → <c>Internal</c> に翻訳。
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
            throw new RpcException(
                new Status(StatusCode.Unavailable, "Locomotion bridge is not configured.")
            );
        }

        var ct = context.CancellationToken;
        long received = 0;

        try
        {
            while (await requestStream.MoveNext(ct).ConfigureAwait(false))
            {
                var cmd = MapFromProto(requestStream.Current);

                try
                {
                    await _bridge.ApplyAsync(cmd, ct).ConfigureAwait(false);
                }
                catch (OperationCanceledException)
                {
                    throw;
                }
                catch (LocomotionNotReadyException ex)
                {
                    _log.LogInfo($"Locomotion.Drive: bridge not ready: {ex.Message}");
                    throw new RpcException(new Status(StatusCode.FailedPrecondition, ex.Message));
                }
                catch (Exception ex)
                {
                    _log.LogError($"Locomotion.Drive: bridge faulted: {ex}");
                    throw new RpcException(
                        new Status(StatusCode.Internal, $"Locomotion bridge faulted: {ex.Message}")
                    );
                }

                received++;
            }
        }
        catch (OperationCanceledException)
        {
            // gRPC のキャンセル経路は response を返せないので summary は捨てる
            // (CameraService と同じ pattern)。
            _log.LogDebug($"Locomotion.Drive cancelled after {received} command(s)");
            throw;
        }

        var unixNanos = (DateTimeOffset.UtcNow.UtcTicks - DateTime.UnixEpoch.Ticks) * 100L;
        _log.LogDebug($"Locomotion.Drive end: applied {received} command(s)");

        return new V1.LocomotionDriveSummary
        {
            ReceivedCount = received,
            DroppedCount = 0L,
            UnixNanos = unixNanos,
        };
    }

    private static LocomotionCommand MapFromProto(V1.LocomotionCommand proto) =>
        new(
            MoveX: proto.MoveX,
            MoveY: proto.MoveY,
            YawRate: proto.YawRate,
            PitchRate: proto.PitchRate,
            Jump: proto.Jump,
            Velocity: proto.Velocity,
            Crouch: proto.Crouch,
            UnixNanos: proto.UnixNanos
        );
}
