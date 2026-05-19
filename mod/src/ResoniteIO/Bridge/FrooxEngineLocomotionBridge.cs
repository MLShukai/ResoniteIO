using System;
using System.Threading;
using System.Threading.Tasks;
using Elements.Core;
using FrooxEngine;
using HarmonyLib;
using ResoniteIO.Core.Bridge;
using ResoniteIO.Core.Logging;

namespace ResoniteIO.Bridge;

/// <summary>
/// <see cref="ILocomotionBridge"/> の FrooxEngine 実装。Python 側から push される
/// <see cref="LocomotionCommand"/> を engine の <c>ExternalInput</c> に流し込み、
/// 既存の collision / smoothing / yaw clamp を再利用してデスクトップ WASD
/// 相当の操作を再現する。
/// </summary>
/// <remarks>
/// <para>
/// 全 <c>InputAction.ExternalInput</c> 書き込みは「nullable 値の単純代入」で、
/// engine 側が次の update tick で消費 + null reset する設計
/// (<see cref="Analog3DAction"/> 等を参照)。書き込み自体は thread-safe なので
/// <c>World.RunSynchronously</c> へのディスパッチは行わず任意スレッドから
/// 直接 set する。これにより client-streaming の 30Hz パケットを engine の
/// per-frame overhead 0 で適用できる。
/// </para>
/// <para>
/// component lookup は <see cref="ResolveComponents"/> で
/// <c>FocusedWorld → LocalUser.Root</c> chain を辿り、<see cref="WorldFocused"/>
/// で cache invalidate する (Camera v2 Bridge と同じ pattern)。
/// </para>
/// <para>
/// engine の private field を読むため <see cref="AccessTools.FieldRefAccess"/>
/// で typed delegate を 1 回だけ生成して保持する。field 名は engine update で
/// silent に壊れうるため、初回 Drive で <see cref="LocomotionNotReadyException"/>
/// になったら decompile を再生成して field 名 diff を確認すること
/// (リスク §1)。
/// </para>
/// </remarks>
internal sealed class FrooxEngineLocomotionBridge : ILocomotionBridge, IDisposable
{
    // ScreenLocomotionDirection.FastMultiplier (decompile) のデフォルト値。
    // proto3 default 0 が来たら本値を使い、>0 が来たらそちらで override する。
    private const float DefaultSprintMultiplier = 2.0f;

    // typed delegate を 1 回だけ生成 (毎フレーム reflection を避ける)。
    private static readonly AccessTools.FieldRef<
        SmoothLocomotionBase,
        SmoothLocomotionInputs
    > _smoothNormalInputRef = AccessTools.FieldRefAccess<
        SmoothLocomotionBase,
        SmoothLocomotionInputs
    >("_normalInput");

    private static readonly AccessTools.FieldRef<
        TargettingControllerBase<ScreenCameraInputs>,
        ScreenCameraInputs
    > _firstPersonInputsRef = AccessTools.FieldRefAccess<
        TargettingControllerBase<ScreenCameraInputs>,
        ScreenCameraInputs
    >("_inputs");

    private static readonly AccessTools.FieldRef<HeadSimulator, HeadInputs> _headInputsRef =
        AccessTools.FieldRefAccess<HeadSimulator, HeadInputs>("_inputs");

    private readonly WorldManager _worldManager;
    private readonly ILogSink _log;
    private readonly object _cacheLock = new();
    private volatile World? _cachedWorld;
    private bool _disposed;

    public FrooxEngineLocomotionBridge(Engine engine, ILogSink log)
    {
        ArgumentNullException.ThrowIfNull(engine);
        ArgumentNullException.ThrowIfNull(log);

        _worldManager = engine.WorldManager;
        _log = log;

        // WorldFocused は新規 focus でしか発火しないため、subscribe 前に
        // 初期 snapshot を採る (FrooxEngineSessionBridge と同じ pattern)。
        _cachedWorld = _worldManager.FocusedWorld;
        _worldManager.WorldFocused += OnWorldFocused;
    }

