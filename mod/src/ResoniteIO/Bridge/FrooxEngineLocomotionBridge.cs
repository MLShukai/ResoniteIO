using System;
using Elements.Core;
using FrooxEngine;
using HarmonyLib;
using ResoniteIO.Core.Locomotion;
using ResoniteIO.Core.Logging;

namespace ResoniteIO.Bridge;

/// <summary>
/// <see cref="ILocomotionBridge"/> の FrooxEngine 実装 (stateful repeater)。
/// </summary>
/// <remarks>
/// <para>
/// <see cref="SetState"/> / <see cref="Reset"/> は任意スレッドから内部 state を
/// 更新するのみ。engine への適用は <see cref="TickStep"/> が
/// <c>World.RunInUpdates(0, TickStep)</c> で self-rescheduling し engine update
/// tick 上で行う。move / jump / crouch は ExternalInput への再注入
/// (engine 1-frame 寿命 ExternalInput と client 送信レートのギャップを吸収)、
/// look (yaw / pitch) は <c>FirstPersonTargettingController</c> の
/// <c>_horizontalAngle</c> / <c>_verticalAngle</c> を <c>rate * Time.Delta</c> で
/// 直接積分する。look の ExternalInput 経路は
/// <c>ScreenCameraInputs.Look.Active = InputInterface.IsCursorLocked</c> で gate
/// され OS window focus 必須のため採らない (直接駆動で focus 非依存に look が
/// 効く)。設計の詳細は <c>memory/feedback_locomotion_external_input.md</c>。
/// </para>
/// <para>
/// thread safety: 単一の <see cref="_lock"/> が <see cref="_latest"/> /
/// <see cref="_jumpPending"/> / <see cref="_pendingResetFlags"/> /
/// <see cref="_cachedWorld"/> / <see cref="_repeaterWorld"/> /
/// <see cref="_repeaterRunning"/> をまとめて守る。contention は無く
/// (任意スレッド SetState / Reset / WorldFocused / engine thread TickStep
/// は事実上 serial)、deadlock-free reasoning を簡素化するため単一 lock。
/// engine への dispatch (<c>RunInUpdates</c>) は lock 外で実行する。
/// </para>
/// <para>
/// World 切替時は <see cref="OnWorldFocused"/> が新 world に re-bind し、旧
/// repeater は次 <see cref="TickStep"/> 内で bind 不一致を検知して
/// self-terminate する (二重 running は 1 tick で収束)。
/// </para>
/// </remarks>
internal sealed class FrooxEngineLocomotionBridge : ILocomotionBridge, IDisposable
{
    // typed delegate は static field で 1 度だけ解決 (TickStep が毎 tick 利用)。
    // 引数順は (declaring type, field type)、逆順は silently wrong delegate を
    // 返すため要 review (feedback_locomotion_external_input.md §3)。
    private static readonly AccessTools.FieldRef<
        SmoothLocomotionBase,
        SmoothLocomotionInputs
    > _smoothNormalInputRef = AccessTools.FieldRefAccess<
        SmoothLocomotionBase,
        SmoothLocomotionInputs
    >("_normalInput");

    private static readonly AccessTools.FieldRef<
        FirstPersonTargettingController,
        float
    > _fpcHorizontalAngleRef = AccessTools.FieldRefAccess<FirstPersonTargettingController, float>(
        "_horizontalAngle"
    );

    private static readonly AccessTools.FieldRef<
        FirstPersonTargettingController,
        float
    > _fpcVerticalAngleRef = AccessTools.FieldRefAccess<FirstPersonTargettingController, float>(
        "_verticalAngle"
    );

    private static readonly AccessTools.FieldRef<HeadSimulator, HeadInputs> _headInputsRef =
        AccessTools.FieldRefAccess<HeadSimulator, HeadInputs>("_inputs");

    private readonly WorldManager _worldManager;
    private readonly ILogSink _log;

    private readonly object _lock = new();
    private LocomotionInput _latest;
    private bool _jumpPending;
    private LocomotionResetFlags _pendingResetFlags;
    private World? _cachedWorld;
    private World? _repeaterWorld;
    private bool _repeaterRunning;

    private volatile bool _disposed;

