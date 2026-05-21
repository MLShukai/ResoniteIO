using Grpc.Core;
using ResoniteIO.Core.Logging;

#pragma warning disable CA1031 // catch (Exception) は Bridge 側の任意例外を gRPC Status に翻訳するために必要

namespace ResoniteIO.Core.Display;

/// <summary><c>resonite_io.v1.Display</c> サービスの Core 実装。</summary>
/// <remarks>
/// <see cref="IDisplayBridge"/> は optional DI: null なら <c>Unavailable</c> を返し、
/// Core 単体テストや display 非対応 engine 構成も成立させる (CameraService と同 pattern)。
/// 例外翻訳は <see cref="DisplayNotReadyException"/> → <c>FailedPrecondition</c>、その他 → <c>Internal</c>。
/// </remarks>
public sealed class DisplayService : V1.Display.DisplayBase
{
    private readonly IDisplayBridge? _bridge;
    private readonly ILogSink _log;

    public DisplayService(ILogSink log, IDisplayBridge? bridge = null)
    {
        _log = log;
        _bridge = bridge;
    }

    public override async Task<V1.DisplayApplyResponse> Apply(
        V1.DisplayConfig request,
        ServerCallContext context
    )
    {
        if (_bridge is null)
        {
            _log.LogWarning(
                "Display.Apply called but no IDisplayBridge is registered; returning Unavailable."
            );
            // "bridge not configured" は server-side configuration issue で transient ではないが、
            // gRPC 慣習として "server-side not ready" に Unavailable を使う (client retry policy にも friendly)。
            throw new RpcException(
                new Status(StatusCode.Unavailable, "Display bridge is not configured.")
            );
        }

        var snapshot = new DisplayConfigSnapshot
        {
            Width = request.Width,
            Height = request.Height,
            MaxFps = request.MaxFps,
        };

        try
        {
            await _bridge.ApplyAsync(snapshot, context.CancellationToken).ConfigureAwait(false);
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (DisplayNotReadyException ex)
        {
            _log.LogInfo($"Display.Apply: bridge not ready: {ex.Message}");
            throw new RpcException(new Status(StatusCode.FailedPrecondition, ex.Message));
        }
        catch (Exception ex)
        {
            _log.LogError($"Display.Apply: bridge faulted: {ex}");
            throw new RpcException(
                new Status(StatusCode.Internal, $"Display bridge faulted: {ex.Message}")
            );
        }

        // Apply の Empty 応答契約は proto / IDisplayBridge.ApplyAsync XML 参照。
        return new V1.DisplayApplyResponse();
    }

    public override async Task<V1.DisplayState> Get(
        V1.DisplayGetRequest request,
        ServerCallContext context
    )
    {
        if (_bridge is null)
        {
            _log.LogWarning(
                "Display.Get called but no IDisplayBridge is registered; returning Unavailable."
            );
            throw new RpcException(
                new Status(StatusCode.Unavailable, "Display bridge is not configured.")
            );
        }

        DisplayConfigSnapshot snapshot;
        try
        {
            snapshot = await _bridge.GetAsync(context.CancellationToken).ConfigureAwait(false);
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (DisplayNotReadyException ex)
        {
            _log.LogInfo($"Display.Get: bridge not ready: {ex.Message}");
            throw new RpcException(new Status(StatusCode.FailedPrecondition, ex.Message));
        }
        catch (Exception ex)
        {
            _log.LogError($"Display.Get: bridge faulted: {ex}");
            throw new RpcException(
                new Status(StatusCode.Internal, $"Display bridge faulted: {ex.Message}")
            );
        }

        return ToProto(snapshot);
    }

    private static V1.DisplayState ToProto(DisplayConfigSnapshot snapshot) =>
        new()
        {
            Width = snapshot.Width,
            Height = snapshot.Height,
            MaxFps = snapshot.MaxFps,
        };
}
