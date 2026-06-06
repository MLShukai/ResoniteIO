using Grpc.Core;
using ResoniteIO.Core.Logging;

#pragma warning disable CA1031 // catch (Exception) は Bridge 側の任意例外を gRPC Status に翻訳するために必要

namespace ResoniteIO.Core.Cursor;

/// <summary><c>resonite_io.v1.Cursor</c> サービスの Core 実装。</summary>
/// <remarks>
/// <see cref="ICursorBridge"/> は optional DI: null なら <c>Unavailable</c> を返し、
/// Core 単体テストや cursor 非対応 engine 構成も成立させる (ContextMenuService と同 pattern)。
/// <c>SetPosition</c> の正規化座標 ([0,1]) 範囲チェックは engine 非依存なので Service 層で行い、
/// 範囲外は <c>InvalidArgument</c>。Bridge 由来の例外翻訳は
/// <see cref="CursorNotReadyException"/> → <c>FailedPrecondition</c>、
/// <see cref="ArgumentOutOfRangeException"/> → <c>InvalidArgument</c>、その他 → <c>Internal</c>。
/// </remarks>
public sealed class CursorService : V1.Cursor.CursorBase
{
    private readonly ICursorBridge? _bridge;
    private readonly ILogSink _log;

    public CursorService(ILogSink log, ICursorBridge? bridge = null)
    {
        _log = log;
        _bridge = bridge;
    }

    public override Task<V1.CursorState> SetPosition(
        V1.CursorSetPositionRequest request,
        ServerCallContext context
    )
    {
        ValidateNormalized(request.X, request.Y);
        return HandleAsync(
            "SetPosition",
            (bridge, ct) => bridge.SetPositionAsync(request.X, request.Y, ct),
            context
        );
    }

    public override Task<V1.CursorState> GetPosition(
        V1.CursorGetPositionRequest request,
        ServerCallContext context
    ) => HandleAsync("GetPosition", (bridge, ct) => bridge.GetPositionAsync(ct), context);

    /// <summary>正規化座標が [0,1] かつ NaN でないことを検証する。範囲外は <c>InvalidArgument</c>。</summary>
    private static void ValidateNormalized(float x, float y)
    {
        if (float.IsNaN(x) || float.IsNaN(y) || x < 0f || x > 1f || y < 0f || y > 1f)
        {
            throw new RpcException(
                new Status(
                    StatusCode.InvalidArgument,
                    $"Cursor position must be normalized within [0,1]; got ({x}, {y})."
                )
            );
        }
    }

    /// <summary>
    /// 全 RPC 共通の orchestration: bridge 解決 → 例外翻訳付き呼び出し → proto 変換。
    /// 各 override はこの helper に <paramref name="call"/> を差し込むだけ。
    /// </summary>
    private async Task<V1.CursorState> HandleAsync(
        string rpc,
        Func<ICursorBridge, CancellationToken, Task<CursorStateSnapshot>> call,
        ServerCallContext context
    )
    {
        var bridge = RequireBridge(rpc);

        var snapshot = await InvokeBridge(rpc, ct => call(bridge, ct), context.CancellationToken)
            .ConfigureAwait(false);

        return ToProto(snapshot);
    }

    private ICursorBridge RequireBridge(string rpc)
    {
        if (_bridge is null)
        {
            _log.LogWarning(
                $"Cursor.{rpc} called but no ICursorBridge is registered; returning Unavailable."
            );
            throw new RpcException(
                new Status(StatusCode.Unavailable, "Cursor bridge is not configured.")
            );
        }

        return _bridge;
    }

    private async Task<CursorStateSnapshot> InvokeBridge(
        string rpc,
        Func<CancellationToken, Task<CursorStateSnapshot>> call,
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
        catch (CursorNotReadyException ex)
        {
            _log.LogInfo($"Cursor.{rpc}: bridge not ready: {ex.Message}");
            throw new RpcException(new Status(StatusCode.FailedPrecondition, ex.Message));
        }
        catch (ArgumentOutOfRangeException ex)
        {
            _log.LogInfo($"Cursor.{rpc}: invalid argument: {ex.Message}");
            throw new RpcException(new Status(StatusCode.InvalidArgument, ex.Message));
        }
        catch (Exception ex)
        {
            _log.LogError($"Cursor.{rpc}: bridge faulted: {ex}");
            throw new RpcException(
                new Status(StatusCode.Internal, $"Cursor bridge faulted: {ex.Message}")
            );
        }
    }

    private static V1.CursorState ToProto(CursorStateSnapshot snapshot) =>
        new()
        {
            X = snapshot.X,
            Y = snapshot.Y,
            WindowWidth = snapshot.WindowWidth,
            WindowHeight = snapshot.WindowHeight,
        };
}
