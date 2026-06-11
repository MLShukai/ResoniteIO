using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using Elements.Core;
using FrooxEngine;
using Renderite.Shared;
using ResoniteIO.Core.Grabber;
using ResoniteIO.Core.Logging;

namespace ResoniteIO.Bridge;

/// <summary>
/// FrooxEngine の手 (<see cref="Grabber"/>) を介した掴み/離しを操作する
/// <see cref="IGrabberBridge"/> 実装。
/// </summary>
/// <remarks>
/// <para>
/// 全操作は <see cref="World.RunSynchronously(System.Action)"/> で engine thread に
/// one-shot で marshal し、<see cref="TaskCompletionSource{T}"/> で結果を待つ
/// (<see cref="EngineDispatch.RunOnEngineAsync{T}"/>)。<see cref="WorldManager.FocusedWorld"/> /
/// <c>LocalUser</c> / <see cref="InteractionHandler"/> / <see cref="Grabber"/> が
/// 未準備なら <see cref="GrabberNotReadyException"/> を投げ、Service 層で
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
/// VR モード (<c>ScreenActive == false</c>) は <see cref="GrabberNotReadyException"/>。
/// </para>
/// </remarks>
internal sealed class FrooxEngineGrabberBridge : IGrabberBridge
{
    private readonly WorldManager _worldManager;
    private readonly ILogSink _log;

    public FrooxEngineGrabberBridge(Engine engine, ILogSink log)
    {
        ArgumentNullException.ThrowIfNull(engine);
        ArgumentNullException.ThrowIfNull(log);

        _worldManager = engine.WorldManager;
        _log = log;
    }

    /// <inheritdoc/>
    public Task<GrabOutcome> GrabAsync(GrabberHandSelector hand, float radius, CancellationToken ct)
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
                    var before = grabber.GrabbedObjects.Count;
                    var grabbed = grabber.Grab(hits[0].Point, radius);

                    if (grabbed)
                    {
                        PinGrabbedAtGrabPose(world, grabber, before);
                    }

