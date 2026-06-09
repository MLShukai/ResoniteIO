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
        ManipulationPoint? point,
        float radius,
        CancellationToken ct
    )
    {
        return ResolveWorld()
            .RunOnEngineAsync(
                () =>
                {
                    var world = ResolveWorld();
                    var resolved = ResolveSelector(world, hand);
                    var grabber = ResolveGrabber(world, resolved);

                    // proximity grab の中心。point 未指定なら手 (holder slot) の現在 world 位置。
                    var center = point is { } p
                        ? new float3(p.X, p.Y, p.Z)
                        : ResolveHandPosition(grabber);

                    // Grabber.Grab(float3 point, float radius) — proximity grab。
                    // decompiled/FrooxEngine/FrooxEngine/Grabber.cs:224
                    var grabbed = grabber.Grab(center, radius);

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
                    var world = ResolveWorld();
                    var resolved = ResolveSelector(world, hand);
                    var grabber = ResolveGrabber(world, resolved);

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
                    var world = ResolveWorld();
                    var resolved = ResolveSelector(world, hand);
                    var grabber = ResolveGrabber(world, resolved);
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
    /// 手の現在 world 位置を求める。holder slot (掴んだ物の親) を優先し、
    /// 取得不可なら grabber 自身の slot 位置に fallback する。
    /// </summary>
    /// <remarks>engine thread 前提。</remarks>
    private static float3 ResolveHandPosition(Grabber grabber)
    {
        // Grabber.HolderSlot は removed 時に null を返す。
        // decompiled/FrooxEngine/FrooxEngine/Grabber.cs:63
        var holder = grabber.HolderSlot;
        if (holder is not null)
        {
            return holder.GlobalPosition;
        }
        return grabber.Slot.GlobalPosition;
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
