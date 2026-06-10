using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using Elements.Core;
using FrooxEngine;
using FrooxEngine.UIX;
using ResoniteIO.Core.Dash;
using ResoniteIO.Core.Logging;

namespace ResoniteIO.Bridge;

/// <summary>
/// FrooxEngine の userspace overlay (dash) を操作する <see cref="IDashBridge"/> 実装。
/// </summary>
/// <remarks>
/// <para>
/// 全操作は <see cref="World.RunSynchronously(System.Action)"/> で engine thread に
/// one-shot で marshal し、<see cref="TaskCompletionSource{T}"/> で結果を待つ
/// (<see cref="RunOnEngineAsync{T}"/>)。<see cref="Userspace.UserspaceWorld"/> /
/// <see cref="UserspaceRadiantDash"/> が未準備なら <see cref="DashNotReadyException"/>
/// を投げ Service 層で FailedPrecondition に翻訳する。
/// </para>
/// <para>
/// dash は ContextMenu の radial メニューとは別系統で、<c>UserspaceWorld</c> 配下に
/// globally-registered された <see cref="UserspaceRadiantDash"/> を扱う。Open/Close/State は
/// engine API で確実に動くが、ツリー列挙 / Invoke / Highlight / Scroll は UIX (<see cref="RectTransform"/> /
/// <see cref="Button"/> / <see cref="ScrollRect"/> 等) の best-effort で、screen pixel への逆投影は
/// 未対応のため Rect は canvas 空間で返す (<c>IsScreenSpace=false</c>)。
/// </para>
/// <para>
/// 操作系 (Invoke / Highlight / Scroll) の対象未解決・型不一致は例外でなく
/// <see cref="DashActionResultSnapshot"/> の <c>Found</c> / <c>Ok</c> = false で返す。
/// </para>
/// </remarks>
internal sealed class FrooxEngineDashBridge : IDashBridge
{
    private readonly ILogSink _log;

    public FrooxEngineDashBridge(Engine engine, ILogSink log)
    {
        ArgumentNullException.ThrowIfNull(engine);
        ArgumentNullException.ThrowIfNull(log);

        _log = log;
    }

    /// <inheritdoc/>
    public Task<DashStateSnapshot> OpenAsync(CancellationToken ct)
    {
        return RunOnEngineAsync(
            () =>
            {
                var dash = ResolveDash();
                dash.Open = true;
                return ReadState(dash);
            },
            ct
        );
    }

    /// <inheritdoc/>
    public Task<DashStateSnapshot> CloseAsync(CancellationToken ct)
    {
        return RunOnEngineAsync(
            () =>
            {
                var dash = ResolveDash();
                dash.Open = false;
                return ReadState(dash);
            },
            ct
        );
    }

    /// <inheritdoc/>
    public Task<DashStateSnapshot> GetStateAsync(CancellationToken ct)
    {
        return RunOnEngineAsync(() => ReadState(ResolveDash()), ct);
    }

    /// <inheritdoc/>
    public Task<DashTreeSnapshot> GetTreeAsync(
        bool interactableOnly,
        string rootRefId,
        CancellationToken ct
    )
    {
        return RunOnEngineAsync(
            () =>
            {
                var world = ResolveWorld();
                var dash = ResolveDash(world);

                var rootSlot = ResolveTreeRoot(world, dash, rootRefId);
                var elements = new List<DashElementSnapshot>();
                if (rootSlot is not null)
                {
                    CollectElements(
                        rootSlot,
                        parentRefId: string.Empty,
                        depth: 0,
                        interactableOnly,
                        elements
                    );
                }

                var resolution = world.InputInterface?.WindowResolution ?? int2.Zero;
                return new DashTreeSnapshot(elements, resolution.x, resolution.y);
            },
            ct
        );
    }

    /// <inheritdoc/>
    public Task<DashActionResultSnapshot> InvokeAsync(string refId, CancellationToken ct)
    {
        return RunOnEngineAsync(
            () =>
            {
                if (!TryResolveSlot(refId, out var slot))
                {
                    return NotFound(refId);
                }

                var button = slot.GetComponent<Button>();
                if (button is null)
                {
                    return Rejected(refId, "element is not a button");
                }

                // ContextMenu.PressMenuItem と同じ呼び方:
                //   SimulatePress(0.1f, new ButtonEventData(button, canvasGlobalPoint, zero, zero))
                var localPoint = float3.Zero;
                var globalPoint = button.RectTransform.Canvas.Slot.LocalPointToGlobal(
                    in localPoint
                );
                var localPress = float2.Zero;
                button.SimulatePress(
                    0.1f,
                    new ButtonEventData(button, in globalPoint, in localPress, in localPress)
                );
                return Succeeded(refId);
            },
            ct
        );
    }

