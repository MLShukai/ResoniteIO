using System;
using System.Collections.Generic;
using System.Reflection;
using System.Threading;
using System.Threading.Tasks;
using Elements.Core;
using FrooxEngine;
using Renderite.Shared;
using ResoniteIO.Core.ContextMenu;
using ResoniteIO.Core.Logging;
using FrooxContextMenu = FrooxEngine.ContextMenu;
using FrooxContextMenuItem = FrooxEngine.ContextMenuItem;

namespace ResoniteIO.Bridge;

/// <summary>
/// FrooxEngine の radial (context) メニューを操作する <see cref="IContextMenuBridge"/> 実装。
/// </summary>
/// <remarks>
/// <para>
/// 全操作は <see cref="World.RunSynchronously(System.Action)"/> で engine thread に
/// one-shot で marshal し、<see cref="TaskCompletionSource{T}"/> で結果を待つ
/// (<see cref="RunOnEngineAsync{T}"/>)。<see cref="WorldManager.FocusedWorld"/> /
/// <c>LocalUser</c> / <see cref="InteractionHandler"/> が未準備なら
/// <see cref="ContextMenuNotReadyException"/> を投げ Service 層で FailedPrecondition に翻訳する。
/// </para>
/// <para>
/// 標準項目入り (T キー相当) のメニューを開くには <b>private</b>
/// <c>InteractionHandler.OpenContextMenu(MenuOptions.Default)</c> を呼ぶ必要があるため
/// reflection を使う (public <c>OpenMenu</c> は空リングしか開かない)。private enum
/// <c>InteractionHandler.MenuOptions</c> の <c>Default</c> 値と
/// <see cref="MethodInfo"/> は static にキャッシュし、解決失敗時は fail-fast する。
/// open は async (Opening→Opened + 項目生成) なので、起動後は engine thread を
/// busy-spin させず短い実時間 delay を挟みつつ <c>Opened</c> 到達までポーリングする。
/// </para>
/// </remarks>
internal sealed class FrooxEngineContextMenuBridge : IContextMenuBridge
{
    // 標準項目入りメニューを開く private API。decompiled/.../InteractionHandler.cs:47,4122 が正典:
    //   private enum MenuOptions { Default, Locomotion, Grabbing, LaserGrab, HandGrab }
    //   private void OpenContextMenu(MenuOptions options, float? speedOverride = null)
    private static readonly Type _menuOptionsType = ResolveMenuOptionsType();
    private static readonly object _menuOptionsDefault = ResolveMenuOptionsDefault(
        _menuOptionsType
    );
    private static readonly MethodInfo _openContextMenuMethod = ResolveOpenContextMenuMethod(
        _menuOptionsType
    );

    // Opened 到達までのポーリング: ~2s 相当。短い実時間 delay を挟んで engine を busy-spin させない。
    private static readonly TimeSpan _openPollInterval = TimeSpan.FromMilliseconds(50);
    private const int _openPollMaxAttempts = 40;

    // Invoke 後の submenu 遷移を 1 回拾うための短い delay。
    private static readonly TimeSpan _postInvokeDelay = TimeSpan.FromMilliseconds(100);

    private readonly WorldManager _worldManager;
    private readonly ILogSink _log;

    public FrooxEngineContextMenuBridge(Engine engine, ILogSink log)
    {
        ArgumentNullException.ThrowIfNull(engine);
        ArgumentNullException.ThrowIfNull(log);

        _worldManager = engine.WorldManager;
        _log = log;
    }

    /// <inheritdoc/>
    public async Task<ContextMenuStateSnapshot> OpenAsync(
        ContextMenuHandSelector hand,
        CancellationToken ct
    )
    {
        // open のトリガは engine thread で 1 回行い、既に開いていれば no-op。
        await RunOnEngineAsync(
                ResolveWorld(),
                () =>
                {
                    var handler = ResolveHandler(hand);
                    if (!handler.IsContextMenuOpen)
                    {
                        // OpenContextMenu(MenuOptions.Default) — speedOverride は省略 (null)。
                        _openContextMenuMethod.Invoke(
                            handler,
                            new object?[] { _menuOptionsDefault, null }
                        );
                    }
                    return true;
                },
                ct
            )
            .ConfigureAwait(false);

        // Opening→Opened + 項目生成は次フレーム以降に進むため、実時間 delay を挟んでポーリングする。
        for (var attempt = 0; attempt < _openPollMaxAttempts; attempt++)
        {
            var opened = await RunOnEngineAsync(
                    ResolveWorld(),
                    () =>
                    {
                        var handler = ResolveHandler(hand);
                        var menu = handler.ContextMenu.Target;
                        return handler.IsContextMenuOpen
                            && menu is not null
                            && menu.MenuState == FrooxContextMenu.State.Opened;
                    },
                    ct
                )
                .ConfigureAwait(false);

            if (opened)
            {
                break;
            }

            await Task.Delay(_openPollInterval, ct).ConfigureAwait(false);
        }

        return await GetStateAsync(hand, ct).ConfigureAwait(false);
    }

