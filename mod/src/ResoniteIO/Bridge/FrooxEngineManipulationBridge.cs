using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using Elements.Core;
using FrooxEngine;
using Renderite.Shared;
using ResoniteIO.Core.Logging;
using ResoniteIO.Core.Manipulation;

namespace ResoniteIO.Bridge;

/// <summary>
/// FrooxEngine の手 (<see cref="Grabber"/>) を介した掴み/離しを操作する
/// <see cref="IManipulationBridge"/> 実装。
/// </summary>
/// <remarks>
/// <para>
/// 全操作は <see cref="World.RunSynchronously(System.Action)"/> で engine thread に
/// one-shot で marshal し、<see cref="TaskCompletionSource{T}"/> で結果を待つ
/// (<see cref="EngineDispatch.RunOnEngineAsync{T}"/>)。<see cref="WorldManager.FocusedWorld"/> /
/// <c>LocalUser</c> / <see cref="InteractionHandler"/> / <see cref="Grabber"/> が
/// 未準備なら <see cref="ManipulationNotReadyException"/> を投げ、Service 層で
/// FailedPrecondition に翻訳する。
/// </para>
/// <para>
/// engine 状態を per-instance には保持せず (manager 参照を読むだけ、event 購読無し、
/// dispatch は <c>world.RunSynchronously</c> の one-shot)、IDisposable でもない。
/// 掴みは <see cref="Grabber.Grab(float3, float)"/> でオブジェクトを手の HolderSlot 下に
/// reparent し、以降は engine が手に自動追従させるため、Locomotion のような per-frame
/// repeater は不要 (Grab/Release は edge-triggered な one-shot で完結する)。
/// </para>
/// <para>
/// Grab の中心点は **デスクトップカーソルレイ** の hit 点。レイは engine 内カーソル位置
/// から計算する: 起点 = <c>world.LocalUserViewPosition</c>
/// (decompiled InteractionHandler.cs:970)、方向 = <c>LocalUserViewRotation *
/// MathX.UVToPerspectiveCameraDirection(Mouse.NormalizedWindowPosition,
/// WindowAspectRatio, LocalUserDesktopFOV)</c> (decompiled TargettingControllerBase.cs:114)。
/// hit 点は自前 raycast (<c>world.Physics.RaycastAll</c>、decompiled RaycastDriver.cs:62
/// パターン) で求め、自分のアバター / 手のコライダ (<c>IsUnderLocalUser</c>) は除外する。
/// grab 実行は従来どおり <see cref="Grabber.Grab(float3, float)"/>
/// (decompiled Grabber.cs:224)。<c>InteractionLaser.LastInteractionTargetPoint</c> は
/// miss でも値が入る / laser 非 active 時は stale なため採用しない。
/// VR モード (<c>ScreenActive == false</c>) は <see cref="ManipulationNotReadyException"/>。
/// </para>
/// </remarks>
internal sealed class FrooxEngineManipulationBridge : IManipulationBridge
{
    private readonly WorldManager _worldManager;
    private readonly ILogSink _log;

    public FrooxEngineManipulationBridge(Engine engine, ILogSink log)
    {
        ArgumentNullException.ThrowIfNull(engine);
        ArgumentNullException.ThrowIfNull(log);

        _worldManager = engine.WorldManager;
        _log = log;
    }

