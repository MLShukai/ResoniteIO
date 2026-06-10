using System;
using System.Collections.Generic;
using System.Reflection;
using System.Threading;
using System.Threading.Tasks;
using Elements.Core;
using FrooxEngine;
using HarmonyLib;
using Renderite.Shared;
using ResoniteIO.Core.Cursor;
using ResoniteIO.Core.Logging;

namespace ResoniteIO.Bridge;

/// <summary>FrooxEngine の desktop カーソル位置を操作する <see cref="ICursorBridge"/> 実装。</summary>
/// <remarks>
/// <para>
/// 全操作は <see cref="World.RunSynchronously(System.Action)"/> で engine thread に
/// marshal する (<see cref="EngineDispatch.RunOnEngineAsync{T}(World, Func{T}, CancellationToken)"/>)。
/// </para>
/// <para>
/// 位置の設定は「<b>register → settle → 保持</b>」: <see cref="SetPositionAsync"/> は
/// <see cref="InputBindingManager.RegisterCursorLock"/> による cursor lock で
/// <c>Mouse.WindowPosition</c> を強制し (<c>Mouse.Update</c> は <c>CursorLockPosition</c> が
/// セットされていると毎フレーム <c>WindowPosition</c> をそこへ上書きする。
/// decompiled/.../Mouse.cs:67-71)、反映 (settle) を確認した後も lock を解放せず
/// <see cref="ReleaseAsync"/> まで保持する。保持中の再 set は
/// <see cref="CursorLock.position"/> の直接書き換えで次フレーム反映される (re-register
/// 不要。decompiled/.../InputBindingManager.cs:182-192)。OS カーソル warp
/// (<c>InputInterface.SetMousePosition</c>) は行わない — OS ポインタには一切触れない契約。
/// </para>
/// <para>
/// OS ポインタを奪わないために <see cref="InputInterface"/>.<c>CollectOutputState</c> へ
/// Harmony Postfix を張り、自分の lock だけが効いている場合に renderer へ渡る
/// <see cref="OutputState.lockCursorPosition"/> を null 化し、かつ
/// <see cref="OutputState.lockCursor"/> を「自 lock が存在しなかった世界線」の値に
/// 再計算する。position だけ null 化すると renderer 側 <c>MouseDriver.HandleStateUpdate</c>
/// が <c>CursorLockMode.Locked</c> (中央 pin) に落ちるため、両 field の偽装が必須
/// (decompiled Assembly-CSharp/MouseDriver.cs:62-100)。再計算に必要な
/// <c>InputBindingManager._cursorUnlockers</c> / <c>_cursorLockers</c> は private のため
/// <see cref="AccessTools.FieldRefAccess"/> で読む (解決失敗時は patch を適用せず
/// SetPosition / Release を fail-loud で拒否する — 黙って OS ポインタを奪う退行を防ぐ)。
/// </para>
/// <para>
/// lock は focused world の <see cref="InputBindingManager"/> 単位なので、world の focus が
/// 移ると engine 側で不活性になる。bridge は lock を自動マイグレーションせず
/// <c>Held = false</c> と報告する。<c>IsRemoved</c> な locker は engine が毎フレーム自動
/// prune するため、world dispose 後の stale 参照は無害。
/// </para>
/// </remarks>
internal sealed class FrooxEngineCursorBridge : ICursorBridge, IDisposable
{
    private const string HarmonyId = "net.mlshukai.resonite-io.cursor";

    // 他の locker (mouse-look 等) に勝てるよう高い priority を使う。
    // LockCursor getter は priority 最大の locker の position を採用する。
    private const int _lockPriority = 1_000_000;

    // lock 反映 (= 次フレームの Mouse.Update) を待つポーリング: ~320ms 相当。
    private static readonly TimeSpan _settlePollInterval = TimeSpan.FromMilliseconds(16);
    private const int _settlePollMaxAttempts = 20;

    /// <summary>
    /// Harmony Postfix (static 制約) から dispatch するために単一 instance を保持する。
    /// 二重 ctor は <see cref="InvalidOperationException"/>。
    /// </summary>
    private static FrooxEngineCursorBridge? _singleton;

    // InputBindingManager の private field への FieldRef。解決は最初の ctor で 1 回だけ
    // 行い static に cache する (失敗時は null のまま = 保持機能 degrade)。
    private static bool _reflectionAttempted;
    private static AccessTools.FieldRef<
        InputBindingManager,
        HashSet<IWorldElement>
    >? _cursorUnlockersRef;
    private static AccessTools.FieldRef<
        InputBindingManager,
        Dictionary<IWorldElement, CursorLock>
    >? _cursorLockersRef;

