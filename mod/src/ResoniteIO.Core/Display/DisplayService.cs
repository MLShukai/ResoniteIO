using Grpc.Core;
using ResoniteIO.Core.Logging;
using ResoniteIO.Core.Rpc;

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
        var bridge = BridgeGuard.Require(_bridge, _log, "Display", "IDisplayBridge", "Apply");

        var snapshot = new DisplayConfigSnapshot
        {
            Width = request.Width,
            Height = request.Height,
            MaxFps = request.MaxFps,
        };

        await BridgeFault
            .InvokeAsync(
                _log,
                "Display",
                "Apply",
                async ct =>
                {
                    await bridge.ApplyAsync(snapshot, ct).ConfigureAwait(false);
                    return true;
                },
                context.CancellationToken,
                ex => TranslateNotReady("Apply", ex)
            )
            .ConfigureAwait(false);

        // Apply の Empty 応答契約は proto / IDisplayBridge.ApplyAsync XML 参照。
        return new V1.DisplayApplyResponse();
    }

    public override async Task<V1.DisplayState> Get(
        V1.DisplayGetRequest request,
        ServerCallContext context
    )
    {
        var bridge = BridgeGuard.Require(_bridge, _log, "Display", "IDisplayBridge", "Get");

        var snapshot = await BridgeFault
            .InvokeAsync(
                _log,
                "Display",
                "Get",
                ct => bridge.GetAsync(ct),
                context.CancellationToken,
                ex => TranslateNotReady("Get", ex)
            )
            .ConfigureAwait(false);

        return ToProto(snapshot);
    }

    private RpcException? TranslateNotReady(string rpc, Exception ex)
    {
        if (ex is DisplayNotReadyException notReady)
        {
            _log.LogInfo($"Display.{rpc}: bridge not ready: {notReady.Message}");
            return new RpcException(new Status(StatusCode.FailedPrecondition, notReady.Message));
        }

        return null;
    }

    private static V1.DisplayState ToProto(DisplayConfigSnapshot snapshot) =>
        new()
        {
            Width = snapshot.Width,
            Height = snapshot.Height,
            MaxFps = snapshot.MaxFps,
        };
}