    /// <inheritdoc/>
    public Task<DashActionResultSnapshot> HighlightAsync(string refId, CancellationToken ct)
    {
        return RunOnEngineAsync(
            () =>
            {
                if (!TryResolveSlot(refId, out var slot))
                {
                    return NotFound(refId);
                }

                var element = slot.GetComponent<InteractionElement>();
                if (element is null)
                {
                    return Rejected(refId, "element does not support hover");
                }

                element.IsHovering.Value = true;
                return Succeeded(refId);
            },
            ct
        );
    }

    /// <inheritdoc/>
    public Task<DashActionResultSnapshot> ScrollAsync(
        string refId,
        float deltaX,
        float deltaY,
        CancellationToken ct
    )
    {
        return RunOnEngineAsync(
            () =>
            {
                if (!TryResolveSlot(refId, out var slot))
                {
                    return NotFound(refId);
                }

                var scroll =
                    slot.GetComponent<ScrollRect>() ?? slot.GetComponentInParents<ScrollRect>();
                if (scroll is null)
                {
                    return Rejected(refId, "element is not scrollable");
                }

                scroll.NormalizedPosition.Value = MathX.Clamp01(
                    scroll.NormalizedPosition.Value + new float2(deltaX, deltaY)
                );
                return Succeeded(refId);
            },
            ct
        );
    }

    /// <inheritdoc/>
    public Task<DashScreenListSnapshot> ListScreensAsync(CancellationToken ct)
    {
        return RunOnEngineAsync(
            () =>
            {
                var radiant = ResolveRadiantDash();
                var current = radiant.CurrentScreen?.Target;

                var screens = new List<DashScreenSnapshot>();
                foreach (var screen in radiant.Screens)
                {
                    screens.Add(BuildScreenSnapshot(screen, current));
                }

                return new DashScreenListSnapshot(screens);
            },
            ct
        );
    }

    /// <inheritdoc/>
    public Task<DashActionResultSnapshot> SetScreenAsync(
        string refId,
        string key,
        CancellationToken ct
    )
    {
        return RunOnEngineAsync(
            () =>
            {
                var radiant = ResolveRadiantDash();

                var screen = ResolveScreen(radiant, refId, key);
                if (screen is null)
                {
                    return NotFoundScreen();
                }

                // engine 自身の RadiantDashButton.Pressed と同一経路で CurrentScreen.Target に直接代入する。
                // タブ Button を SimulatePress で叩く経路は採らない: 言語非依存 key で解決した screen を
                // 確実かつ同期的に切り替えられ、Button の hit-test / interactable gating に左右されないため。
                radiant.CurrentScreen.Target = screen;

                var afterRefId =
                    radiant.CurrentScreen?.Target?.ReferenceID.ToString()
                    ?? screen.ReferenceID.ToString();

                // disabled screen でも代入自体はブロックされない (button 側の gating)。
                // 遷移は成立扱い (ok=true) とし、無効状態は detail で通知する。
                var detail =
                    screen.ScreenEnabled?.Value == false ? "screen disabled" : string.Empty;

                return new DashActionResultSnapshot(
                    Ok: true,
                    Found: true,
                    RefId: afterRefId,
                    Detail: detail
                );
            },
            ct
        );
    }

    /// <summary>engine thread に <paramref name="fn"/> を marshal し結果を await する one-shot ヘルパ。</summary>
    private Task<T> RunOnEngineAsync<T>(Func<T> fn, CancellationToken ct) =>
        ResolveWorld().RunOnEngineAsync(fn, ct);

    /// <summary>userspace overlay world を取得する。未準備なら <see cref="DashNotReadyException"/>。</summary>
    private static World ResolveWorld()
    {
        var world = Userspace.UserspaceWorld;
        if (world is null || world.IsDisposed)
        {
            throw new DashNotReadyException(
                "Userspace world is not available yet; engine still initializing."
            );
        }
        return world;
    }

    /// <summary>現在の userspace world から dash を解決する。</summary>
    private static UserspaceRadiantDash ResolveDash()
    {
        return ResolveDash(ResolveWorld());
    }

    /// <summary>
    /// <paramref name="world"/> に globally-registered された <see cref="UserspaceRadiantDash"/> を解決する。
    /// 未準備なら <see cref="DashNotReadyException"/>。
    /// </summary>
    /// <remarks>呼び出し元が engine thread に marshal 済みであることを前提とする。</remarks>
    private static UserspaceRadiantDash ResolveDash(World world)
    {
        var dash = world.GetGloballyRegisteredComponent<UserspaceRadiantDash>();
        if (dash is null)
        {
            throw new DashNotReadyException(
                "UserspaceRadiantDash is not registered yet; engine still initializing."
            );
        }
        return dash;
    }

