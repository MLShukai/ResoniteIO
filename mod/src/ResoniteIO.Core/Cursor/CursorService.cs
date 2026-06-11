using Grpc.Core;
using ResoniteIO.Core.Logging;
using ResoniteIO.Core.Rpc;

namespace ResoniteIO.Core.Cursor;

/// <summary><c>resonite_io.v1.Cursor</c> サービスの Core 実装。</summary>
/// <remarks>
/// <see cref="ICursorBridge"/> は optional DI: null なら <c>Unavailable</c> を返し、
/// Core 単体テストや cursor 非対応 engine 構成も成立させる (ContextMenuService と同 pattern)。
/// <c>SetPosition</c> の正規化座標 ([0,1]) 範囲チェックは engine 非依存なので Service 層で行い、
/// 範囲外は <c>InvalidArgument</c>。Bridge 由来の例外翻訳は <c>SetPosition</c> /
/// <c>GetPosition</c> / <c>Release</c> の全 RPC 共通で
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

    public override Task<V1.CursorState> Release(
        V1.CursorReleaseRequest request,
        ServerCallContext context
    ) => HandleAsync("Release", (bridge, ct) => bridge.ReleaseAsync(ct), context);

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
        var bridge = BridgeGuard.Require(_bridge, _log, "Cursor", "ICursorBridge", rpc);

        var snapshot = await BridgeFault
            .InvokeAsync(
                _log,
                "Cursor",
                rpc,
                ct => call(bridge, ct),
                context.CancellationToken,
                Translate
            )
            .ConfigureAwait(false);

        return ToProto(snapshot);

        RpcException? Translate(Exception ex)
        {
            switch (ex)
            {
                case CursorNotReadyException notReady:
                    return BridgeFault.Translate(
                        _log,
                        "Cursor",
                        rpc,
                        StatusCode.FailedPrecondition,
                        "bridge not ready",
                        notReady
                    );
                case ArgumentOutOfRangeException invalid:
                    return BridgeFault.Translate(
                        _log,
                        "Cursor",
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

    private static V1.CursorState ToProto(CursorStateSnapshot snapshot) =>
        new()
        {
            X = snapshot.X,
            Y = snapshot.Y,
            WindowWidth = snapshot.WindowWidth,
            WindowHeight = snapshot.WindowHeight,
            Held = snapshot.Held,
        };
}