    private readonly WorldManager _worldManager;
    private readonly ILogSink _log;
    private readonly Harmony _harmony;

    // 保持状態。書き込みは engine thread 上のみ。_held は Harmony Postfix
    // (engine input 経路のスレッド) から read されるため volatile。
    private World? _lockWorld;
    private CursorLock? _lock;
    private volatile bool _held;

    // reflection / patch が揃い保持機能が使えるか。ctor で成功時に true、
    // Dispose (UnpatchSelf 後) で false に戻す。
    private bool _patched;

    private int _disposed;

    public FrooxEngineCursorBridge(Engine engine, ILogSink log)
    {
        ArgumentNullException.ThrowIfNull(engine);
        ArgumentNullException.ThrowIfNull(log);

        if (Interlocked.CompareExchange(ref _singleton, this, null) is not null)
        {
            throw new InvalidOperationException(
                "FrooxEngineCursorBridge: another instance is already alive."
            );
        }

        _worldManager = engine.WorldManager;
        _log = log;
        _harmony = new Harmony(HarmonyId);

        if (!ResolveReflection(log))
        {
            _log.LogError(
                "Cursor Bridge: cursor hold unavailable: engine internals changed "
                    + "(_cursorUnlockers not found). SetPosition/Release will fail with "
                    + "FailedPrecondition; GetPosition remains available."
            );
            return;
        }

        ApplyPatch();
    }

    /// <inheritdoc/>
    public async Task<CursorStateSnapshot> SetPositionAsync(float x, float y, CancellationToken ct)
    {
        EnsureHoldAvailable();

        var target = await RunOnEngineAsync(() => ApplyHold(x, y), ct).ConfigureAwait(false);

        // lock の WindowPosition 強制は次の Mouse.Update まで効かないため、反映を待つ。
        // cancel は待ちを打ち切るだけで保持は解除しない (client は必要なら Release を呼ぶ)。
        for (var attempt = 0; attempt < _settlePollMaxAttempts; attempt++)
        {
            var snapshot = await ReadStateAsync(ct).ConfigureAwait(false);
            if (Matches(snapshot, target))
            {
                return snapshot;
            }

            await Task.Delay(_settlePollInterval, ct).ConfigureAwait(false);
        }

        // timeout しても現在の実測 state を返す (best-effort)。保持は継続する。
        return await ReadStateAsync(ct).ConfigureAwait(false);
    }

    /// <inheritdoc/>
    public Task<CursorStateSnapshot> GetPositionAsync(CancellationToken ct) => ReadStateAsync(ct);

    /// <inheritdoc/>
    public Task<CursorStateSnapshot> ReleaseAsync(CancellationToken ct)
    {
        EnsureHoldAvailable();

        return RunOnEngineAsync(
            () =>
            {
                if (_held || _lock is not null || _lockWorld is not null)
                {
                    // Postfix への偽装を先に遮断してから lock を外す。
                    _held = false;
                    var lockWorld = _lockWorld;
                    if (lockWorld is not null && !lockWorld.IsDisposed)
                    {
                        TryUnregister(lockWorld);
                    }
                    _lock = null;
                    _lockWorld = null;
                }

                // 未保持なら read のみ (冪等)。
                return ReadState(ResolveWorld());
            },
            ct
        );
    }

    /// <summary>
    /// engine thread 上で目標ピクセルを解決し、保持 lock を register / 更新する。
    /// </summary>
    /// <remarks>
    /// engine thread への marshal により呼び出しは直列化されるため、並行 SetPosition は
    /// 後勝ち (last-wins) になり追加の排他は不要。
    /// </remarks>
    private int2 ApplyHold(float x, float y)
    {
        var world = ResolveWorld();
        var resolution = ResolveResolution(world);
        var pixel = ToPixel(x, y, resolution);

        if (_held && _lock is not null && ReferenceEquals(_lockWorld, world))
        {
            // 同一 world で保持中: position の直接書き換えのみで次フレーム反映される。
            _lock.position = pixel;
            return pixel;
        }

        if (!ReferenceEquals(_lockWorld, world))
        {
            // world 切替後: 旧 world の lock を best-effort 解除 (完了は await しない)。
            QueueUnregister(_lockWorld, "stale cursor-lock release");
        }

        // 同一 element の二重登録は RegisterCursorLock が例外を投げるため、念のため先に
        // 外す (UnregisterCursorLock は Dictionary.Remove 相当で未登録でも安全)。
        IWorldElement element = world.RootSlot;
        world.Input.UnregisterCursorLock(element);
        var cursorLock = world.Input.RegisterCursorLock(element, pixel, _lockPriority);
        // decompiled の RegisterCursorLock は priority 引数を CursorLock に反映しない
        // (position のみ設定) ため、public field へ明示的に書き込む。
        cursorLock.priority = _lockPriority;

        _lock = cursorLock;
        _lockWorld = world;
        _held = true;
        return pixel;
    }