    /// <inheritdoc/>
    public Task ApplyAsync(LocomotionCommand command, CancellationToken ct)
    {
        if (_disposed)
        {
            throw new LocomotionNotReadyException("LocomotionBridge has been disposed.");
        }

        ct.ThrowIfCancellationRequested();

        var (loco, fpc, head) = ResolveComponents();

        // Move + Jump: SmoothLocomotionBase 派生 (Walk / Fly / NoClip 等) が
        // active なときだけ。Teleport / GrabWorld 等は失敗扱い。
        if (loco?.ActiveModule is not SmoothLocomotionBase smooth)
        {
            throw new LocomotionNotReadyException(
                "Active LocomotionModule is not SmoothLocomotionBase."
            );
        }

        var normalInput = _smoothNormalInputRef(smooth);
        if (normalInput is null || normalInput.Move is null || normalInput.Jump is null)
        {
            throw new LocomotionNotReadyException(
                "SmoothLocomotionInputs (_normalInput) is not initialized."
            );
        }

        var sprintMul = command.Sprint
            ? (command.SprintMultiplier > 0f ? command.SprintMultiplier : DefaultSprintMultiplier)
            : 1.0f;
        normalInput.Move.ExternalInput = new float3(
            command.MoveX * sprintMul,
            0f,
            command.MoveY * sprintMul
        );
        if (command.Jump)
        {
            // DigitalAction.ExternalInput は OR-merge なので false は明示不要。
            normalInput.Jump.ExternalInput = true;
        }

        // Look (Yaw + Pitch): FirstPersonTargettingController が active なときだけ
        // (VR mode 等で取れないときは silent skip)。pitch は engine 側で
        // `_verticalAngle -= y` の符号反転が入るため、ここで明示的に反転する。
        if (fpc is not null)
        {
            var screenInputs = _firstPersonInputsRef(fpc);
            if (screenInputs?.Look is not null)
            {
                screenInputs.Look.ExternalInput = new float2(command.YawRate, -command.PitchRate);
            }
        }

        // Crouch: HeadSimulator が attach 済みなら HeadInputs.Crouch.ExternalInput
        // にそのまま流す。値 0 でも書く設計 (engine は += 0 を加算するだけで
        // 副作用がなく、idle 戻し用途も兼ねる)。
        if (head is not null)
        {
            var headInputs = _headInputsRef(head);
            if (headInputs?.Crouch is not null)
            {
                headInputs.Crouch.ExternalInput = command.Crouch;
            }
        }

        return Task.CompletedTask;
    }

    private (
        LocomotionController? Loco,
        FirstPersonTargettingController? Fpc,
        HeadSimulator? Head
    ) ResolveComponents()
    {
        lock (_cacheLock)
        {
            var world = _cachedWorld;
            if (world is null || world.IsDisposed)
            {
                // event 経由で更新されるまでの fallback。WorldFocused が発火
                // 前の窓ではここで現在値を採る。
                world = _worldManager.FocusedWorld;
                _cachedWorld = world;
            }

            if (world is null || world.IsDisposed)
            {
                throw new LocomotionNotReadyException("FocusedWorld is not available.");
            }

            var userRoot = world.LocalUser?.Root;
            if (userRoot is null)
            {
                throw new LocomotionNotReadyException(
                    "LocalUser.Root is not yet attached to the focused world."
                );
            }

            var loco = userRoot.Slot.GetComponentInChildren<LocomotionController>();

            var screen = userRoot.ScreenController.Target;
            // ActiveTargetting が FirstPersonTargettingController であるケースを
            // 優先し、null や別 controller のときは Slot 配下の component を直接探す。
            var fpc = screen?.ActiveTargetting.Target as FirstPersonTargettingController;
            if (fpc is null)
            {
                fpc = userRoot.Slot.GetComponentInChildren<FirstPersonTargettingController>();
            }

            // HeadSimulator は ScreenController が attach タイミングで採用する
            // component なので screen が null のとき (= ScreenController 未初期化)
            // は null 返しとし、ApplyAsync が silent skip する。
            var head = screen?.Head.Target;

            return (loco, fpc, head);
        }
    }

    private void OnWorldFocused(World world)
    {
        lock (_cacheLock)
        {
            _cachedWorld = world;
        }
        _log.LogDebug($"LocomotionBridge: world refocused → {world?.Name ?? "<null>"}");
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
            // engine 側が先に破棄されている場合の best-effort。
        }

        // Best-effort idle 戻し: Drive ストリームが終了したとき engine 側に
        // 残っている ExternalInput を 0 で上書きして停止状態を保証する。
        // engine が既に破棄済みなら例外を飲んで skip。
        try
        {
            var (loco, fpc, head) = ResolveComponents();
            if (loco?.ActiveModule is SmoothLocomotionBase smooth)
            {
                var normalInput = _smoothNormalInputRef(smooth);
                if (normalInput?.Move is not null)
                {
                    normalInput.Move.ExternalInput = float3.Zero;
                }
            }
            if (fpc is not null)
            {
                var screenInputs = _firstPersonInputsRef(fpc);
                if (screenInputs?.Look is not null)
                {
                    screenInputs.Look.ExternalInput = float2.Zero;
                }
            }
            if (head is not null)
            {
                var headInputs = _headInputsRef(head);
                if (headInputs?.Crouch is not null)
                {
                    headInputs.Crouch.ExternalInput = 0f;
                }
            }
        }
        catch
        {
            // ProcessExit 経路では engine state が信頼できない。
        }
    }
}
