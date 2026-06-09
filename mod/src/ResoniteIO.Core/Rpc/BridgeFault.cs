using Grpc.Core;
using ResoniteIO.Core.Logging;

#pragma warning disable CA1031 // catch (Exception) は Bridge 側の任意例外を gRPC Status に翻訳するために必要

namespace ResoniteIO.Core.Rpc;

/// <summary>
/// unary RPC の Bridge 呼び出しに共通する例外 → gRPC Status 翻訳を集約する内部ヘルパ。
/// </summary>
/// <remarks>
/// <para>
/// 共通テール: <see cref="OperationCanceledException"/> はそのまま rethrow (client cancel を
/// Grpc.AspNetCore が <c>Cancelled</c> に変換)、それ以外の例外は <c>Internal</c>
/// ("&lt;Modality&gt; bridge faulted: {message}") に翻訳する。
/// </para>
/// <para>
/// モダリティ固有の status マッピング (NotReady → <c>FailedPrecondition</c>、NotFound →
/// <c>NotFound</c> 等) は <paramref name="translate"/> delegate を呼び出し側で渡して残す。
/// delegate は処理した例外に対応する <see cref="RpcException"/> を返し (ログ出力も delegate 側で行う)、
/// 未処理なら <c>null</c> を返して共通の <c>Internal</c> 経路に委ねる。
/// </para>
/// </remarks>
internal static class BridgeFault
{
    /// <summary>
    /// <paramref name="call"/> を実行し、例外を gRPC Status に翻訳する。
    /// </summary>
    /// <param name="log">Internal 翻訳時の error 出力先。</param>
    /// <param name="modality">"ContextMenu" / "Dash" 等のモダリティ名 (メッセージに使う)。</param>
    /// <param name="rpc">"Open" / "Invoke" 等の RPC 名 (ログに使う)。</param>
    /// <param name="call">Bridge 呼び出し本体。</param>
    /// <param name="ct">呼び出しに渡す cancellation token。</param>
    /// <param name="translate">
    /// モダリティ固有の例外を <see cref="RpcException"/> に翻訳する delegate。処理しない例外には
    /// <c>null</c> を返す。<c>null</c> を渡すと共通 (Internal) 翻訳のみ行う。
    /// </param>
    public static async Task<T> InvokeAsync<T>(
        ILogSink log,
        string modality,
        string rpc,
        Func<CancellationToken, Task<T>> call,
        CancellationToken ct,
        Func<Exception, RpcException?>? translate = null
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
        catch (IOException) when (ct.IsCancellationRequested)
        {
            // Kestrel UDS では client cancel が OperationCanceledException でなく IOException で
            // 表面化する経路がある (feedback_grpc_client_cancel_exception_surface)。
            // Internal に翻訳せず素通しする。
            throw;
        }
        catch (Exception ex)
        {
            var translated = translate?.Invoke(ex);
            if (translated is not null)
            {
                throw translated;
            }

            log.LogError($"{modality}.{rpc}: bridge faulted: {ex}");
            throw new RpcException(
                new Status(StatusCode.Internal, $"{modality} bridge faulted: {ex.Message}")
            );
        }
    }

    /// <summary>
    /// モダリティ固有例外を <c>LogInfo</c> したうえで <see cref="RpcException"/> に翻訳する定型ヘルパ。
    /// 各 Service の <c>translate</c> delegate 内の "NotReady → FailedPrecondition" 等の case を畳む。
    /// </summary>
    /// <param name="log">情報ログの出力先。</param>
    /// <param name="modality">"World" / "Dash" 等のモダリティ名 (ログに使う)。</param>
    /// <param name="rpc">"Join" / "Open" 等の RPC 名 (ログに使う)。</param>
    /// <param name="code">翻訳後の gRPC status code。</param>
    /// <param name="label">"bridge not ready" / "not found" 等のログ内ラベル。</param>
    /// <param name="ex">翻訳対象の例外。<see cref="Exception.Message"/> を Status.Detail に転写する。</param>
    public static RpcException Translate(
        ILogSink log,
        string modality,
        string rpc,
        StatusCode code,
        string label,
        Exception ex
    )
    {
        log.LogInfo($"{modality}.{rpc}: {label}: {ex.Message}");
        return new RpcException(new Status(code, ex.Message));
    }
}
