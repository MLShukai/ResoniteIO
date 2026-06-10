using System;
using System.Threading;
using System.Threading.Tasks;
using FrooxEngine;

namespace ResoniteIO.Bridge;

/// <summary>
/// FrooxEngine の <see cref="World"/> 上に処理を one-shot で marshal するための
/// 共通拡張メソッド群。各 <c>FrooxEngine&lt;Modality&gt;Bridge</c> が個別に持っていた
/// <c>RunOnEngineAsync</c> の TCS/RunSynchronously/ct.Register ボイラープレートを集約する。
/// </summary>
/// <remarks>
/// <para>
/// <see cref="TaskCompletionSource{T}"/> は
/// <see cref="TaskCreationOptions.RunContinuationsAsynchronously"/> で生成する。TCS の完了は
/// engine update thread 上で起きるため、無指定だと continuation が engine thread に inline
/// 実行され engine tick を塞ぐ。
/// </para>
/// <para>
/// 完了は <c>TrySet*</c> 系で行う。<paramref name="ct"/> の cancel で
/// <see cref="TaskCompletionSource{T}.TrySetCanceled(CancellationToken)"/> が成立した後に
/// deferred な engine action が走っても、<c>SetResult</c>/<c>SetException</c> のように
/// <see cref="InvalidOperationException"/> を engine thread 上で投げない。
/// </para>
/// </remarks>
internal static class EngineDispatch
{
    /// <summary>
    /// engine update tick 上で <paramref name="fn"/> を one-shot 実行し、その結果を await する。
    /// </summary>
    public static async Task<T> RunOnEngineAsync<T>(
        this World world,
        Func<T> fn,
        CancellationToken ct
    )
    {
        var tcs = new TaskCompletionSource<T>(TaskCreationOptions.RunContinuationsAsynchronously);
        world.RunSynchronously(() =>
        {
            try
            {
                tcs.TrySetResult(fn());
            }
            catch (Exception ex)
            {
                tcs.TrySetException(ex);
            }
        });
        using (ct.Register(() => tcs.TrySetCanceled(ct)))
        {
            return await tcs.Task.ConfigureAwait(false);
        }
    }

    /// <summary>
    /// engine update tick 上で <paramref name="action"/> を one-shot 実行し、その完了まで await する。
    /// </summary>
    public static Task RunOnEngineAsync(this World world, Action action, CancellationToken ct)
    {
        return world.RunOnEngineAsync(
            () =>
            {
                action();
                return true;
            },
            ct
        );
    }
}
