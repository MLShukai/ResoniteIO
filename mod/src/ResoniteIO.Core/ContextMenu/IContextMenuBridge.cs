namespace ResoniteIO.Core.ContextMenu;

/// <summary>操作対象の手 (radial メニューを開く側) を指定する Core 層セレクタ。</summary>
/// <remarks>
/// proto <c>ContextMenuHand</c> から独立。<c>Primary</c> は desktop の
/// <c>InputInterface.PrimaryHand</c> に対応 (Bridge 側で解決)。
/// </remarks>
public enum ContextMenuHandSelector
{
    Primary,
    Left,
    Right,
}

/// <summary>radial メニュー 1 項目の snapshot (proto <c>ContextMenuItem</c> から独立した Core 層 POCO)。</summary>
/// <remarks>
/// <paramref name="Index"/> は列挙順 (ArcLayout 子順) で、Highlight / Invoke はこの index で項目を指す。
/// </remarks>
public sealed record ContextMenuItemSnapshot(
    int Index,
    string Label,
    bool Enabled,
    bool HasIcon,
    float ColorR,
    float ColorG,
    float ColorB,
    float ColorA
);

/// <summary>radial メニュー全体の snapshot (proto <c>ContextMenuState</c> から独立した Core 層 POCO)。</summary>
/// <remarks>
/// <paramref name="HighlightedIndex"/> はハイライト中の項目 index。無ければ <c>-1</c>。
/// </remarks>
public sealed record ContextMenuStateSnapshot(
    bool IsOpen,
    IReadOnlyList<ContextMenuItemSnapshot> Items,
    int HighlightedIndex
);

/// <summary>Mod 側 (FrooxEngine) が実装し DI で注入する radial メニュー操作の抽象。</summary>
/// <remarks>
/// 各メソッドは engine thread に one-shot で marshal し、操作後の最新 state を返す。
/// </remarks>
public interface IContextMenuBridge
{
    /// <summary>指定 <paramref name="hand"/> の radial メニューを開き、Opened 到達後の state を返す。</summary>
    /// <exception cref="ContextMenuNotReadyException">local user / handler がまだ準備できていない。</exception>
    Task<ContextMenuStateSnapshot> OpenAsync(ContextMenuHandSelector hand, CancellationToken ct);

    /// <summary>指定 <paramref name="hand"/> の radial メニューを閉じ、閉じた後の state を返す。</summary>
    /// <exception cref="ContextMenuNotReadyException">local user / handler がまだ準備できていない。</exception>
    Task<ContextMenuStateSnapshot> CloseAsync(ContextMenuHandSelector hand, CancellationToken ct);

    /// <summary>指定 <paramref name="hand"/> の現在の radial メニュー state を読む。</summary>
    /// <exception cref="ContextMenuNotReadyException">local user / handler がまだ準備できていない。</exception>
    Task<ContextMenuStateSnapshot> GetStateAsync(
        ContextMenuHandSelector hand,
        CancellationToken ct
    );

    /// <summary><paramref name="index"/> の項目をハイライトし、操作後の state を返す。</summary>
    /// <exception cref="ContextMenuNotReadyException">メニュー未 open 等で操作できない。</exception>
    /// <exception cref="ArgumentOutOfRangeException"><paramref name="index"/> が範囲外。</exception>
    Task<ContextMenuStateSnapshot> HighlightAsync(
        ContextMenuHandSelector hand,
        int index,
        CancellationToken ct
    );

    /// <summary><paramref name="index"/> の項目を実行 (press) し、操作後の state を返す。</summary>
    /// <exception cref="ContextMenuNotReadyException">メニュー未 open 等で操作できない。</exception>
    /// <exception cref="ArgumentOutOfRangeException"><paramref name="index"/> が範囲外。</exception>
    Task<ContextMenuStateSnapshot> InvokeAsync(
        ContextMenuHandSelector hand,
        int index,
        CancellationToken ct
    );
}

/// <summary>
/// Bridge が一時的に radial メニューを操作できない状態。Service 層は <c>FailedPrecondition</c>
/// に翻訳するので Client は時間を置いて retry できる。
/// </summary>
public sealed class ContextMenuNotReadyException : Exception
{
    public ContextMenuNotReadyException(string message)
        : base(message) { }

    public ContextMenuNotReadyException(string message, Exception innerException)
        : base(message, innerException) { }
}
