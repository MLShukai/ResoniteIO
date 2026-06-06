using Grpc.Core;
using ResoniteIO.Core.Logging;

namespace ResoniteIO.Core.Rpc;

/// <summary>
/// optional DI な Bridge の null チェックを全モダリティで統一する内部ヘルパ。
/// </summary>
/// <remarks>
/// Bridge が未注入 (null) のとき、全 Service で同一の <c>LogWarning</c> 文言と
/// <c>Status.Unavailable</c> ("&lt;Modality&gt; bridge is not configured.") を返す。
/// "bridge not configured" は server-side configuration issue で transient ではないが、
/// gRPC 慣習として "server-side not ready" に Unavailable を使う (client retry policy にも friendly)。
/// </remarks>
internal static class BridgeGuard
{
    /// <summary>
    /// <paramref name="bridge"/> が null なら <c>LogWarning</c> したうえで
    /// <c>Status.Unavailable</c> の <see cref="RpcException"/> を throw し、非 null なら
    /// そのまま返す。
    /// </summary>
    /// <param name="bridge">解決対象の optional bridge。</param>
    /// <param name="log">警告出力先。</param>
    /// <param name="modality">"Camera" / "Display" 等のモダリティ名 (メッセージに使う)。</param>
    /// <param name="interfaceName">"ICameraBridge" 等の bridge interface 名 (警告ログに使う)。</param>
    /// <param name="rpc">"StreamFrames" / "Apply" 等の RPC 名 (警告ログに使う)。</param>
    public static T Require<T>(
        T? bridge,
        ILogSink log,
        string modality,
        string interfaceName,
        string rpc
    )
        where T : class
    {
        if (bridge is null)
        {
            log.LogWarning(
                $"{modality}.{rpc} called but no {interfaceName} is registered; "
                    + "returning Unavailable."
            );
            throw new RpcException(
                new Status(StatusCode.Unavailable, $"{modality} bridge is not configured.")
            );
        }

        return bridge;
    }
}
