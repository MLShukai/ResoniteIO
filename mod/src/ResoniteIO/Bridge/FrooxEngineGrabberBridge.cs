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
/// FrooxEngine の手 (<see cref="Grabber"/> / <see cref="InteractionHandler"/>) を介した
/// 掴み/離し (Grab/Release) と掴んだ後の操作 (Use/Unuse/Equip/Dequip) を行う
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
/// Grab / Release / GetState / Equip / Dequip は edge-triggered な one-shot。掴みは
/// <see cref="Grabber.Grab(float3, float)"/> でオブジェクトを手の HolderSlot 下に reparent し、
/// 以降は engine が手に自動追従させる。Equip は engine の <c>EquipGrabbed</c>
/// (decompiled InteractionHandler.cs:3582) を手本に、grab 中の grabbable から
/// <c>ITool</c> を探し <see cref="InteractionHandler.Equip(ITool, bool)"/> で装備する。
/// </para>
/// <para>
/// Use / Unuse は <b>hold セマンティクス</b>を持つ stateful 操作。Use した
/// (手, ボタン) を内部集合に保持し、self-rescheduling repeater
/// (<c>World.RunInUpdates(0, …)</c>) が毎 engine tick その入力 action の <c>ExternalInput</c>
/// を再注入し続ける (engine 1-frame 寿命 ExternalInput と RPC レートのギャップを吸収)。
/// primary は <see cref="InteractionHandlerInputs.Interact"/> (digital) と
/// <see cref="InteractionHandlerInputs.Strength"/> (analog=use で指定された強度) の両方、secondary は
/// <see cref="InteractionHandlerInputs.Secondary"/> (digital) を立てる (実マウス左ボタンが
/// digital と analog strength を同時に駆動するのを再現し、整列・laser press と BrushTool 系
/// (Pen 等、primaryStrength で発火) の双方を成立させる。詳細は <see cref="InjectHeld"/>)。
/// 初 tick で engine が <c>OnPrimaryPress</c> (整列 / 装備 tool の機能発現) を、以後
/// <c>OnPrimaryHold</c> / <c>ITool.Update</c> を毎フレーム駆動する。Unuse で集合から外すと
/// 翌 tick に注入が止まり engine が <c>OnPrimaryRelease</c> を発火、repeater は集合が空に
/// なった時点で self-terminate する。Locomotion の継続入力と同型
/// (<c>memory/feedback_locomotion_external_input.md</c>)。world 切替 / Dispose 時は
/// hold を全クリアしてボタン押しっぱなし leak を防ぐ。
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
internal sealed class FrooxEngineGrabberBridge : IGrabberBridge, IDisposable
{
    private readonly WorldManager _worldManager;
    private readonly ILogSink _log;

    // hold 状態 (Use 済み Unuse 前の (手, ボタン) → 採用済み strength) と repeater の
    // running フラグ / 世代を守る単一 lock。
    private readonly object _holdLock = new();
    private readonly Dictionary<(Chirality Side, GrabberButtonSelector Button), float> _held =
        new();
    private bool _repeaterRunning;

    // repeater の世代。world 切替 / Dispose で進めて旧世代のコルーチンを supersede する。
    // RunInUpdates のコルーチンは scheduling した world のキューに載るため、その world が
    // dispose されると (CoroutineManager.Dispose の worldQueue.Clear) 破棄され二度と走らない。
    // _repeaterRunning だけに依存すると、その取りこぼしでフラグが true のまま wedge し以後
    // 一切 repeater が再起動しなくなる。世代チェックでこれを防ぐ。
    private long _holdGeneration;
    private volatile bool _disposed;

    public FrooxEngineGrabberBridge(Engine engine, ILogSink log)
    {
        ArgumentNullException.ThrowIfNull(engine);
        ArgumentNullException.ThrowIfNull(log);

        _worldManager = engine.WorldManager;
        _log = log;

        // world 切替で hold を持ち越さない (別 world のボタンを押し続けない)。
        _worldManager.WorldFocused += OnWorldFocused;
    }

