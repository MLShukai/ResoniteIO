using System;
using System.Threading;
using System.Threading.Tasks;
using Elements.Core;
using FrooxEngine;
using ResoniteIO.Core.Cursor;
using ResoniteIO.Core.Logging;

namespace ResoniteIO.Bridge;

/// <summary>FrooxEngine の desktop カーソル位置を操作する <see cref="ICursorBridge"/> 実装。</summary>
/// <remarks>
/// <para>
/// 全操作は <see cref="World.RunSynchronously(System.Action)"/> で engine thread に
/// one-shot で marshal する (<see cref="RunOnEngineAsync{T}"/>)。
/// </para>
/// <para>
/// 位置の設定は「<b>warp → settle → 即 release</b>」の one-shot で行い、RPC を跨いだ
/// 状態は一切保持しない。engine thread 上で目標ピクセルを解決した後、
/// (a) <see cref="InputInterface.SetMousePosition"/> で OS カーソルを warp し
/// (native では実カーソルが移動、Wine/Proton では injection 非対応のため no-op)、
/// (b) <see cref="InputBindingManager.RegisterCursorLock"/> による一時 lock で
/// <c>Mouse.WindowPosition</c> を強制する (<c>Mouse.Update</c> は
/// <c>CursorLockPosition</c> がセットされていると毎フレーム <c>WindowPosition</c> を
/// そこへ上書きする。decompiled/.../Mouse.cs:67-71)。settle (反映) を確認したら、
/// cancel 経路を含むあらゆる経路で <b>呼び出しが戻る前に必ず
/// <c>UnregisterCursorLock</c> で lock を解放する</b> (register と cancel の競合は
/// <see cref="WarpAndLockAsync"/> の engine action 側 rollback が塞ぐ)。旧実装は lock を
/// 永続保持していたため Resonite フォーカス中はマウスが掴まれ他アプリを操作できな
/// かったが、現実装では呼び出し終了後にマウスは自由になる。
/// </para>
/// <para>
/// 帰結として位置は保持されない: Wine では OS warp が no-op のため、lock 解放後の
/// 次フレームで <c>WindowPosition</c> は実 OS カーソル位置へ戻る。menu-at-cursor の
/// ような位置依存の後続操作は、warp が効いている同一操作内でのみ成立する。
/// </para>
/// </remarks>
internal sealed class FrooxEngineCursorBridge : ICursorBridge
{
    // 他の locker (mouse-look 等) に勝てるよう高い priority を使う。
    // LockCursor getter は priority 最大の locker の position を採用する。
    private const int _lockPriority = 1_000_000;

    // lock 反映 (= 次フレームの Mouse.Update) を待つポーリング: ~320ms 相当。
    private static readonly TimeSpan _settlePollInterval = TimeSpan.FromMilliseconds(16);
    private const int _settlePollMaxAttempts = 20;

    private readonly WorldManager _worldManager;
    private readonly ILogSink _log;

    public FrooxEngineCursorBridge(Engine engine, ILogSink log)
    {
        ArgumentNullException.ThrowIfNull(engine);
        ArgumentNullException.ThrowIfNull(log);

        _worldManager = engine.WorldManager;
        _log = log;
    }

    /// <inheritdoc/>
    public async Task<CursorStateSnapshot> SetPositionAsync(float x, float y, CancellationToken ct)
    {
        var (world, element, target) = await WarpAndLockAsync(x, y, ct).ConfigureAwait(false);

        try
        {
            // lock の WindowPosition 強制は次の Mouse.Update まで効かないため、反映を待つ。
            for (var attempt = 0; attempt < _settlePollMaxAttempts; attempt++)
            {
                var snapshot = await RunOnEngineAsync(() => ReadState(ResolveWorld()), ct)
                    .ConfigureAwait(false);
                if (Matches(snapshot, target))
                {
                    return snapshot;
                }

                await Task.Delay(_settlePollInterval, ct).ConfigureAwait(false);
            }

            // timeout しても現在の実測 state を返す (best-effort)。
            return await RunOnEngineAsync(() => ReadState(ResolveWorld()), ct)
                .ConfigureAwait(false);
        }
        finally
        {
            // settle 確認後 / timeout / cancel のいずれの経路でも、戻る前に必ず lock を
            // 解放してマウスを返す。
            ReleaseLock(world, element);
        }
    }

    /// <inheritdoc/>
    public Task<CursorStateSnapshot> GetPositionAsync(CancellationToken ct) =>
        RunOnEngineAsync(() => ReadState(ResolveWorld()), ct);