    public FrooxEngineLocomotionBridge(Engine engine, ILogSink log)
    {
        ArgumentNullException.ThrowIfNull(engine);
        ArgumentNullException.ThrowIfNull(log);

        _worldManager = engine.WorldManager;
        _log = log;
        _latest = LocomotionInput.Neutral;

        // WorldFocused は新規 focus でしか発火しないため、subscribe 前の初期
        // snapshot で起動時の窓を埋める (FrooxEngineConnectionBridge と同じ pattern)。
        var initial = _worldManager.FocusedWorld;
        _cachedWorld = initial;
        _worldManager.WorldFocused += OnWorldFocused;

        if (initial is not null && !initial.IsDisposed)
        {
            EnsureRepeaterStarted(initial);
        }
    }

    /// <inheritdoc/>
    public void SetState(LocomotionPartialInput delta)
    {
        if (_disposed)
        {
            return;
        }

        // WorldFocused より前に Drive が来るケース (mod 起動直後) を救うため、
        // 同 lock 内で running 判定 + cachedWorld snapshot まで済ませる。
        World? worldToStart;
        lock (_lock)
        {
            // present field のみを保持 state にマージ (未設定は前回値を保持)。
            _latest = delta.MergeInto(_latest);
            // jump が present かつ true の rising edge だけが latch を立てる
            // (None/false は既存 pending を取り消さない)。consume-once 化は
            // TickStep 側で行う。
            if (delta.Jump == true)
            {
                _jumpPending = true;
            }

            worldToStart = _repeaterRunning ? null : _cachedWorld;
        }

        if (worldToStart is not null && !worldToStart.IsDisposed)
        {
            EnsureRepeaterStarted(worldToStart);
        }
    }

    /// <inheritdoc/>
    public void Reset(LocomotionResetFlags flags)
    {
        if (_disposed || flags == LocomotionResetFlags.None)
        {
            return;
        }

        lock (_lock)
        {
            // pending として蓄積するだけ。実 reset 適用は TickStep (engine thread) で
            // 行い、_latest と ExternalInput の書き込みを 1 スレッドに閉じる。
            _pendingResetFlags |= flags;
        }
    }

    /// <inheritdoc/>
    public void NotifyDisconnect(LocomotionDisconnectReason reason)
    {
        if (_disposed)
        {
            return;
        }

        _log.LogDebug($"LocomotionBridge: Drive stream disconnect reason={reason}");

        // 将来 reason ごとに別経路 (e.g. Errored で log level を上げる、Cancelled
        // のみ全 reset ではなく Move/Look だけ reset など) を分岐させる余地を
        // switch で確保。現状は graceful 維持 / それ以外で safety reset の 2 つ。
        switch (reason)
        {
            case LocomotionDisconnectReason.Graceful:
                // 正常終了は state 維持。
                break;
            case LocomotionDisconnectReason.Cancelled:
            case LocomotionDisconnectReason.Errored:
                Reset(LocomotionResetFlags.All);
                break;
        }
    }

    private void OnWorldFocused(World world)
    {
        if (_disposed)
        {
            return;
        }

        bool restartNeeded = false;
        lock (_lock)
        {
            _cachedWorld = world;
            // 旧 world bind の repeater は次 TickStep 内で bind 不一致を検知して
            // self-terminate するので、ここでは running を下ろして新 world で
            // 再 bind する。
            if (world is not null && !ReferenceEquals(_repeaterWorld, world))
            {
                _repeaterRunning = false;
                _repeaterWorld = null;
                restartNeeded = true;
            }
        }

        _log.LogDebug($"LocomotionBridge: world refocused → {world?.Name ?? "<null>"}");

        if (restartNeeded && world is not null && !world.IsDisposed)
        {
            EnsureRepeaterStarted(world);
        }
    }

    /// <summary>指定 world に repeater を 1 回だけ schedule する (二重起動防止)。</summary>
    private void EnsureRepeaterStarted(World world)
    {
        ArgumentNullException.ThrowIfNull(world);

        bool start = false;
        lock (_lock)
        {
            if (_disposed)
            {
                return;
            }

            if (!_repeaterRunning)
            {
                _repeaterWorld = world;
                _repeaterRunning = true;
                start = true;
            }
        }

        if (start)
        {
            try
            {
                world.RunInUpdates(0, TickStep);
            }
            catch (Exception ex)
            {
                // running を戻して次回 SetState で再試行できるようにする。
                _log.LogWarning($"LocomotionBridge: failed to schedule TickStep: {ex.Message}");
                lock (_lock)
                {
                    _repeaterRunning = false;
                    _repeaterWorld = null;
                }
            }
        }
    }