    /// <summary>engine thread 上で現在の dash 開閉 state を読む。</summary>
    private static DashStateSnapshot ReadState(UserspaceRadiantDash dash)
    {
        return new DashStateSnapshot(dash.Open, dash.OpenLerp);
    }

    /// <summary>
    /// 現在の dash から <see cref="RadiantDash"/> (screen 列挙・遷移の本体) を解決する。
    /// <c>dash.Dash</c> が transient に null のことがあるため、null なら <see cref="DashNotReadyException"/>。
    /// </summary>
    /// <remarks>engine thread 前提。</remarks>
    private static RadiantDash ResolveRadiantDash()
    {
        var radiant = ResolveDash().Dash;
        if (radiant is null)
        {
            throw new DashNotReadyException("RadiantDash is not available yet.");
        }
        return radiant;
    }

    /// <summary>
    /// 1 screen の snapshot を構築する。<c>Key</c> は <see cref="ResolveLocaleKey"/> 経由で
    /// screen ラベルを駆動する <c>LocaleStringDriver</c> から取る (言語非依存の主キー)。engine thread 前提。
    /// </summary>
    private static DashScreenSnapshot BuildScreenSnapshot(
        RadiantDashScreen screen,
        RadiantDashScreen? current
    )
    {
        return new DashScreenSnapshot(
            RefId: screen.ReferenceID.ToString(),
            Key: ResolveLocaleKey(screen.Label),
            Name: screen.Slot?.Name ?? string.Empty,
            Label: screen.Label?.Value ?? string.Empty,
            IsCurrent: current is not null && screen == current,
            Enabled: screen.ScreenEnabled?.Value ?? false
        );
    }

    /// <summary>
    /// <paramref name="refId"/> 優先、空なら <paramref name="key"/> で <paramref name="radiant"/> の
    /// <see cref="RadiantDash.Screens"/> から screen を解決する。未解決なら null。
    /// </summary>
    /// <remarks>
    /// engine thread 前提。<c>World.ReferenceController</c> ではなく <c>Screens</c> を直接列挙するのは、
    /// ref_id が「この dash に所属する screen」であることを保証するため (任意 RefID の Slot を
    /// screen と取り違えて代入する事故を防ぐ)。
    /// </remarks>
    private static RadiantDashScreen? ResolveScreen(RadiantDash radiant, string refId, string key)
    {
        if (!string.IsNullOrEmpty(refId))
        {
            if (!RefID.TryParse(refId, out var parsed))
            {
                return null;
            }

            foreach (var screen in radiant.Screens)
            {
                if (screen.ReferenceID == parsed)
                {
                    return screen;
                }
            }

            return null;
        }

        if (!string.IsNullOrEmpty(key))
        {
            foreach (var screen in radiant.Screens)
            {
                if (ResolveLocaleKey(screen.Label) == key)
                {
                    return screen;
                }
            }
        }

        return null;
    }

    /// <summary>
    /// 列挙対象の root Slot を解決する。<paramref name="rootRefId"/> が非空ならその要素を root に、
    /// 空なら現在表示中の screen (なければ dash の VisualsRoot) を root にする。
    /// 解決できなければ null (= 空ツリー)。
    /// </summary>
    /// <remarks>engine thread 前提。</remarks>
    private static Slot? ResolveTreeRoot(World world, UserspaceRadiantDash dash, string rootRefId)
    {
        if (!string.IsNullOrEmpty(rootRefId))
        {
            return TryResolveSlot(world, rootRefId, out var slot) ? slot : null;
        }

        var radiant = dash.Dash;
        if (radiant is null)
        {
            return null;
        }

        return radiant.CurrentScreen.Target?.ScreenRoot ?? radiant.VisualsRoot;
    }

    /// <summary>
    /// <paramref name="slot"/> から深さ優先で <see cref="RectTransform"/> を持つ Slot を要素として収集する。
    /// </summary>
    /// <remarks>engine thread 前提。</remarks>
    private static void CollectElements(
        Slot slot,
        string parentRefId,
        int depth,
        bool interactableOnly,
        List<DashElementSnapshot> elements
    )
    {
        var rect = slot.GetComponent<RectTransform>();
        var nextParentRefId = parentRefId;
        var nextDepth = depth;

        if (rect is not null)
        {
            var refId = slot.ReferenceID.ToString();
            var interactable = ResolveInteractable(slot);
            if (!interactableOnly || interactable)
            {
                elements.Add(BuildElement(slot, rect, refId, parentRefId, depth, interactable));
            }

            // RectTransform を持つ Slot を「親」とみなして子孫の ParentRefId / Depth を更新する。
            nextParentRefId = refId;
            nextDepth = depth + 1;
        }

        foreach (var child in slot.Children)
        {
            CollectElements(child, nextParentRefId, nextDepth, interactableOnly, elements);
        }
    }