    /// <summary>
    /// engine thread 上で目標ピクセルを解決し、OS warp + call-scoped な一時 cursor lock を張る。
    /// </summary>
    /// <remarks>
    /// <see cref="EngineDispatch.RunOnEngineAsync{T}(World, Func{T}, CancellationToken)"/> を
    /// 使わず手で dispatch する: 汎用ヘルパでは <paramref name="ct"/> の cancel が register と
    /// 競合した場合 (queue 済みの engine action は cancel 後もそのまま実行される)、awaiter は
    /// 結果を観測せず <see cref="SetPositionAsync"/> の finally にも入らないため lock が
    /// leak する。ここでは <c>TrySetResult</c> の失敗 (= awaiter が既に cancel 済み) を
    /// engine action 自身が検知し、同一 tick 内で lock を巻き戻すことで「呼び出しが戻る際に
    /// lock が残らない」保証を cancel 経路でも成立させる。TCS の生成 option と
    /// <c>TrySet*</c> を使う理由は <see cref="EngineDispatch"/> の remarks と同じ。
    /// </remarks>
    private async Task<(World World, IWorldElement Element, int2 Target)> WarpAndLockAsync(
        float x,
        float y,
        CancellationToken ct
    )
    {
        var tcs = new TaskCompletionSource<(World, IWorldElement, int2)>(
            TaskCreationOptions.RunContinuationsAsynchronously
        );
        ResolveWorld()
            .RunSynchronously(() =>
            {
                try
                {
                    var world = ResolveWorld();
                    var resolution = ResolveResolution(world);
                    var pixel = ToPixel(x, y, resolution);

                    // (a) OS カーソル warp。native では実カーソルが動くので呼び出し後も
                    //     位置が残る。Wine/Proton では injection 非対応で no-op。
                    world.InputInterface.SetMousePosition(in pixel);

                    // (b) 反映確認まで WindowPosition を強制する一時 lock。同一 element の
                    //     二重登録は RegisterCursorLock が例外を投げるため、念のため先に外す
                    //     (UnregisterCursorLock は Dictionary.Remove 相当で未登録でも安全)。
                    IWorldElement element = world.RootSlot;
                    world.Input.UnregisterCursorLock(element);
                    world.Input.RegisterCursorLock(element, pixel, _lockPriority);

                    if (!tcs.TrySetResult((world, element, pixel)))
                    {
                        // awaiter は cancel 済みで SetPositionAsync の finally は走らない。
                        // engine action 自身が同一 tick 内で lock を巻き戻す。
                        TryUnregister(world, element);
                    }
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

    /// <summary>正規化 [0,1] 座標を window ピクセル座標へ変換し、範囲内へクランプする。</summary>
    private static int2 ToPixel(float x, float y, int2 resolution)
    {
        var px = MathX.Clamp((int)MathX.Round(x * resolution.x), 0, resolution.x - 1);
        var py = MathX.Clamp((int)MathX.Round(y * resolution.y), 0, resolution.y - 1);
        return new int2(px, py);
    }

    /// <summary>call-scoped な一時 cursor lock を engine thread 上で best-effort に解放する。</summary>
    /// <remarks>
    /// cancel 経路でも必ず解放するため CancellationToken には依存しない。
    /// <see cref="World.RunSynchronously(System.Action)"/> で次の engine update に queue する
    /// だけで完了は await しない (engine 終了済みで action が実行されない場合も world ごと
    /// 破棄されるため leak は無害)。
    /// </remarks>
    private void ReleaseLock(World world, IWorldElement element)
    {
        try
        {
            world.RunSynchronously(() => TryUnregister(world, element));
        }
        catch (Exception ex)
        {
            _log.LogWarning(
                $"Cursor: failed to queue cursor-lock release: {ex.GetType().Name}: {ex.Message}"
            );
        }
    }

    private void TryUnregister(World world, IWorldElement element)
    {
        try
        {
            world.Input.UnregisterCursorLock(element);
        }
        catch (Exception ex)
        {
            _log.LogWarning(
                $"Cursor: UnregisterCursorLock threw: {ex.GetType().Name}: {ex.Message}"
            );
        }
    }

    /// <summary>現在の正規化カーソル位置と window 解像度を読む。</summary>
    private CursorStateSnapshot ReadState(World world)
    {
        var resolution = ResolveResolution(world);
        var normalized = world.InputInterface.Mouse.NormalizedWindowPosition;
        return new CursorStateSnapshot(normalized.x, normalized.y, resolution.x, resolution.y);
    }

    private static bool Matches(CursorStateSnapshot snapshot, int2 target)
    {
        var px = MathX.Round(snapshot.X * snapshot.WindowWidth);
        var py = MathX.Round(snapshot.Y * snapshot.WindowHeight);
        // ±1px のスラックで判定 (round 境界 + lerp 補間中の 1 フレームずれを吸収)。
        return MathX.Abs(px - target.x) <= 1f && MathX.Abs(py - target.y) <= 1f;
    }

    /// <summary>現在 focus されている world を取得する。未準備なら <see cref="CursorNotReadyException"/>。</summary>
    private World ResolveWorld()
    {
        var world = _worldManager.FocusedWorld;
        if (world is null || world.IsDisposed)
        {
            throw new CursorNotReadyException(
                "No focused world is available yet; engine still initializing."
            );
        }
        return world;
    }

    /// <summary>window 解像度を取得する。未準備 (0 以下) なら <see cref="CursorNotReadyException"/>。</summary>
    private static int2 ResolveResolution(World world)
    {
        var resolution = world.InputInterface.WindowResolution;
        if (resolution.x <= 0 || resolution.y <= 0)
        {
            throw new CursorNotReadyException(
                "Window resolution is not available yet; engine still initializing."
            );
        }
        return resolution;
    }

    /// <summary>engine thread に <paramref name="fn"/> を marshal し結果を await する one-shot ヘルパ。</summary>
    private Task<T> RunOnEngineAsync<T>(Func<T> fn, CancellationToken ct) =>
        ResolveWorld().RunOnEngineAsync(fn, ct);
}