    /// <summary>
    /// engine update tick 上で 1 度実行され、末尾で次 tick へ自己 schedule する
    /// repeater 本体。disposed / world dispose / bind 不一致で self-terminate。
    /// </summary>
    private void TickStep()
    {
        if (_disposed)
        {
            MarkRepeaterStopped(expected: null);
            return;
        }

        // bind 確認 + pending reset 消化 + state snapshot を 1 lock 内で行う。
        // OnWorldFocused が _repeaterWorld を差し替えていたら旧 world 用として
        // self-terminate する (新 world 用は OnWorldFocused が別途 schedule 済み)。
        World? boundWorld;
        LocomotionInput snapshot;
        bool jumpSnapshot;
        lock (_lock)
        {
            boundWorld = _repeaterWorld;
            if (boundWorld is null)
            {
                _repeaterRunning = false;
                _repeaterWorld = null;
                return;
            }

            var resetFlags = _pendingResetFlags;
            _pendingResetFlags = LocomotionResetFlags.None;

            _latest = _latest.ApplyReset(resetFlags);
            if (resetFlags.HasFlag(LocomotionResetFlags.Jump))
            {
                _jumpPending = false;
            }

            snapshot = _latest;
            jumpSnapshot = _jumpPending;
            _jumpPending = false;
        }

        if (boundWorld.IsDisposed)
        {
            MarkRepeaterStopped(expected: boundWorld);
            return;
        }

        // precondition NG なら今 tick の write を skip。jump pulse は次 tick で
        // 再 apply できるよう latch を戻す (CLI から見た pulse 消失を防ぐ)。
        // ApplyToEngine 失敗時の reapply は OR-merge で _jumpPending = true を戻す。
        // 直前に SetState(Jump=true) が来た場合は lock 内で再 latch されるため過小
        // 消費にはならない。最悪、次 tick で 1 frame 早く pulse が出る race は許容
        // (consume は engine 適用成功時のみ確定)。
        var (loco, fpc, head) = ResolveComponents(boundWorld);
        if (loco?.ActiveModule is SmoothLocomotionBase smooth)
        {
            ApplyToEngine(smooth, fpc, head, snapshot, jumpSnapshot);
        }
        else if (jumpSnapshot)
        {
            lock (_lock)
            {
                _jumpPending = true;
            }
        }

        if (_disposed || boundWorld.IsDisposed)
        {
            MarkRepeaterStopped(expected: boundWorld);
            return;
        }

        try
        {
            boundWorld.RunInUpdates(0, TickStep);
        }
        catch (Exception ex)
        {
            _log.LogWarning($"LocomotionBridge: TickStep reschedule failed: {ex.Message}");
            MarkRepeaterStopped(expected: boundWorld);
        }
    }