    /// <summary>正規化 [0,1] 座標を window ピクセル座標へ変換し、範囲内へクランプする。</summary>
    private static int2 ToPixel(float x, float y, int2 resolution)
    {
        var px = MathX.Clamp((int)MathX.Round(x * resolution.x), 0, resolution.x - 1);
        var py = MathX.Clamp((int)MathX.Round(y * resolution.y), 0, resolution.y - 1);
        return new int2(px, py);
    }

    /// <summary>
    /// <paramref name="world"/> の engine thread へ保持 lock 解除を best-effort で queue する
    /// (完了は await しない)。null / disposed なら no-op、queue 失敗は warning に握る。
    /// </summary>
    private void QueueUnregister(World? world, string failureContext)
    {
        if (world is null || world.IsDisposed)
        {
            return;
        }

        try
        {
            world.RunSynchronously(() => TryUnregister(world));
        }
        catch (Exception ex)
        {
            _log.LogWarning(
                $"Cursor: failed to queue {failureContext}: {ex.GetType().Name}: {ex.Message}"
            );
        }
    }

    /// <summary>保持 lock を engine thread 上で best-effort に解除する。例外は warning に握る。</summary>
    private void TryUnregister(World world)
    {
        try
        {
            world.Input.UnregisterCursorLock(world.RootSlot);
        }
        catch (Exception ex)
        {
            _log.LogWarning(
                $"Cursor: UnregisterCursorLock threw: {ex.GetType().Name}: {ex.Message}"
            );
        }
    }