    /// <inheritdoc/>
    public Task<ContextMenuStateSnapshot> CloseAsync(
        ContextMenuHandSelector hand,
        CancellationToken ct
    )
    {
        return RunOnEngineAsync(
            ResolveWorld(),
            () =>
            {
                var handler = ResolveHandler(hand);
                handler.CloseContextMenu();
                return ReadState(handler);
            },
            ct
        );
    }

    /// <inheritdoc/>
    public Task<ContextMenuStateSnapshot> GetStateAsync(
        ContextMenuHandSelector hand,
        CancellationToken ct
    )
    {
        return RunOnEngineAsync(ResolveWorld(), () => ReadState(ResolveHandler(hand)), ct);
    }

    /// <inheritdoc/>
    public Task<ContextMenuStateSnapshot> HighlightAsync(
        ContextMenuHandSelector hand,
        int index,
        CancellationToken ct
    )
    {
        return RunOnEngineAsync(
            ResolveWorld(),
            () =>
            {
                var handler = ResolveHandler(hand);
                var items = ResolveOpenItems(handler);
                ThrowIfIndexOutOfRange(index, items.Count);

                for (var i = 0; i < items.Count; i++)
                {
                    if (i == index)
                    {
                        items[i].SetHighlighted();
                    }
                    else
                    {
                        items[i].ClearHighlighted();
                    }
                }

                return ReadState(handler);
            },
            ct
        );
    }

    /// <inheritdoc/>
    public async Task<ContextMenuStateSnapshot> InvokeAsync(
        ContextMenuHandSelector hand,
        int index,
        CancellationToken ct
    )
    {
        await RunOnEngineAsync(
                ResolveWorld(),
                () =>
                {
                    var handler = ResolveHandler(hand);
                    var menu = handler.ContextMenu.Target!;
                    var items = ResolveOpenItems(handler);
                    ThrowIfIndexOutOfRange(index, items.Count);

                    var button = items[index].Button;
                    if (button is null)
                    {
                        throw new ContextMenuNotReadyException(
                            $"context menu item {index} has no button to press."
                        );
                    }

                    // ContextMenu.PressMenuItem と同じ呼び方:
                    //   SimulatePress(0.1f, new ButtonEventData(menu, canvasGlobalPoint, zero, zero))
                    var localPoint = float3.Zero;
                    var globalPoint = menu.Canvas.Slot.LocalPointToGlobal(in localPoint);
                    var localPress = float2.Zero;
                    button.SimulatePress(
                        0.1f,
                        new ButtonEventData(menu, in globalPoint, in localPress, in localPress)
                    );
                    return true;
                },
                ct
            )
            .ConfigureAwait(false);

        // press 後の submenu 遷移を 1 拍待ってから state を読む。
        await Task.Delay(_postInvokeDelay, ct).ConfigureAwait(false);
        return await GetStateAsync(hand, ct).ConfigureAwait(false);
    }

    /// <summary>engine thread に <paramref name="fn"/> を marshal し結果を await する one-shot ヘルパ。</summary>
    private static async Task<T> RunOnEngineAsync<T>(World world, Func<T> fn, CancellationToken ct)
    {
        var tcs = new TaskCompletionSource<T>();
        world.RunSynchronously(() =>
        {
            try
            {
                tcs.SetResult(fn());
            }
            catch (Exception e)
            {
                tcs.SetException(e);
            }
        });
        using (ct.Register(() => tcs.TrySetCanceled(ct)))
        {
            return await tcs.Task.ConfigureAwait(false);
        }
    }

    /// <summary>現在 focus されている world を取得する。未準備なら <see cref="ContextMenuNotReadyException"/>。</summary>
    private World ResolveWorld()
    {
        var world = _worldManager.FocusedWorld;
        if (world is null || world.IsDisposed)
        {
            throw new ContextMenuNotReadyException(
                "No focused world is available yet; engine still initializing."
            );
        }
        return world;
    }

    /// <summary>
    /// engine thread 上で <paramref name="hand"/> に対応する <see cref="InteractionHandler"/> を解決する。
    /// </summary>
    /// <remarks>呼び出し元が engine thread に marshal 済みであることを前提とする。</remarks>
    private InteractionHandler ResolveHandler(ContextMenuHandSelector hand)
    {
        var world = ResolveWorld();
        var localUser = world.LocalUser;
        if (localUser is null)
        {
            throw new ContextMenuNotReadyException(
                "No local user in the focused world yet; engine still initializing."
            );
        }

        var side = ResolveChirality(world, hand);
        var handler = localUser.GetInteractionHandler(side);
        if (handler is null)
        {
            throw new ContextMenuNotReadyException(
                $"No InteractionHandler for side {side}; engine still initializing."
            );
        }
        return handler;
    }