    private void ApplyToEngine(
        SmoothLocomotionBase smooth,
        FirstPersonTargettingController? fpc,
        HeadSimulator? head,
        LocomotionInput snapshot,
        bool jumpSnapshot
    )
    {
        var normalInput = _smoothNormalInputRef(smooth);
        if (normalInput is null || normalInput.Move is null || normalInput.Jump is null)
        {
            return;
        }

        // Move は Slot-local。WASD binding と同じく LocalUserViewRotation を
        // 経由して body-local に変換する (HFR / GlobalRotation を採らない理由・
        // pitch sink が実害無しの根拠・定量検証は
        // feedback_locomotion_external_input.md §8)。userRoot / World 未準備時は
        // skip し repeater 次 tick で再評価。
        var userRoot = smooth.Slot.ActiveUserRoot;
        var world = userRoot?.World;
        if (userRoot is not null && world is not null)
        {
            var viewRot = world.LocalUserViewRotation;
            var worldForward = viewRot * float3.Forward;
            var worldRight = viewRot * float3.Right;
            // move_up は view-rotation を掛けない絶対 world-up。fwd/right と違い
            // 視点 pitch から独立させるため float3.Up を直接使い、Move が Slot-local
            // なので slot-local に変換してから合成する。モード差は Bridge では分岐せず
            // engine の active module が解釈する (Walk は Move を `.x_z` 射影して垂直
            // 成分を破棄 → move_up は無視され歩行を乱さない、NoClip/fly は 3 成分を
            // そのまま使い上下移動になる)。よって Bridge は 1 ベクトルを書くだけでよい。
            var worldUp = float3.Up;
            var slotForward = userRoot.Slot.GlobalDirectionToLocal(in worldForward);
            var slotRight = userRoot.Slot.GlobalDirectionToLocal(in worldRight);
            var slotUp = userRoot.Slot.GlobalDirectionToLocal(in worldUp);

            var slotMove =
                snapshot.MoveRight * slotRight
                + snapshot.MoveForward * slotForward
                + snapshot.MoveUp * slotUp;
            normalInput.Move.ExternalInput = slotMove * snapshot.Velocity;
        }

        if (jumpSnapshot)
        {
            // DigitalAction.ExternalInput は OR-merge なので false は明示不要。
            normalInput.Jump.ExternalInput = true;
        }

        // look は ExternalInput を使わず _horizontalAngle / _verticalAngle を直接
        // 積分する。Look ExternalInput 経路は Look.Active = IsCursorLocked
        // (OS window focus 必須) で gate され、非フォーカス / headless で原理的に
        // 効かないため gate ごとバイパスする。符号は engine OnBeforeHeadUpdate の
        // `_horizontalAngle += x` / `_verticalAngle -= y` と同形 (実機検証済みの
        // UP=見上げを保つ、feedback_locomotion_external_input.md §2)。clamp は
        // engine が毎 frame MathX.Clamp(±89°) するため不要。rate=0 は no-op。
        if (fpc is not null && !fpc.IsRemoved)
        {
            var dt = fpc.Time.Delta;
            _fpcHorizontalAngleRef(fpc) += snapshot.YawRate * dt;
            _fpcVerticalAngleRef(fpc) -= snapshot.PitchRate * dt;
        }

        // crouch は値 0 でも書く (engine の += 0 は副作用なし、idle 戻し兼用)。
        if (head is not null)
        {
            var headInputs = _headInputsRef(head);
            if (headInputs?.Crouch is not null)
            {
                headInputs.Crouch.ExternalInput = snapshot.Crouch;
            }
        }
    }

    private static (
        LocomotionController? Loco,
        FirstPersonTargettingController? Fpc,
        HeadSimulator? Head
    ) ResolveComponents(World world)
    {
        var userRoot = world.LocalUser?.Root;
        if (userRoot is null)
        {
            return (null, null, null);
        }

        var loco = userRoot.Slot.GetComponentInChildren<LocomotionController>();

        var screen = userRoot.ScreenController.Target;
        // ActiveTargetting が他の controller のときは Slot 配下から fallback 探索。
        var fpc = screen?.ActiveTargetting.Target as FirstPersonTargettingController;
        if (fpc is null)
        {
            fpc = userRoot.Slot.GetComponentInChildren<FirstPersonTargettingController>();
        }

        // ScreenController 未初期化 → Head は null。ApplyToEngine が silent skip する。
        var head = screen?.Head.Target;

        return (loco, fpc, head);
    }

    private void MarkRepeaterStopped(World? expected)
    {
        lock (_lock)
        {
            if (expected is null || ReferenceEquals(_repeaterWorld, expected))
            {
                _repeaterRunning = false;
                _repeaterWorld = null;
            }
        }
    }

    public void Dispose()
    {
        if (_disposed)
        {
            return;
        }
        _disposed = true;

        try
        {
            _worldManager.WorldFocused -= OnWorldFocused;
        }
        catch
        {
            // engine 側が先に破棄されているケースの best-effort。
        }

        // schedule 済みの TickStep は次回 head で _disposed=true を見て self-terminate。
        lock (_lock)
        {
            _repeaterRunning = false;
            _repeaterWorld = null;
            _cachedWorld = null;
        }

        _log.LogInfo("Locomotion Bridge disposed: state cleared, repeater stopped");
    }
}
