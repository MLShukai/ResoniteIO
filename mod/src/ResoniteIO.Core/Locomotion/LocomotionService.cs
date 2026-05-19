using Grpc.Core;
using ResoniteIO.Core.Bridge;
using ResoniteIO.Core.Logging;

#pragma warning disable CA1031 // catch (Exception) は Bridge 側の任意例外を gRPC Status に翻訳するために必要

namespace ResoniteIO.Core.Locomotion;

/// <summary><c>resonite_io.v1.Locomotion</c> サービスの Core 実装。</summary>
/// <remarks>
/// <see cref="ILocomotionBridge"/> は optional DI: null なら <c>Unavailable</c> を返し、
/// Core 単体テストや locomotion 非対応 engine 構成も成立させる (CameraService と
/// 同 pattern)。例外翻訳は <see cref="LocomotionNotReadyException"/> →
/// <c>FailedPrecondition</c>、その他 → <c>Internal</c>。<see cref="Drive"/> は
/// request stream の各 command を Bridge に直列 <c>await</c> し、完了時に
/// <c>received_count</c> / <c>dropped_count=0</c> / <c>unix_nanos</c> を返す。
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

    /// <summary>
    /// client-streaming RPC。受け取った各 <c>LocomotionCommand</c> を順に Bridge へ
    /// 適用し、完了時に処理件数を summary で返す。
    /// </summary>
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
            // client cancel / deadline。これまでに処理した件数を summary で返す
            // ことはできない (gRPC はキャンセル経路で response を返せない)。
            // CameraService と同様に黙って break する。
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
            Sprint: proto.Sprint,
            Crouch: proto.Crouch,
            SprintMultiplier: proto.SprintMultiplier,
            UnixNanos: proto.UnixNanos
        );
}