    /// <inheritdoc/>
    public Task<GrabOutcome> GrabAsync(
        ManipulationHandSelector hand,
        float radius,
        CancellationToken ct
    )
    {
        return ResolveWorld()
            .RunOnEngineAsync(
                () =>
                {
                    var world = ResolveWorld();
                    var (resolved, grabber) = ResolveHandGrabber(world, hand);
                    var (origin, dir) = ComputeCursorRay(world);

                    // 自前 raycast (decompiled RaycastDriver.cs:62 パターン)。自分の
                    // アバター / 手のコライダは除外。先頭 hit が最手前である前提。
                    var hits = new List<RaycastHit>();
                    world.Physics.RaycastAll(
                        in origin,
                        in dir,
                        float.MaxValue,
                        hits,
                        c => !c.IsUnderLocalUser,
                        hitTriggers: false
                    );

                    if (hits.Count == 0)
                    {
                        // レイ miss は grabbed=false の正常結果 (Grab は呼ばない)。
                        return new GrabOutcome(false, ReadSnapshot(resolved, grabber));
                    }

                    // Grabber.Grab(float3 point, float radius) — proximity grab。
                    // decompiled/FrooxEngine/FrooxEngine/Grabber.cs:224
                    var grabbed = grabber.Grab(hits[0].Point, radius);

                    return new GrabOutcome(grabbed, ReadSnapshot(resolved, grabber));
                },
                ct
            );
    }

    /// <inheritdoc/>
    public Task<GrabSnapshot> ReleaseAsync(ManipulationHandSelector hand, CancellationToken ct)
    {
        return ResolveWorld()
            .RunOnEngineAsync(
                () =>
                {
                    var (resolved, grabber) = ResolveHandGrabber(ResolveWorld(), hand);

                    // Grabber.Release(bool supressEvents = false) — 保持中の全オブジェクトを離す。
                    // decompiled/FrooxEngine/FrooxEngine/Grabber.cs:358
                    grabber.Release();

                    return ReadSnapshot(resolved, grabber);
                },
                ct
            );
    }

    /// <inheritdoc/>
    public Task<GrabSnapshot> GetStateAsync(ManipulationHandSelector hand, CancellationToken ct)
    {
        return ResolveWorld()
            .RunOnEngineAsync(
                () =>
                {
                    var (resolved, grabber) = ResolveHandGrabber(ResolveWorld(), hand);
                    return ReadSnapshot(resolved, grabber);
                },
                ct
            );
    }

    /// <summary>現在 focus されている world を取得する。未準備なら <see cref="ManipulationNotReadyException"/>。</summary>
    private World ResolveWorld()
    {
        var world = _worldManager.FocusedWorld;
        if (world is null || world.IsDisposed)
        {
            throw new ManipulationNotReadyException(
                "No focused world is available yet; engine still initializing."
            );
        }
        return world;
    }

    /// <summary>
    /// engine thread 上で <paramref name="hand"/> を実際の手 (Left/Right) へ解決し、
    /// 対応する <see cref="Grabber"/> とペアで返す (全 RPC 共通の前段)。
    /// </summary>
    /// <remarks>呼び出し元が engine thread に marshal 済みであることを前提とする。</remarks>
    private (ManipulationHandSelector Resolved, Grabber Grabber) ResolveHandGrabber(
        World world,
        ManipulationHandSelector hand
    )
    {
        var resolved = ResolveSelector(world, hand);
        return (resolved, ResolveGrabber(world, resolved));
    }

    /// <summary>
    /// engine thread 上で現在のデスクトップカーソルレイ (起点 / 方向) を計算する。
    /// desktop (screen) モード非 active・Mouse 未準備・レイ入力不正は
    /// <see cref="ManipulationNotReadyException"/>。
    /// </summary>
    private static (float3 Origin, float3 Direction) ComputeCursorRay(World world)
    {
        var input = world.InputInterface;
        if (input is null || !input.ScreenActive)
        {
            throw new ManipulationNotReadyException(
                "Grab requires desktop (screen) mode; VR is active."
            );
        }

        var mouse = input.Mouse;
        if (mouse is null)
        {
            throw new ManipulationNotReadyException(
                "Mouse device not available yet; engine still initializing."
            );
        }

        // デスクトップカーソルレイ: 起点 = view 位置、方向 = view 回転 *
        // カーソル UV → カメラ方向 (decompiled TargettingControllerBase.cs:114)。
        var origin = world.LocalUserViewPosition;
        var dir = (
            world.LocalUserViewRotation
            * MathX.UVToPerspectiveCameraDirection(
                mouse.NormalizedWindowPosition,
                input.WindowAspectRatio,
                world.LocalUserDesktopFOV
            )
        ).Normalized;

        if (!PhysicsManager.IsValidRaycast(in origin, in dir))
        {
            throw new ManipulationNotReadyException(
                "Cursor raycast inputs are not valid yet; engine still initializing."
            );
        }

        return (origin, dir);
    }