    /// <inheritdoc/>
    public Task<GrabOutcome> GrabAsync(GrabberHandSelector hand, float radius, CancellationToken ct)
    {
        return ResolveWorld()
            .RunOnEngineAsync(
                () =>
                {
                    var world = ResolveWorld();
                    var (resolved, handler, grabber) = ResolveHand(world, hand);
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
                        return new GrabOutcome(false, ReadSnapshot(resolved, handler, grabber));
                    }

                    // Grabber.Grab(float3 point, float radius) — proximity grab。
                    // decompiled/FrooxEngine/FrooxEngine/Grabber.cs:224
                    var before = grabber.GrabbedObjects.Count;
                    var grabbed = grabber.Grab(hits[0].Point, radius);

                    if (grabbed)
                    {
                        PinGrabbedAtGrabPose(world, grabber, before);
                    }

                    return new GrabOutcome(grabbed, ReadSnapshot(resolved, handler, grabber));
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
                    var (resolved, handler, grabber) = ResolveHand(ResolveWorld(), hand);

                    // Grabber.Release(bool supressEvents = false) — 保持中の全オブジェクトを離す。
                    // decompiled/FrooxEngine/FrooxEngine/Grabber.cs:358
                    grabber.Release();

                    return ReadSnapshot(resolved, handler, grabber);
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
                    var (resolved, handler, grabber) = ResolveHand(ResolveWorld(), hand);
                    return ReadSnapshot(resolved, handler, grabber);
                },
                ct
            );
    }

    /// <inheritdoc/>
    public Task<GrabSnapshot> UseAsync(
        GrabberHandSelector hand,
        GrabberButtonSelector button,
        float strength,
        CancellationToken ct
    )
    {
        return ResolveWorld()
            .RunOnEngineAsync(
                () =>
                {
                    var world = ResolveWorld();
                    var (resolved, handler, grabber) = ResolveHand(world, hand);

                    // (手, ボタン) を hold 集合へ (strength を payload に保持。再 use は上書き)。
                    // repeater が毎 tick ExternalInput を再注入する。
                    lock (_holdLock)
                    {
                        _held[(ToChirality(resolved), button)] = strength;
                    }
                    EnsureRepeaterStarted(world);

                    return ReadSnapshot(resolved, handler, grabber);
                },
                ct
            );
    }

    /// <inheritdoc/>
    public Task<GrabSnapshot> UnuseAsync(
        GrabberHandSelector hand,
        GrabberButtonSelector button,
        CancellationToken ct
    )
    {
        return ResolveWorld()
            .RunOnEngineAsync(
                () =>
                {
                    var (resolved, handler, grabber) = ResolveHand(ResolveWorld(), hand);

                    // 集合から外すだけ。翌 tick に repeater が注入を止め、engine が
                    // ExternalInput 不在を held=false と評価して OnPrimaryRelease を発火する。
                    lock (_holdLock)
                    {
                        _held.Remove((ToChirality(resolved), button));
                    }

                    return ReadSnapshot(resolved, handler, grabber);
                },
                ct
            );
    }

    /// <inheritdoc/>
    public Task<GrabSnapshot> EquipAsync(GrabberHandSelector hand, CancellationToken ct)
    {
        return ResolveWorld()
            .RunOnEngineAsync(
                () =>
                {
                    var (resolved, handler, grabber) = ResolveHand(ResolveWorld(), hand);

                    // engine EquipGrabbed (decompiled InteractionHandler.cs:3582) を手本に、
                    // grab 中の grabbable から最初の ITool を探して装備する。tool が無ければ no-op。
                    var grabbed = grabber.GrabbedObjects;
                    for (var i = 0; i < grabbed.Count; i++)
                    {
                        var grabbable = grabbed[i];
                        if (grabbable is null)
                        {
                            continue;
                        }
                        var tool = grabbable.Slot?.GetComponent<ITool>();
                        if (tool is not null)
                        {
                            // engine の Equip は permission-gated world 等で拒否されうる。
                            // 先に Release してから拒否されると tool を落とすだけになるため、
                            // CanEquip で装備可能を確認できたときだけ grab を手放す
                            // (不可なら no-op で掴んだまま残す)。
                            // decompiled/FrooxEngine/FrooxEngine/InteractionHandler.cs:3436
                            if (handler.CanEquip(tool))
                            {
                                grabber.Release(grabbable, supressEvents: true);
                                handler.Equip(tool, lockEquip: true);
                            }
                            break;
                        }
                    }

                    return ReadSnapshot(resolved, handler, grabber);
                },
                ct
            );
    }

    /// <inheritdoc/>
    public Task<GrabSnapshot> DequipAsync(GrabberHandSelector hand, CancellationToken ct)
    {
        return ResolveWorld()
            .RunOnEngineAsync(
                () =>
                {
                    var (resolved, handler, grabber) = ResolveHand(ResolveWorld(), hand);

                    // InteractionHandler.Dequip(bool popOff) — 装備中 tool を外す。未装備は no-op。
                    // decompiled/FrooxEngine/FrooxEngine/InteractionHandler.cs:3606
                    handler.Dequip(popOff: true);

                    return ReadSnapshot(resolved, handler, grabber);
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
    /// 対応する <see cref="InteractionHandler"/> / <see cref="Grabber"/> をまとめて返す
    /// (全 RPC 共通の前段)。
    /// </summary>
    /// <remarks>呼び出し元が engine thread に marshal 済みであることを前提とする。</remarks>
    private (GrabberHandSelector Resolved, InteractionHandler Handler, Grabber Grabber) ResolveHand(
        World world,
        GrabberHandSelector hand
    )
    {
        var resolved = ResolveSelector(world, hand);
        var handler = ResolveInteractionHandler(world, resolved);

        // InteractionHandler.Grabber — 手の Grabber。
        // decompiled/FrooxEngine/FrooxEngine/InteractionHandler.cs:1554
        var grabber = handler.Grabber;
        if (grabber is null)
        {
            throw new GrabberNotReadyException(
                $"No Grabber for side {ToChirality(resolved)}; engine still initializing."
            );
        }

        return (resolved, handler, grabber);
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
    /// engine thread 上で <paramref name="resolved"/> に対応する <see cref="InteractionHandler"/>
    /// を解決する。
    /// </summary>
    /// <remarks>呼び出し元が engine thread に marshal 済みであることを前提とする。</remarks>
    private static InteractionHandler ResolveInteractionHandler(
        World world,
        GrabberHandSelector resolved
    )
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

        return handler;
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
    private GrabSnapshot ReadSnapshot(
        GrabberHandSelector resolved,
        InteractionHandler handler,
        Grabber grabber
    )
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

        // InteractionHandler.ActiveTool — 装備中 tool (未装備は null)。
        // decompiled/FrooxEngine/FrooxEngine/InteractionHandler.cs:1753
        var activeTool = handler.ActiveTool;
        var isToolEquipped = activeTool is not null;
        var equippedToolName = activeTool?.Slot?.Name ?? string.Empty;

        return new GrabSnapshot(
            resolved,
            isHolding,
            names,
            isToolEquipped,
            equippedToolName,
            HeldButtonsFor(resolved)
        );
    }

    /// <summary>現在 <paramref name="resolved"/> の手で hold 中 (Use 済み Unuse 前) のボタンを列挙する。</summary>
    private IReadOnlyList<GrabberButtonSelector> HeldButtonsFor(GrabberHandSelector resolved)
    {
        var side = ToChirality(resolved);
        var buttons = new List<GrabberButtonSelector>(2);
        lock (_holdLock)
        {
            foreach (var ((heldSide, button), _) in _held)
            {
                if (heldSide == side)
                {
                    buttons.Add(button);
                }
            }
        }
        return buttons;
    }

    /// <summary>
    /// hold 集合が非空の間、毎 engine tick 各 (手, ボタン) の <c>ExternalInput = true</c> を
    /// 再注入する self-rescheduling repeater を、まだ動いていなければ 1 回 schedule する。
    /// </summary>
    /// <remarks>
    /// 注入先 world は <see cref="HoldTickStep"/> が毎 tick <see cref="WorldManager.FocusedWorld"/>
    /// から解決し直すため、ここでは最初の schedule 先 (= Use 呼び出し時の focused world) だけを
    /// 渡す。world 切替後は <see cref="OnWorldFocused"/> が hold を空にし repeater が止まる。
    /// </remarks>
    private void EnsureRepeaterStarted(World world)
    {
        bool start = false;
        long generation = 0;
        lock (_holdLock)
        {
            if (_disposed)
            {
                return;
            }
            if (!_repeaterRunning)
            {
                _repeaterRunning = true;
                generation = ++_holdGeneration;
                start = true;
            }
        }

        if (start)
        {
            TryScheduleTick(world, generation);
        }
    }

    private void TryScheduleTick(World world, long generation)
    {
        try
        {
            world.RunInUpdates(0, () => HoldTickStep(generation));
        }
        catch (Exception ex)
        {
            _log.LogWarning($"GrabberBridge: failed to schedule hold tick: {ex.Message}");
            lock (_holdLock)
            {
                // 自世代の所有権が残っているときだけ running を下ろす。
                if (_holdGeneration == generation)
                {
                    _repeaterRunning = false;
                }
            }
        }
    }

    /// <summary>
    /// engine update tick 上で 1 度実行され、hold 中の各ボタンへ ExternalInput を注入してから
    /// 次 tick へ自己 schedule する repeater 本体。disposed / focus world 不在 / hold 集合が空に
    /// なったら self-terminate する。注入先は毎 tick 現在の focused world から解決し直すので
    /// world 切替に追従する。<paramref name="generation"/> が進んでいたら (world 切替 / Dispose で
    /// supersede 済み) このコルーチンは旧世代として静かに終わる — 現世代の running フラグは
    /// 触らない (二重 repeater の発生を防ぎつつ、コルーチン取りこぼしによる wedge も防ぐ)。
    /// </summary>
    private void HoldTickStep(long generation)
    {
        (Chirality Side, GrabberButtonSelector Button, float Strength)[] held;
        lock (_holdLock)
        {
            if (_holdGeneration != generation)
            {
                return;
            }
            if (_disposed || _held.Count == 0)
            {
                _repeaterRunning = false;
                return;
            }
            held = new (Chirality, GrabberButtonSelector, float)[_held.Count];
            var i = 0;
            foreach (var ((side, button), strength) in _held)
            {
                held[i++] = (side, button, strength);
            }
        }

        var world = _worldManager.FocusedWorld;
        if (world is null || world.IsDisposed)
        {
            lock (_holdLock)
            {
                if (_holdGeneration == generation)
                {
                    _repeaterRunning = false;
                }
            }
            return;
        }

        InjectHeld(world, held);

        bool reschedule;
        lock (_holdLock)
        {
            reschedule = !_disposed && _held.Count > 0 && _holdGeneration == generation;
            if (!reschedule && _holdGeneration == generation)
            {
                _repeaterRunning = false;
            }
        }

        if (reschedule)
        {
            TryScheduleTick(world, generation);
        }
    }

    /// <summary>
    /// engine thread 上で、<paramref name="held"/> の各 (手, ボタン, strength) に対応する入力 action へ
    /// <c>ExternalInput</c> を注入する。primary は <see cref="InteractionHandlerInputs.Interact"/>
    /// (digital) と <see cref="InteractionHandlerInputs.Strength"/> (analog=その entry の strength) の
    /// 両方、secondary は <see cref="InteractionHandlerInputs.Secondary"/> (digital) を立てる
    /// (strength は無視)。
    /// </summary>
    /// <remarks>
    /// <para>
    /// <c>ExternalInput</c> は engine が毎 Evaluate で OR-merge 後に null へ戻す 1-frame 寿命の
    /// フックなので、hold を継続するには毎 tick の再注入が要る (off は明示不要)。
    /// </para>
    /// <para>
    /// primary で Strength も注入するのが要点。実マウス左ボタンは同一 binding で
    /// Interact(digital) と Strength(analog) の両方を駆動する。Interact は
    /// <c>StartInteraction</c>/<c>HoldInteraction</c> (掴んだ object の整列・laser press) を、
    /// Strength は <c>ITool.Update(primaryStrength, …)</c> を駆動する
    /// (decompiled InteractionHandler.cs:2304,2327 — <c>primaryStrength = BlockPrimary ? 0 :
    /// (float)_inputs.Strength</c>)。<see cref="BrushTool"/> 系 (Pen / Geometry Line Brush 等) は
    /// <c>OnPrimaryHold</c> ではなく <c>Update</c> 内で <c>Pressure</c> (← primaryStrength) が
    /// <c>ActivationThreshold</c>(0.05) を超えたら描画する (decompiled BrushTool.cs:524-535)。
    /// digital だけでは primaryStrength=0 のままで brush が一切発火しないため、Strength を
    /// 注入しないと Pen で線が引けない。
    /// </para>
    /// </remarks>
    private static void InjectHeld(
        World world,
        (Chirality Side, GrabberButtonSelector Button, float Strength)[] held
    )
    {
        var localUser = world.LocalUser;
        if (localUser is null)
        {
            return;
        }
        foreach (var (side, button, strength) in held)
        {
            var inputs = localUser.GetInteractionHandler(side)?.Inputs;
            if (inputs is null)
            {
                continue;
            }
            if (button == GrabberButtonSelector.Secondary)
            {
                inputs.Secondary.ExternalInput = true;
            }
            else
            {
                inputs.Interact.ExternalInput = true;
                inputs.Strength.ExternalInput = strength;
            }
        }
    }

    private void OnWorldFocused(World world)
    {
        if (_disposed)
        {
            return;
        }
        // world 切替で hold は持ち越さない。集合を空にするだけでなく running を下ろし
        // 世代を進める: 旧 world に scheduling 済みの HoldTickStep は、その world が
        // dispose されるとコルーチンキューごと破棄され二度と走らないため、running フラグの
        // リセットをその tick に依存できない (依存すると wedge して以後 Use が効かなくなる)。
        // ここで running=false にしておけば、掴んだまま world を離脱しても次の Use が新 world で
        // repeater を再起動できる。世代 bump で、もし旧 tick が生きていても supersede される。
        lock (_holdLock)
        {
            _held.Clear();
            _repeaterRunning = false;
            _holdGeneration++;
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

        lock (_holdLock)
        {
            _held.Clear();
            _repeaterRunning = false;
            // 世代 bump で、scheduling 済みのまだ走っていない HoldTickStep を supersede する。
            _holdGeneration++;
        }

        _log.LogInfo("Grabber Bridge disposed: holds cleared, hold repeater stopped");
    }
}