                    return new GrabOutcome(grabbed, ReadSnapshot(resolved, grabber));
                },
                ct
            );
    }

    /// <inheritdoc/>
    public Task<GrabSnapshot> ReleaseAsync(GrabberHandSelector hand, CancellationToken ct)
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
    public Task<GrabSnapshot> GetStateAsync(GrabberHandSelector hand, CancellationToken ct)
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

    /// <summary>現在 focus されている world を取得する。未準備なら <see cref="GrabberNotReadyException"/>。</summary>
    private World ResolveWorld()
    {
        var world = _worldManager.FocusedWorld;
        if (world is null || world.IsDisposed)
        {
            throw new GrabberNotReadyException(
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
    private (GrabberHandSelector Resolved, Grabber Grabber) ResolveHandGrabber(
        World world,
        GrabberHandSelector hand
    )
    {
        var resolved = ResolveSelector(world, hand);
        return (resolved, ResolveGrabber(world, resolved));
    }

    /// <summary>
    /// engine thread 上で現在のデスクトップカーソルレイ (起点 / 方向) を計算する。
    /// desktop (screen) モード非 active・Mouse 未準備・レイ入力不正は
    /// <see cref="GrabberNotReadyException"/>。
    /// </summary>
    private static (float3 Origin, float3 Direction) ComputeCursorRay(World world)
    {
        var input = world.InputInterface;
        if (input is null || !input.ScreenActive)
        {
            throw new GrabberNotReadyException(
                "Grab requires desktop (screen) mode; VR is active."
            );
        }

        var mouse = input.Mouse;
        if (mouse is null)
        {
            throw new GrabberNotReadyException(
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
            throw new GrabberNotReadyException(
                "Cursor raycast inputs are not valid yet; engine still initializing."
            );
        }

        return (origin, dir);
    }

    /// <summary>
    /// engine thread 上で <paramref name="resolved"/> に対応する <see cref="Grabber"/> を解決する。
    /// </summary>
    /// <remarks>呼び出し元が engine thread に marshal 済みであることを前提とする。</remarks>
    private Grabber ResolveGrabber(World world, GrabberHandSelector resolved)
    {
        var localUser = world.LocalUser;
        if (localUser is null)
        {
            throw new GrabberNotReadyException(
                "No local user in the focused world yet; engine still initializing."
            );
        }

        var side = ToChirality(resolved);
        // LocalUser.GetInteractionHandler(Chirality) — per-hand handler。
        // decompiled/FrooxEngine/FrooxEngine/InteractionHandlerExtensions.cs
        var handler = localUser.GetInteractionHandler(side);
        if (handler is null)
        {
            throw new GrabberNotReadyException(
                $"No InteractionHandler for side {side}; engine still initializing."
            );
        }

        // InteractionHandler.Grabber — 手の Grabber。
        // decompiled/FrooxEngine/FrooxEngine/InteractionHandler.cs:1554
        var grabber = handler.Grabber;
        if (grabber is null)
        {
            throw new GrabberNotReadyException(
                $"No Grabber for side {side}; engine still initializing."
            );
        }
        return grabber;
    }

    /// <summary>
    /// <see cref="GrabberHandSelector.Primary"/> を実際の手 (Left/Right) へ解決する。
    /// Left/Right はそのまま返す。
    /// </summary>
    private static GrabberHandSelector ResolveSelector(World world, GrabberHandSelector hand)
    {
        return hand switch
        {
            GrabberHandSelector.Left => GrabberHandSelector.Left,
            GrabberHandSelector.Right => GrabberHandSelector.Right,
            // Primary: desktop の主手。InputInterface 未準備なら Right に fallback。
            _ => FromChirality(world.InputInterface?.PrimaryHand ?? Chirality.Right),
        };
    }

    private static Chirality ToChirality(GrabberHandSelector resolved)
    {
        return resolved == GrabberHandSelector.Left ? Chirality.Left : Chirality.Right;
    }

    private static GrabberHandSelector FromChirality(Chirality side)
    {
        return side == Chirality.Left ? GrabberHandSelector.Left : GrabberHandSelector.Right;
    }

    /// <summary>
    /// 手の保持ポーズ遷移が落ち着くまで object を grab 時の world pose に
    /// ピン留めし続ける update 数。実測では遷移は約 30 update で settle する
    /// (margin 2 倍)。
    /// </summary>
    private const int GrabPosePinUpdates = 60;

    /// <summary>
    /// engine thread 上で、今回の grab で新たに掴んだ object を grab 時の world pose
    /// (= カーソルレイの hit 位置) にピン留めする。
    /// </summary>
    /// <remarks>
    /// <para>
    /// grab 時、object は world 位置を保ったまま HolderSlot 下に reparent されるが、
    /// desktop では HandSimulator が grab 直後に手を rest pose (腰) から保持ポーズ (胸)
    /// へ動かすため、カーソルレイで遠くを掴んだ際の大きな holder-local offset (実測 ≈1m)
    /// が lever arm として振り回され object が頭の後ろへ飛ぶ (実機計測 2026-06-10)。
    /// HolderSlot の position は InteractionHandler の FieldDrive に駆動されており外部から
    /// 書けない (engine の RunGrab laser 経路の「grab 前に holder を laser 点へ移動」は
    /// 流用不可、実機で確認)。
    /// </para>
    /// <para>
    /// desktop の期待挙動は「object は画面のカーソル位置 (= grab した場所) に留まる」
    /// なので、手の遷移が settle するまで毎 update grab 時の world pose を書き戻して
    /// ピン留めする (移動量ゼロ = カーソル位置への最小距離移動)。settle 後は確定した
    /// holder-local offset のまま手 (= 体) に追従して運べる。
    /// </para>
    /// <para>
    /// なお VR モード対応時は、ピン留めではなく **object を手の中へ寄せる** 方が自然
    /// (手で直接掴む UX)。その場合は engine の TryAlignGrabbed (decompiled
    /// InteractionHandler.cs:3935) と同じ 0.1 秒 tween で寄せるのが良い (実機確認済みの
    /// 良挙動だったため記録):
    /// <code>
    /// slot.Position_Field.TweenTo(
    ///     float3.Zero, 0.1f, CurvePreset.Sine, onlyUnderParent: slot.Parent);
    /// </code>
    /// 現状 GrabAsync は VR (ScreenActive=false) を FailedPrecondition で拒否するため
    /// desktop 経路のみ実装する。
    /// </para>
    /// </remarks>
    private static void PinGrabbedAtGrabPose(World world, Grabber grabber, int previousCount)
    {
        var grabbedObjects = grabber.GrabbedObjects;
        for (var i = previousCount; i < grabbedObjects.Count; i++)
        {
            var grabbable = grabbedObjects[i];
            var slot = grabbable?.Slot;
            if (grabbable is null || slot is null)
            {
                continue;
            }
            PinStep(
                world,
                grabber,
                grabbable,
                slot,
                slot.GlobalPosition,
                slot.GlobalRotation,
                GrabPosePinUpdates
            );
        }
    }

    /// <summary>
    /// <see cref="PinGrabbedAtGrabPose"/> の 1 update 分。release / 削除 / 他 grabber への
    /// 移動でピン留めを打ち切る。
    /// </summary>
    private static void PinStep(
        World world,
        Grabber grabber,
        IGrabbable grabbable,
        Slot slot,
        float3 position,
        floatQ rotation,
        int remaining
    )
    {
        if (slot.IsRemoved || !ReferenceEquals(grabbable.Grabber, grabber))
        {
            return;
        }
        slot.GlobalPosition = position;
        slot.GlobalRotation = rotation;
        if (remaining > 0)
        {
            world.RunInUpdates(
                1,
                () => PinStep(world, grabber, grabbable, slot, position, rotation, remaining - 1)
            );
        }
    }

    /// <summary>
    /// engine thread 上で現在の掴み状態の snapshot を構築する。
    /// <paramref name="resolved"/> は Primary 解決後の実際の手 (Left/Right)。
    /// </summary>
    private static GrabSnapshot ReadSnapshot(GrabberHandSelector resolved, Grabber grabber)
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
