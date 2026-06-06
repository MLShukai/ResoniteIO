namespace ResoniteIO.Core.Dash;

/// <summary>UI 要素の矩形 snapshot (proto <c>DashRect</c> から独立した Core 層 POCO)。</summary>
/// <remarks>
/// origin = 画面左上 (0,0)、x 右・y 下。<paramref name="IsScreenSpace"/> が false の場合は
/// canvas 空間座標 (screen pixel 逆投影が未確定なときのフォールバック)。
/// </remarks>
public sealed record DashRectSnapshot(
    float X,
    float Y,
    float Width,
    float Height,
    bool IsScreenSpace
);

/// <summary>dash (userspace overlay) の開閉状態 snapshot (proto <c>DashState</c> から独立した Core 層 POCO)。</summary>
/// <remarks>
/// <paramref name="OpenLerp"/> は開閉アニメーションの lerp [0.0, 1.0]
/// (<c>UserspaceRadiantDash.OpenLerp</c>)。
/// </remarks>
public sealed record DashStateSnapshot(bool IsOpen, float OpenLerp);

/// <summary>dash UI ツリーの 1 ノード snapshot (proto <c>DashElement</c> から独立した Core 層 POCO)。</summary>
/// <remarks>
/// <paramref name="RefId"/> は <c>Slot.ReferenceID.ToString()</c> で、言語非依存の主キー。
/// Invoke / Highlight / Scroll はこの <paramref name="RefId"/> で engine 側要素を解決する。
/// <paramref name="Type"/> は component 型名 ("Button" / "ScrollRect" / "Text" / "Image" 等)。
/// <paramref name="LocaleKey"/> は <c>LocaleString</c> の key (isLocaleKey のときのみ。例
/// "Settings.Audio")。生文字列ラベルしか無い要素では空文字。
/// </remarks>
public sealed record DashElementSnapshot(
    string RefId,
    string Type,
    string SlotName,
    string LocaleKey,
    string Label,
    bool Enabled,
    bool Interactable,
    DashRectSnapshot Rect,
    string ParentRefId,
    int Depth
);

/// <summary>dash UI ツリー全体の snapshot (proto <c>DashTree</c> から独立した Core 層 POCO)。</summary>
/// <remarks>
/// <paramref name="Elements"/> は深さ優先順。dash が閉じているときは空。
/// <paramref name="ScreenWidth"/> / <paramref name="ScreenHeight"/> はポインタ座標空間 =
/// 現在の window 解像度 (pixel) で、grounding 用。
/// </remarks>
public sealed record DashTreeSnapshot(
    IReadOnlyList<DashElementSnapshot> Elements,
    int ScreenWidth,
    int ScreenHeight
);

/// <summary>状態変化系操作 (Invoke / Highlight / Scroll) の結果 snapshot (proto <c>DashActionResult</c> から独立した Core 層 POCO)。</summary>
/// <remarks>
/// <paramref name="Found"/> は指定 ref_id の要素が解決できたか (false なら <paramref name="Ok"/> も false)。
/// <paramref name="RefId"/> は操作対象として解決した ref_id の echo back。
/// <paramref name="Detail"/> は lock / 非 interactable / 未解決などの補足理由。
/// </remarks>
public sealed record DashActionResultSnapshot(bool Ok, bool Found, string RefId, string Detail);

/// <summary>Mod 側 (FrooxEngine) が実装し DI で注入する dash (userspace overlay) 操作の抽象。</summary>
/// <remarks>
/// 各メソッドは engine thread に one-shot で marshal し、操作後の最新 state を返す。
/// dash は <c>Userspace.UserspaceWorld</c> 配下の <c>UserspaceRadiantDash</c> を扱い、
/// ContextMenu の radial メニューとは別系統。
/// </remarks>
public interface IDashBridge
{
    /// <summary>dash (userspace overlay) を開き、開いた後の state を返す。既に開いていれば no-op で現状態を返す。</summary>
    /// <exception cref="DashNotReadyException">dash / userspace world がまだ準備できていない。</exception>
    Task<DashStateSnapshot> OpenAsync(CancellationToken ct);

    /// <summary>dash を閉じ、閉じた後の state を返す。</summary>
    /// <exception cref="DashNotReadyException">dash / userspace world がまだ準備できていない。</exception>
    Task<DashStateSnapshot> CloseAsync(CancellationToken ct);

    /// <summary>現在の dash 開閉 state を読む。</summary>
    /// <exception cref="DashNotReadyException">dash / userspace world がまだ準備できていない。</exception>
    Task<DashStateSnapshot> GetStateAsync(CancellationToken ct);

    /// <summary>現在開いている dash UI ツリーを列挙する。</summary>
    /// <remarks>
    /// <paramref name="interactableOnly"/> が true なら interactable な要素のみ返す。
    /// <paramref name="rootRefId"/> が空でなければその要素を部分木 root にする (空なら dash 全体)。
    /// </remarks>
    /// <exception cref="DashNotReadyException">dash / userspace world がまだ準備できていない。</exception>
    Task<DashTreeSnapshot> GetTreeAsync(
        bool interactableOnly,
        string rootRefId,
        CancellationToken ct
    );

    /// <summary><paramref name="refId"/> の要素のアクションを実行 (Button.SimulatePress 等) し、結果を返す。</summary>
    /// <exception cref="DashNotReadyException">dash / userspace world がまだ準備できていない。</exception>
    Task<DashActionResultSnapshot> InvokeAsync(string refId, CancellationToken ct);

    /// <summary><paramref name="refId"/> の要素をハイライト (hover) する。実行はしない。</summary>
    /// <exception cref="DashNotReadyException">dash / userspace world がまだ準備できていない。</exception>
    Task<DashActionResultSnapshot> HighlightAsync(string refId, CancellationToken ct);

    /// <summary><paramref name="refId"/> の要素に <paramref name="deltaX"/> / <paramref name="deltaY"/> のスクロールを当て、結果を返す。</summary>
    /// <exception cref="DashNotReadyException">dash / userspace world がまだ準備できていない。</exception>
    Task<DashActionResultSnapshot> ScrollAsync(
        string refId,
        float deltaX,
        float deltaY,
        CancellationToken ct
    );
}

/// <summary>
/// Bridge が一時的に dash を操作できない状態。Service 層は <c>FailedPrecondition</c>
/// に翻訳するので Client は時間を置いて retry できる。
/// </summary>
public sealed class DashNotReadyException : Exception
{
    public DashNotReadyException(string message)
        : base(message) { }

    public DashNotReadyException(string message, Exception innerException)
        : base(message, innerException) { }
}
