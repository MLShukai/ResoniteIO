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
/// 位置の設定は <see cref="InputBindingManager.RegisterCursorLock"/> による
/// <b>cursor lock</b> で行う。<c>Mouse.Update</c> は <c>CursorLockPosition</c> が
/// セットされていると毎フレーム <c>WindowPosition</c> をそこへ強制する
/// (decompiled/.../Mouse.cs:67-71)。OS レベルのマウス injection
/// (<c>InputInterface.SetMousePosition</c>) は Wine/Proton で反映されるか不確実なため使わず、
/// engine 内で完結する cursor lock を採用する。lock は「カーソルをその位置に保持する」
/// 副作用を持つが、これは desktop で context menu を開いたまま視点移動で自動クローズ
/// させる (exit-lerp の arming) ために必要な性質でもある。
/// </para>
/// <para>
/// lock は world ごとに 1 つ、<see cref="World.RootSlot"/> を element key として登録し、
/// 以降の <see cref="SetPositionAsync"/> では <see cref="CursorLock.position"/> を
/// 上書きする。world 切替時は旧 lock を unregister して新 world に張り直す。
/// <see cref="Dispose"/> で best-effort に unregister する (engine 終了時は world ごと
/// 破棄されるため leak は無害)。
/// </para>
/// </remarks>
internal sealed class FrooxEngineCursorBridge : ICursorBridge, IDisposable
{
    // 他の locker (mouse-look 等) に勝てるよう高い priority を使う。
    // LockCursor getter は priority 最大の locker の position を採用する。
    private const int _lockPriority = 1_000_000;

    // lock 反映 (= 次フレームの Mouse.Update) を待つポーリング: ~320ms 相当。
    private static readonly TimeSpan _settlePollInterval = TimeSpan.FromMilliseconds(16);
    private const int _settlePollMaxAttempts = 20;

    private readonly WorldManager _worldManager;
    private readonly ILogSink _log;

    private readonly object _lock = new();
    private World? _lockedWorld;
    private IWorldElement? _lockElement;
    private CursorLock? _cursorLock;
    private bool _disposed;

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
        // engine thread 上で目標ピクセルを解決し cursor lock を張る / 更新する。
        var target = await RunOnEngineAsync(
                () =>
                {
                    var world = ResolveWorld();
                    var resolution = ResolveResolution(world);
                    var pixel = ToPixel(x, y, resolution);
                    ApplyLock(world, pixel);
                    return pixel;
                },
                ct
            )
            .ConfigureAwait(false);

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
        return await RunOnEngineAsync(() => ReadState(ResolveWorld()), ct).ConfigureAwait(false);
    }

    /// <inheritdoc/>
    public Task<CursorStateSnapshot> GetPositionAsync(CancellationToken ct) =>
        RunOnEngineAsync(() => ReadState(ResolveWorld()), ct);

    /// <summary>正規化 [0,1] 座標を window ピクセル座標へ変換し、範囲内へクランプする。</summary>
    private static int2 ToPixel(float x, float y, int2 resolution)
    {
        var px = MathX.Clamp((int)MathX.Round(x * resolution.x), 0, resolution.x - 1);
        var py = MathX.Clamp((int)MathX.Round(y * resolution.y), 0, resolution.y - 1);
        return new int2(px, py);
    }

    /// <summary>engine thread 上で world の cursor lock を張る / 位置を更新する。</summary>
    private void ApplyLock(World world, int2 pixel)
    {
        lock (_lock)
        {
            if (_disposed)
            {
                return;
            }

            // world が切り替わっていたら旧 lock を畳む。
            if (_lockedWorld is not null && !ReferenceEquals(_lockedWorld, world))
            {
                TryUnregister(_lockedWorld, _lockElement);
                _lockedWorld = null;
                _lockElement = null;
                _cursorLock = null;
            }

            if (_cursorLock is not null && ReferenceEquals(_lockedWorld, world))
            {
                _cursorLock.position = pixel;
                return;
            }

            var element = world.RootSlot;
            // 同一 element の二重登録は RegisterCursorLock が例外を投げるため、念のため先に外す。
            world.Input.UnregisterCursorLock(element);
            _cursorLock = world.Input.RegisterCursorLock(element, pixel, _lockPriority);
            _lockedWorld = world;
            _lockElement = element;
        }
    }

    private void TryUnregister(World world, IWorldElement? element)
    {
        if (element is null)
        {
            return;
        }
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
    private async Task<T> RunOnEngineAsync<T>(Func<T> fn, CancellationToken ct)
    {
        var world = ResolveWorld();
        var tcs = new TaskCompletionSource<T>();
        world.RunSynchronously(() =>
        {
            try
            {
                tcs.SetResult(fn());
            }
            catch (Exception e)
            {
                tcs.SetException(e);
            }
        });
        using (ct.Register(() => tcs.TrySetCanceled(ct)))
        {
            return await tcs.Task.ConfigureAwait(false);
        }
    }

    public void Dispose()
    {
        World? world;
        IWorldElement? element;
        lock (_lock)
        {
            if (_disposed)
            {
                return;
            }
            _disposed = true;
            world = _lockedWorld;
            element = _lockElement;
            _lockedWorld = null;
            _lockElement = null;
            _cursorLock = null;
        }

        if (world is null || element is null || world.IsDisposed)
        {
            return;
        }

        // dictionary 変更は engine thread 上で行う (Update の読みと race させない)。
        // engine 終了済みなら action は実行されないが world ごと破棄されるため leak は無害。
        try
        {
            world.RunSynchronously(() => TryUnregister(world, element));
        }
        catch (Exception ex)
        {
            try
            {
                _log.LogWarning(
                    $"Cursor.Dispose: RunSynchronously threw: {ex.GetType().Name}: {ex.Message}"
                );
            }
            catch
            {
                // log path may be dead during ProcessExit
            }
        }
    }
}
