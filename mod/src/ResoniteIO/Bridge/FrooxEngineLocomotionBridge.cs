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
/// <see cref="ILocomotionBridge"/> の FrooxEngine 実装。Python 側からの
/// <see cref="LocomotionCommand"/> を engine の <c>ExternalInput</c> に流し込み、
/// 既存の collision / smoothing / yaw clamp 経路を再利用する。
/// </summary>
/// <remarks>
/// <para>
/// <c>InputAction.ExternalInput</c> 書き込みは thread-safe な単純代入 (engine が
/// 次の update tick で消費 + null reset する設計; <see cref="Analog3DAction"/>
/// 参照) なので <c>World.RunSynchronously</c> 経由ではなく任意スレッドから
/// 直接 set する。これにより 30Hz パケットを per-frame overhead 0 で適用できる。
/// </para>
/// <para>
/// engine の private field を <see cref="AccessTools.FieldRefAccess"/> で typed
/// delegate 化して保持する。field 名は engine update で silent に壊れうるため、
/// 初回 Drive で <see cref="LocomotionNotReadyException"/> になったら decompile を
/// 再生成して field 名 diff を確認すること (リスク §1)。
/// </para>
/// </remarks>
internal sealed class FrooxEngineLocomotionBridge : ILocomotionBridge, IDisposable
{
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

        // WorldFocused は新規 focus でしか発火しないため、subscribe 前の初期
        // snapshot で起動時の窓を埋める (FrooxEngineSessionBridge と同じ pattern)。
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

        // Teleport / GrabWorld 等 SmoothLocomotionBase 派生でない module は失敗扱い。
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

        // proto3 default=0 を 1.0 に再解釈する正典的な site (詳細は locomotion.proto)。
        var velocityMul = command.Velocity > 0f ? command.Velocity : 1.0f;
        normalInput.Move.ExternalInput = new float3(
            command.MoveX * velocityMul,
            0f,
            command.MoveY * velocityMul
        );
        if (command.Jump)
        {
            // DigitalAction.ExternalInput は OR-merge なので false は明示不要。
            normalInput.Jump.ExternalInput = true;
        }

        // pitch は engine 側 `_verticalAngle -= y` で反転加算されるため符号反転。
        // FirstPersonTargettingController が無い (VR mode 等) なら silent skip。
        if (fpc is not null)
        {
            var screenInputs = _firstPersonInputsRef(fpc);
            if (screenInputs?.Look is not null)
            {
                screenInputs.Look.ExternalInput = new float2(command.YawRate, -command.PitchRate);
            }
        }

        // 値 0 でも書く: engine の += 0 には副作用が無く、idle 戻し用途も兼ねる。
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
                // WorldFocused 発火前の起動窓では現在値を直接採る。
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
            // ActiveTargetting が他の controller のときは Slot 配下から fallback 探索。
            var fpc = screen?.ActiveTargetting.Target as FirstPersonTargettingController;
            if (fpc is null)
            {
                fpc = userRoot.Slot.GetComponentInChildren<FirstPersonTargettingController>();
            }

            // ScreenController 未初期化 → Head は null。ApplyAsync が silent skip する。
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

        // Best-effort idle 戻し: 残留 ExternalInput を 0 で上書きして停止を保証。
        // engine が既に破棄済みなら例外を飲んで skip (ProcessExit 経路)。
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
