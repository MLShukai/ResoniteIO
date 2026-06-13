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
/// globally-registered された <see cref="UserspaceRadiantDash"/> を扱う。下部タブ
/// (<see cref="RadiantDashScreen"/>) と、現タブ内の操作対象コントロール
/// (<see cref="Button"/> = 押下 / <see cref="ScrollRect"/> = スクロール) を扱う。
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
    public Task<DashTabListSnapshot> ListTabsAsync(CancellationToken ct)
    {
        return RunOnEngineAsync(
            () =>
            {
                var radiant = ResolveRadiantDash();
                var current = radiant.CurrentScreen?.Target;

                var tabs = new List<DashTabSnapshot>();
                foreach (var screen in radiant.Screens)
                {
                    tabs.Add(BuildTabSnapshot(screen, current));
                }

                return new DashTabListSnapshot(tabs);
            },
            ct
        );
    }

    /// <inheritdoc/>
    public Task<DashActionResultSnapshot> SetTabAsync(
        string refId,
        string localeKey,
        CancellationToken ct
    )
    {
        return RunOnEngineAsync(
            () =>
            {
                var radiant = ResolveRadiantDash();

                var screen = ResolveScreen(radiant, refId, localeKey);
                if (screen is null)
                {
                    return NotFoundTab();
                }

                // engine 自身の RadiantDashButton.Pressed と同一経路で CurrentScreen.Target に直接代入する。
                // タブ Button を SimulatePress で叩く経路は採らない: 言語非依存 locale_key で解決した screen を
                // 確実かつ同期的に切り替えられ、Button の hit-test / interactable gating に左右されないため。
                radiant.CurrentScreen.Target = screen;

                // echo は ListTabs / ResolveScreen と同じ Slot の RefID に揃える
                // (client が echo した ref_id を再度 set_tab(ref_id=...) に使えるように)。
                var afterRefId =
                    radiant.CurrentScreen?.Target?.Slot?.ReferenceID.ToString()
                    ?? screen.Slot?.ReferenceID.ToString()
                    ?? string.Empty;

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

    /// <inheritdoc/>
    public Task<DashControlListSnapshot> ListControlsAsync(
        bool includeDisabled,
        CancellationToken ct
    )
    {
        return RunOnEngineAsync(
            () =>
            {
                var radiant = ResolveRadiantDash();
                var root = radiant.CurrentScreen?.Target?.ScreenRoot;
                if (root is null)
                {
                    return new DashControlListSnapshot(Array.Empty<DashControlSnapshot>());
                }

                // DFS で root 配下から control (Button / ScrollRect) を収集する。control を実際に
                // emit したときだけ parent/depth を進める (light hierarchy)。各 control の sort key
                // (canvas-space rect) も同時に拾い、最後に y→x で stable-sort する。
                var collected = new List<CollectedControl>();
                CollectControls(
                    root,
                    parentRefId: string.Empty,
                    depth: 0,
                    includeDisabled,
                    collected
                );

                StableSortByRect(collected);

                var controls = new List<DashControlSnapshot>(collected.Count);
                foreach (var entry in collected)
                {
                    controls.Add(entry.Snapshot);
                }

                return new DashControlListSnapshot(controls);
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
                    return Rejected(refId, "control is not a button");
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
                    return Rejected(refId, "control is not scrollable");
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
                    // ScrollRect は InteractionElement ではないため hover 非対応として reject される。
                    return Rejected(refId, "control does not support hover");
                }

                element.IsHovering.Value = true;
                return Succeeded(refId);
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

    /// <summary>
    /// 現在の userspace world に globally-registered された <see cref="UserspaceRadiantDash"/> を解決する。
    /// 未準備なら <see cref="DashNotReadyException"/>。engine thread 前提。
    /// </summary>
    private static UserspaceRadiantDash ResolveDash()
    {
        var dash = ResolveWorld().GetGloballyRegisteredComponent<UserspaceRadiantDash>();
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
    /// 現在の dash から <see cref="RadiantDash"/> (tab 列挙・遷移の本体) を解決する。
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
    /// 1 tab (<see cref="RadiantDashScreen"/>) の snapshot を構築する。<c>LocaleKey</c> は
    /// <see cref="ResolveLocaleKey"/> 経由で tab ラベルを駆動する <c>LocaleStringDriver</c> から取る
    /// (言語非依存の主キー)。engine thread 前提。
    /// </summary>
    private static DashTabSnapshot BuildTabSnapshot(
        RadiantDashScreen screen,
        RadiantDashScreen? current
    )
    {
        return new DashTabSnapshot(
            RefId: screen.Slot?.ReferenceID.ToString() ?? string.Empty,
            LocaleKey: ResolveLocaleKey(screen.Label),
            Name: screen.Slot?.Name ?? string.Empty,
            Label: screen.Label?.Value ?? string.Empty,
            IsCurrent: current is not null && screen == current,
            Enabled: screen.ScreenEnabled?.Value ?? true
        );
    }

    /// <summary>
    /// <paramref name="refId"/> 優先、空なら <paramref name="localeKey"/> で <paramref name="radiant"/> の
    /// <see cref="RadiantDash.Screens"/> から screen を解決する。未解決なら null。
    /// </summary>
    /// <remarks>
    /// engine thread 前提。<c>World.ReferenceController</c> ではなく <c>Screens</c> を直接列挙するのは、
    /// ref_id が「この dash に所属する screen」であることを保証するため (任意 RefID の Slot を
    /// screen と取り違えて代入する事故を防ぐ)。
    /// </remarks>
    private static RadiantDashScreen? ResolveScreen(
        RadiantDash radiant,
        string refId,
        string localeKey
    )
    {
        if (!string.IsNullOrEmpty(refId))
        {
            if (!RefID.TryParse(refId, out var parsed))
            {
                return null;
            }

            foreach (var screen in radiant.Screens)
            {
                // ListTabs は screen.Slot.ReferenceID を tab の ref_id として出すので、
                // 解決側も Slot の RefID で突き合わせる (screen 自身の ReferenceID とは別物)。
                if (screen.Slot?.ReferenceID == parsed)
                {
                    return screen;
                }
            }

            return null;
        }

        if (!string.IsNullOrEmpty(localeKey))
        {
            foreach (var screen in radiant.Screens)
            {
                if (ResolveLocaleKey(screen.Label) == localeKey)
                {
                    return screen;
                }
            }
        }

        return null;
    }

    /// <summary>
    /// <paramref name="slot"/> から深さ優先で control (<see cref="Button"/> または <see cref="ScrollRect"/>
    /// を持つ Slot) を収集する。<c>!IsActive</c> な部分木はスキップする。control を実際に emit したときだけ
    /// 子孫の <c>parentRefId</c> / <c>depth</c> を更新する (light hierarchy)。
    /// <paramref name="includeDisabled"/> が false の場合、disabled control は emit しないが子孫の再帰は続ける。
    /// </summary>
    /// <remarks>engine thread 前提。</remarks>
    private static void CollectControls(
        Slot slot,
        string parentRefId,
        int depth,
        bool includeDisabled,
        List<CollectedControl> collected
    )
    {
        if (!slot.IsActive)
        {
            return;
        }

        var nextParentRefId = parentRefId;
        var nextDepth = depth;

        var button = slot.GetComponent<Button>();
        var scroll = button is null ? slot.GetComponent<ScrollRect>() : null;
        if (button is not null || scroll is not null)
        {
            var enabled = button?.Enabled ?? scroll!.Enabled;
            if (includeDisabled || enabled)
            {
                var refId = slot.ReferenceID.ToString();
                var snapshot = BuildControlSnapshot(
                    slot,
                    button,
                    scroll,
                    refId,
                    parentRefId,
                    depth,
                    enabled
                );
                var sortRect = ComputeSortRect(slot, scroll);
                collected.Add(new CollectedControl(snapshot, sortRect));

                // emit した control を基準に子孫の parent/depth を進める。
                nextParentRefId = refId;
                nextDepth = depth + 1;
            }
        }

        foreach (var child in slot.Children)
        {
            CollectControls(child, nextParentRefId, nextDepth, includeDisabled, collected);
        }
    }

    /// <summary>1 control の snapshot を構築する。engine thread 前提。</summary>
    private static DashControlSnapshot BuildControlSnapshot(
        Slot slot,
        Button? button,
        ScrollRect? scroll,
        string refId,
        string parentRefId,
        int depth,
        bool enabled
    )
    {
        var controlType = button is not null ? "button" : "scroll";

        // label を駆動している IField<string> (Text.Content) を特定し、その同じ field から locale_key を取る。
        var labelField = button is not null
            ? button.LabelTextField
            : slot.GetComponentInChildren<Text>()?.Content;

        var labelText = labelField?.Value;
        var localeKey = ResolveLocaleKey(labelField);

        // 1) label 本文 → 2) (上で labelField から取得済み) → 3) locale_key → 4) slot.Name。
        // 最初の non-empty を採用する。label は icon-only button などで "" のことがある。
        var label = FirstNonEmpty(labelText, localeKey, slot.Name);

        return new DashControlSnapshot(
            RefId: refId,
            ControlType: controlType,
            Label: label,
            LocaleKey: localeKey,
            Enabled: enabled,
            ParentRefId: parentRefId,
            Depth: depth
        );
    }

    /// <summary>
    /// sort 用の canvas-space rect を計算する。<paramref name="scroll"/> が非 null の control は
    /// content の伸びた extent ではなく viewport rect を使う (ScrollRect は scroll される Content slot に
    /// 載っており、その slot の rect は content の extent になるため)。RectTransform が無ければ null。
    /// </summary>
    /// <remarks>engine thread 前提。rect は ordering 専用で、wire には emit しない。</remarks>
    private static Rect? ComputeSortRect(Slot slot, ScrollRect? scroll)
    {
        if (scroll is not null)
        {
            var viewportSlot =
                scroll.ViewportOverride.Target?.Slot ?? scroll.RectTransform?.RectParent?.Slot;
            var viewportRect = viewportSlot?.GetComponent<RectTransform>();
            if (viewportRect is not null)
            {
                return viewportRect.ComputeGlobalComputeRect();
            }
            // viewport を解決できなければ content rect に fallback する。
        }

        var rect = slot.GetComponent<RectTransform>();
        return rect?.ComputeGlobalComputeRect();
    }

    /// <summary>
    /// 収集した control を canvas-space rect の y 昇順 → x 昇順で stable-sort する。
    /// rect が無い (RectTransform を持たない) control は末尾に置く。
    /// </summary>
    private static void StableSortByRect(List<CollectedControl> collected)
    {
        // List.Sort は unstable なため、index を tie-breaker にして stable に並べる。
        var indexed = new List<(int Index, CollectedControl Control)>(collected.Count);
        for (var i = 0; i < collected.Count; i++)
        {
            indexed.Add((i, collected[i]));
        }

        indexed.Sort(
            (a, b) =>
            {
                var cmp = CompareByRect(a.Control.SortRect, b.Control.SortRect);
                // 同 rect (両方 rect 無し含む) は元の DFS 順を保つ — これが stable 性を担う。
                return cmp != 0 ? cmp : a.Index.CompareTo(b.Index);
            }
        );

        collected.Clear();
        foreach (var entry in indexed)
        {
            collected.Add(entry.Control);
        }
    }

    /// <summary>
    /// 2 つの sort rect を y 昇順 → x 昇順で比較する。rect 無し (null) は常に末尾
    /// (null は正、非 null は負)。両方 null なら 0 (順序は呼び出し側の tie-breaker に委ねる)。
    /// </summary>
    private static int CompareByRect(Rect? a, Rect? b)
    {
        if (a is null)
        {
            return b is null ? 0 : 1;
        }
        if (b is null)
        {
            return -1;
        }

        var cmpY = a.Value.position.y.CompareTo(b.Value.position.y);
        return cmpY != 0 ? cmpY : a.Value.position.x.CompareTo(b.Value.position.x);
    }

    /// <summary>引数を順に評価し、最初の非空文字列を返す。すべて空なら空文字。</summary>
    private static string FirstNonEmpty(params string?[] candidates)
    {
        foreach (var candidate in candidates)
        {
            if (!string.IsNullOrEmpty(candidate))
            {
                return candidate;
            }
        }
        return string.Empty;
    }

    /// <summary>
    /// <paramref name="field"/> (<see cref="Text.Content"/> や <see cref="RadiantDashScreen.Label"/> 等の
    /// <c>Sync&lt;string&gt;</c>) を駆動している <see cref="LocaleStringDriver"/> から言語非依存の key を読む。
    /// driver が無い (生文字列ラベルしか無い) 要素では空文字。slot.Name には決して fallback しない。
    /// </summary>
    private static string ResolveLocaleKey(IField<string>? field)
    {
        if (field is null)
        {
            return string.Empty;
        }
        // Elements.Core にも GetLocalizedDriver を持たない LocaleHelper があるため fully-qualify する。
        var driver = FrooxEngine.LocaleHelper.GetLocalizedDriver(field);
        return driver?.Key?.Value ?? string.Empty;
    }

    /// <summary>
    /// 現在の userspace world から <paramref name="refId"/> を Slot に解決する。
    /// parse 失敗・未解決・Slot 以外なら false。例外は投げない。engine thread 前提。
    /// </summary>
    private static bool TryResolveSlot(string refId, out Slot slot)
    {
        slot = null!;
        if (!RefID.TryParse(refId, out var parsed))
        {
            return false;
        }

        var element = ResolveWorld().ReferenceController.GetObjectOrNull(in parsed);
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
            Detail: "control not found"
        );
    }

    /// <summary>指定 (ref_id / locale_key) に一致する tab が解決できなかったときの結果 (<c>Found=false</c>)。</summary>
    private static DashActionResultSnapshot NotFoundTab()
    {
        return new DashActionResultSnapshot(
            Ok: false,
            Found: false,
            RefId: string.Empty,
            Detail: "tab not found"
        );
    }

    /// <summary>control は解決できたが操作対象として不適 (型不一致等) なときの結果 (<c>Found=true, Ok=false</c>)。</summary>
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

    /// <summary>
    /// DFS で収集した 1 control と、その sort key (canvas-space rect、無ければ null)。
    /// rect は ordering 専用で wire には載せない。
    /// </summary>
    private readonly struct CollectedControl
    {
        public CollectedControl(DashControlSnapshot snapshot, Rect? sortRect)
        {
            Snapshot = snapshot;
            SortRect = sortRect;
        }

        public DashControlSnapshot Snapshot { get; }

        public Rect? SortRect { get; }
    }
}
