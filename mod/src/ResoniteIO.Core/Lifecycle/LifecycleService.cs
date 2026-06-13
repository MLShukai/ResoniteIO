using Grpc.Core;
using ResoniteIO.Core.Logging;
using ResoniteIO.Core.Rpc;

namespace ResoniteIO.Core.Lifecycle;

/// <summary><c>resonite_io.v1.Lifecycle</c> サービスの Core 実装。</summary>
/// <remarks>
/// <see cref="ILifecycleBridge"/> は optional DI: null なら <c>Unavailable</c> を返し、
/// Core 単体テストや bridge 未注入構成も成立させる (他モダリティと同 pattern)。
/// bridge は終了を engine tick に enqueue するだけで即座に返るため、本 RPC は応答を flush
/// してから engine が畳まれる (再入回避は bridge 実装側の責務)。
/// </remarks>
public sealed class LifecycleService : V1.Lifecycle.LifecycleBase
{
    private readonly ILifecycleBridge? _bridge;
    private readonly ILogSink _log;

    public LifecycleService(ILogSink log, ILifecycleBridge? bridge = null)
    {
        _log = log;
        _bridge = bridge;
    }

    public override Task<V1.ShutdownResponse> Shutdown(
        V1.ShutdownRequest request,
        ServerCallContext context
    )
    {
        var bridge = BridgeGuard.Require(
            _bridge,
            _log,
            "Lifecycle",
            "ILifecycleBridge",
            "Shutdown"
        );
        var outcome = bridge.RequestShutdown();
        _log.LogInfo($"Lifecycle.Shutdown scheduled (accepted={outcome.Accepted})");
        return Task.FromResult(new V1.ShutdownResponse { Accepted = outcome.Accepted });
    }
}