    /// <summary>現在の正規化カーソル位置・window 解像度・保持状態を読む (engine thread 上)。</summary>
    /// <remarks>
    /// Held は「<c>_held</c> かつ <c>_lockWorld</c> が生存 かつ <c>_lockWorld</c> == 現在の
    /// focused world (参照同一)」。world 切替で focus が移ると lock は engine 側で不活性に
    /// なるため、この規則で <c>held=false</c> を報告して観測と一致させる。
    /// </remarks>
    private CursorStateSnapshot ReadState(World world)
    {
        var resolution = ResolveResolution(world);
        var normalized = world.InputInterface.Mouse.NormalizedWindowPosition;
        var held =
            _held && _lockWorld is { IsDisposed: false } && ReferenceEquals(_lockWorld, world);
        return new CursorStateSnapshot(
            normalized.x,
            normalized.y,
            resolution.x,
            resolution.y,
            held
        );
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

    /// <summary>
    /// 保持機構 (reflection + Harmony patch) が利用可能か検証する。不能なら
    /// <see cref="CursorNotReadyException"/> (→ FailedPrecondition) で fail-loud。
    /// </summary>
    private void EnsureHoldAvailable()
    {
        if (!_patched)
        {
            throw new CursorNotReadyException(
                "cursor hold unavailable: engine internals changed; "
                    + "SetPosition/Release are disabled to avoid grabbing the OS pointer."
            );
        }
    }

    /// <summary>engine thread に <paramref name="fn"/> を marshal し結果を await する one-shot ヘルパ。</summary>
    private Task<T> RunOnEngineAsync<T>(Func<T> fn, CancellationToken ct) =>
        ResolveWorld().RunOnEngineAsync(fn, ct);

    /// <summary>focused world の engine thread 上で <see cref="ReadState"/> を評価する。</summary>
    private Task<CursorStateSnapshot> ReadStateAsync(CancellationToken ct) =>
        RunOnEngineAsync(() => ReadState(ResolveWorld()), ct);

    private static bool ResolveReflection(ILogSink log)
    {
        if (!_reflectionAttempted)
        {
            _reflectionAttempted = true;
            try
            {
                _cursorUnlockersRef = AccessTools.FieldRefAccess<
                    InputBindingManager,
                    HashSet<IWorldElement>
                >("_cursorUnlockers");
                _cursorLockersRef = AccessTools.FieldRefAccess<
                    InputBindingManager,
                    Dictionary<IWorldElement, CursorLock>
                >("_cursorLockers");
            }
            catch (Exception ex)
            {
                log.LogWarning(
                    "Cursor Bridge: InputBindingManager FieldRefAccess resolution failed: "
                        + $"{ex.GetType().Name}: {ex.Message}"
                );
                _cursorUnlockersRef = null;
                _cursorLockersRef = null;
            }
        }

        return _cursorUnlockersRef is not null && _cursorLockersRef is not null;
    }

    private void ApplyPatch()
    {
        var original = AccessTools.Method(typeof(InputInterface), "CollectOutputState");
        if (original is null)
        {
            _log.LogError(
                "Cursor Bridge: cursor hold unavailable: InputInterface.CollectOutputState "
                    + "not found; SetPosition/Release will fail with FailedPrecondition."
            );
            return;
        }

        var postfix = new HarmonyMethod(
            typeof(FrooxEngineCursorBridge).GetMethod(
                nameof(OnCollectOutputStatePostfix),
                BindingFlags.NonPublic | BindingFlags.Static
            )
        );

        try
        {
            _harmony.Patch(original, postfix: postfix);
            _patched = true;
            _log.LogInfo(
                "Cursor Bridge: HarmonyLib Postfix attached to InputInterface.CollectOutputState"
            );
        }
        catch (Exception ex)
        {
            // 偽装できない lock を張ると OS ポインタを奪う旧問題が再発するため、
            // patch 失敗時も保持機能ごと degrade させる。
            _log.LogError($"Cursor Bridge: failed to apply Harmony patch: {ex}");
        }
    }

    /// <summary>
    /// HarmonyLib によって <see cref="InputInterface"/>.<c>CollectOutputState</c> の直後に
    /// 呼ばれる static postfix。renderer へ渡る <see cref="OutputState"/> の
    /// <c>lockCursor</c> / <c>lockCursorPosition</c> を「自 lock が存在しなかった世界線」へ
    /// 偽装する。
    /// </summary>
    /// <remarks>
    /// 毎フレームの hot path。log は出さず、例外はすべて握りつぶす (engine 経路に
    /// 例外を逃がさない)。自分以外の有効な locker (mouse-look 等) が 1 つでも存在する
    /// 場合は何も書き換えない (他者の lock を尊重する)。
    /// </remarks>
    private static void OnCollectOutputStatePostfix(InputInterface __instance, OutputState __result)
    {
        try
        {
            var bridge = _singleton;
            if (bridge is null || !bridge._held)
            {
                return;
            }
            var myLock = bridge._lock;
            if (myLock is null)
            {
                return;
            }
            var lockersRef = _cursorLockersRef;
            var unlockersRef = _cursorUnlockersRef;
            if (lockersRef is null || unlockersRef is null)
            {
                return;
            }

            // InputInterface.Update と同じ対象集合 (Running かつ非 Background) を走査し、
            // (a) 自分以外の有効な locker が居れば即 return、(b) 居なければ「自 lock 抜き」の
            // 世界線で unlocker が成立するかを集める。(decompiled InputInterface.cs:615-632)
            var anyUnlocker = false;
            foreach (var world in bridge._worldManager.Worlds)
            {
                if (
                    world.State != FrooxEngine.World.WorldState.Running
                    || world.Focus == FrooxEngine.World.WorldFocus.Background
                )
                {
                    continue;
                }

                var input = world.Input;
                foreach (var locker in lockersRef(input))
                {
                    if (!ReferenceEquals(locker.Value, myLock) && !locker.Key.IsRemoved)
                    {
                        // 自分以外の lock が生きている — 偽装せず engine ネイティブの
                        // 出力をそのまま renderer へ渡す。
                        return;
                    }
                }

                // 自 lock 抜きの世界線ではこの world の lockers は空なので、
                // UnlockCursor 相当は unlocker の有無だけで決まる
                // (decompiled InputBindingManager.cs:54-64)。
                if (unlockersRef(input).Count > 0)
                {
                    anyUnlocker = true;
                }
            }

            // 自分の lock だけが効いている: position を null 化し、lockCursor を
            // 「lock が 1 つも無い世界線」の式 (InputInterface.cs:627-632) で再計算する。
            __result.lockCursorPosition = null;
            __result.lockCursor = !anyUnlocker && __instance.IsWindowFocused;
        }
        catch (Exception)
        {
            // hot path: engine の input 経路に例外を逃がさない。log も出さない。
        }
    }

    public void Dispose()
    {
        if (Interlocked.Exchange(ref _disposed, 1) != 0)
        {
            return;
        }

        // Postfix への偽装を先に遮断する。
        _held = false;

        QueueUnregister(_lockWorld, "cursor-lock release on dispose");

        if (_patched)
        {
            try
            {
                _harmony.UnpatchSelf();
            }
            catch (Exception ex)
            {
                _log.LogWarning($"Cursor Bridge: Harmony.UnpatchSelf threw: {ex.Message}");
            }
            _patched = false;
        }

        Interlocked.CompareExchange(ref _singleton, null, this);
        _log.LogInfo("Cursor Bridge disposed: harmony unpatched, lock release queued");
    }
}