    private static Chirality ResolveChirality(World world, ContextMenuHandSelector hand)
    {
        return hand switch
        {
            ContextMenuHandSelector.Left => Chirality.Left,
            ContextMenuHandSelector.Right => Chirality.Right,
            // Primary: desktop の主手。InputInterface 未準備なら Right に fallback。
            _ => world.InputInterface?.PrimaryHand ?? Chirality.Right,
        };
    }

    /// <summary>open 済みメニューの項目を列挙順で取得する。未 open なら <see cref="ContextMenuNotReadyException"/>。</summary>
    private static List<FrooxContextMenuItem> ResolveOpenItems(InteractionHandler handler)
    {
        if (!handler.IsContextMenuOpen)
        {
            throw new ContextMenuNotReadyException(
                "Context menu is not open; open it before highlighting or invoking items."
            );
        }

        var menu = handler.ContextMenu.Target;
        if (menu is null)
        {
            throw new ContextMenuNotReadyException("Context menu component is not available yet.");
        }

        return menu.Slot.GetComponentsInChildren<FrooxContextMenuItem>();
    }

    /// <summary>Highlight / Invoke 共通の項目 index 範囲チェック。範囲外なら <see cref="ArgumentOutOfRangeException"/>。</summary>
    private static void ThrowIfIndexOutOfRange(int index, int itemCount)
    {
        if (index < 0 || index >= itemCount)
        {
            throw new ArgumentOutOfRangeException(
                nameof(index),
                index,
                $"index out of range; menu has {itemCount} item(s)."
            );
        }
    }

    /// <summary>engine thread 上で現在の state snapshot を構築する。</summary>
    private static ContextMenuStateSnapshot ReadState(InteractionHandler handler)
    {
        var isOpen = handler.IsContextMenuOpen;
        var menu = handler.ContextMenu.Target;
        if (!isOpen || menu is null)
        {
            return new ContextMenuStateSnapshot(false, Array.Empty<ContextMenuItemSnapshot>(), -1);
        }

        var components = menu.Slot.GetComponentsInChildren<FrooxContextMenuItem>();
        var items = new List<ContextMenuItemSnapshot>(components.Count);
        var highlightedIndex = -1;
        for (var i = 0; i < components.Count; i++)
        {
            var item = components[i];
            if (highlightedIndex < 0 && item.Highlight.Value)
            {
                highlightedIndex = i;
            }

            var color = item.Color.Value;
            items.Add(
                new ContextMenuItemSnapshot(
                    i,
                    item.LabelText ?? string.Empty,
                    item.Button?.Enabled ?? false,
                    item.HasSprite,
                    color.r,
                    color.g,
                    color.b,
                    color.a
                )
            );
        }

        return new ContextMenuStateSnapshot(true, items, highlightedIndex);
    }

    private static Type ResolveMenuOptionsType()
    {
        var type = typeof(InteractionHandler).GetNestedType(
            "MenuOptions",
            BindingFlags.NonPublic | BindingFlags.Public
        );
        if (type is null)
        {
            throw new ContextMenuNotReadyException(
                "Could not resolve private enum InteractionHandler.MenuOptions via reflection; "
                    + "Resonite internals may have changed (see decompiled/.../InteractionHandler.cs)."
            );
        }
        return type;
    }

    private static object ResolveMenuOptionsDefault(Type menuOptionsType)
    {
        try
        {
            return Enum.Parse(menuOptionsType, "Default");
        }
        catch (ArgumentException ex)
        {
            throw new ContextMenuNotReadyException(
                "Could not resolve InteractionHandler.MenuOptions.Default via reflection; "
                    + "Resonite internals may have changed (see decompiled/.../InteractionHandler.cs).",
                ex
            );
        }
    }

    private static MethodInfo ResolveOpenContextMenuMethod(Type menuOptionsType)
    {
        // private void OpenContextMenu(MenuOptions options, float? speedOverride = null)
        var method = typeof(InteractionHandler).GetMethod(
            "OpenContextMenu",
            BindingFlags.Instance | BindingFlags.NonPublic,
            binder: null,
            types: new[] { menuOptionsType, typeof(float?) },
            modifiers: null
        );
        if (method is null)
        {
            throw new ContextMenuNotReadyException(
                "Could not resolve private InteractionHandler.OpenContextMenu(MenuOptions, float?) "
                    + "via reflection; Resonite internals may have changed "
                    + "(see decompiled/.../InteractionHandler.cs)."
            );
        }
        return method;
    }
}