    /// <summary>
    /// engine thread 上で <paramref name="resolved"/> に対応する <see cref="Grabber"/> を解決する。
    /// </summary>
    /// <remarks>呼び出し元が engine thread に marshal 済みであることを前提とする。</remarks>
    private Grabber ResolveGrabber(World world, ManipulationHandSelector resolved)
    {
        var localUser = world.LocalUser;
        if (localUser is null)
        {
            throw new ManipulationNotReadyException(
                "No local user in the focused world yet; engine still initializing."
            );
        }

        var side = ToChirality(resolved);
        // LocalUser.GetInteractionHandler(Chirality) — per-hand handler。
        // decompiled/FrooxEngine/FrooxEngine/InteractionHandlerExtensions.cs
        var handler = localUser.GetInteractionHandler(side);
        if (handler is null)
        {
            throw new ManipulationNotReadyException(
                $"No InteractionHandler for side {side}; engine still initializing."
            );
        }

        // InteractionHandler.Grabber — 手の Grabber。
        // decompiled/FrooxEngine/FrooxEngine/InteractionHandler.cs:1554
        var grabber = handler.Grabber;
        if (grabber is null)
        {
            throw new ManipulationNotReadyException(
                $"No Grabber for side {side}; engine still initializing."
            );
        }
        return grabber;
    }

    /// <summary>
    /// <see cref="ManipulationHandSelector.Primary"/> を実際の手 (Left/Right) へ解決する。
    /// Left/Right はそのまま返す。
    /// </summary>
    private static ManipulationHandSelector ResolveSelector(
        World world,
        ManipulationHandSelector hand
    )
    {
        return hand switch
        {
            ManipulationHandSelector.Left => ManipulationHandSelector.Left,
            ManipulationHandSelector.Right => ManipulationHandSelector.Right,
            // Primary: desktop の主手。InputInterface 未準備なら Right に fallback。
            _ => FromChirality(world.InputInterface?.PrimaryHand ?? Chirality.Right),
        };
    }

    private static Chirality ToChirality(ManipulationHandSelector resolved)
    {
        return resolved == ManipulationHandSelector.Left ? Chirality.Left : Chirality.Right;
    }

    private static ManipulationHandSelector FromChirality(Chirality side)
    {
        return side == Chirality.Left
            ? ManipulationHandSelector.Left
            : ManipulationHandSelector.Right;
    }

    /// <summary>
    /// engine thread 上で現在の掴み状態の snapshot を構築する。
    /// <paramref name="resolved"/> は Primary 解決後の実際の手 (Left/Right)。
    /// </summary>
    private static GrabSnapshot ReadSnapshot(ManipulationHandSelector resolved, Grabber grabber)
    {
        // Grabber.IsHoldingObjects / GrabbedObjects。
        // decompiled/FrooxEngine/FrooxEngine/Grabber.cs:91,95
        var isHolding = grabber.IsHoldingObjects;
        var grabbed = grabber.GrabbedObjects;
        var names = new List<string>(grabbed.Count);
        for (var i = 0; i < grabbed.Count; i++)
        {
            // grabbable.Slot.Name は best-effort (null 要素・null slot は空文字へ)。
            var name = grabbed[i]?.Slot?.Name ?? string.Empty;
            names.Add(name);
        }
        return new GrabSnapshot(resolved, isHolding, names);
    }
}