    /// <summary>1 要素の snapshot を構築する。engine thread 前提。</summary>
    private static DashElementSnapshot BuildElement(
        Slot slot,
        RectTransform rect,
        string refId,
        string parentRefId,
        int depth,
        bool interactable
    )
    {
        var button = slot.GetComponent<Button>();
        var type = ResolveType(slot, button);

        var text = button is not null ? button.Label : slot.GetComponentInChildren<Text>();
        var label = text?.Content?.Value ?? string.Empty;
        var localeKey = ResolveLocaleKey(text?.Content);

        var globalRect = rect.ComputeGlobalComputeRect();
        var rectSnapshot = new DashRectSnapshot(
            globalRect.position.x,
            globalRect.position.y,
            globalRect.size.x,
            globalRect.size.y,
            IsScreenSpace: false
        );

        return new DashElementSnapshot(
            RefId: refId,
            Type: type,
            SlotName: slot.Name ?? string.Empty,
            LocaleKey: localeKey,
            Label: label,
            Enabled: slot.IsActive,
            Interactable: interactable,
            Rect: rectSnapshot,
            ParentRefId: parentRefId,
            Depth: depth
        );
    }

    /// <summary>component 型からラベル付きの型名を決める。</summary>
    private static string ResolveType(Slot slot, Button? button)
    {
        if (button is not null)
        {
            return "Button";
        }
        if (slot.GetComponent<ScrollRect>() is not null)
        {
            return "ScrollRect";
        }
        if (slot.GetComponent<Text>() is not null)
        {
            return "Text";
        }
        if (slot.GetComponent<Image>() is not null)
        {
            return "Image";
        }
        return "RectTransform";
    }

    /// <summary>
    /// <paramref name="field"/> (<see cref="Text.Content"/> や <see cref="RadiantDashScreen.Label"/> 等の
    /// <c>Sync&lt;string&gt;</c>) を駆動している <see cref="LocaleStringDriver"/> から言語非依存の key を読む。
    /// driver が無い (生文字列ラベルしか無い) 要素では空文字。
    /// </summary>
    private static string ResolveLocaleKey(IField<string>? field)
    {
        if (field is null)
        {
            return string.Empty;
        }
        var driver = FrooxEngine.LocaleHelper.GetLocalizedDriver(field);
        return driver?.Key?.Value ?? string.Empty;
    }

    /// <summary>
    /// slot が <see cref="IUIInteractable"/> を持ち、その component が enabled なら interactable。
    /// </summary>
    private static bool ResolveInteractable(Slot slot)
    {
        var interactable = slot.GetComponent<IUIInteractable>();
        return interactable is not null && interactable.Enabled;
    }

    /// <summary>現在の userspace world から <paramref name="refId"/> を Slot に解決する。engine thread 前提。</summary>
    private static bool TryResolveSlot(string refId, out Slot slot)
    {
        return TryResolveSlot(ResolveWorld(), refId, out slot);
    }

    /// <summary>
    /// <paramref name="refId"/> を parse し <paramref name="world"/> 内の Slot に解決する。
    /// parse 失敗・未解決・Slot 以外なら false。例外は投げない。
    /// </summary>
    /// <remarks>engine thread 前提。</remarks>
    private static bool TryResolveSlot(World world, string refId, out Slot slot)
    {
        slot = null!;
        if (!RefID.TryParse(refId, out var parsed))
        {
            return false;
        }

        var element = world.ReferenceController.GetObjectOrNull(in parsed);
        if (element is Slot resolved)
        {
            slot = resolved;
            return true;
        }
        return false;
    }

    /// <summary>対象 ref_id が解決できなかったときの結果 (<c>Found=false</c>)。</summary>
    private static DashActionResultSnapshot NotFound(string refId)
    {
        return new DashActionResultSnapshot(
            Ok: false,
            Found: false,
            RefId: refId,
            Detail: "element not found"
        );
    }

    /// <summary>指定 (ref_id / key) に一致する screen が解決できなかったときの結果 (<c>Found=false</c>)。</summary>
    private static DashActionResultSnapshot NotFoundScreen()
    {
        return new DashActionResultSnapshot(
            Ok: false,
            Found: false,
            RefId: string.Empty,
            Detail: "screen not found"
        );
    }

    /// <summary>要素は解決できたが操作対象として不適 (型不一致等) なときの結果 (<c>Found=true, Ok=false</c>)。</summary>
    private static DashActionResultSnapshot Rejected(string refId, string detail)
    {
        return new DashActionResultSnapshot(Ok: false, Found: true, RefId: refId, Detail: detail);
    }

    /// <summary>操作が成功したときの結果 (<c>Found=true, Ok=true</c>)。</summary>
    private static DashActionResultSnapshot Succeeded(string refId)
    {
        return new DashActionResultSnapshot(
            Ok: true,
            Found: true,
            RefId: refId,
            Detail: string.Empty
        );
    }
}
