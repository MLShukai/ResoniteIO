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

/// <summary>dash 下部タブが切り替える 1 screen (<c>RadiantDashScreen</c>) の snapshot (proto <c>DashScreen</c> から独立した Core 層 POCO)。</summary>
/// <remarks>
/// <paramref name="Key"/> は <c>LocaleStringDriver</c> の key (例 "Dash.Screens.Worlds") で言語非依存の主キー。
/// 取得できない screen では空文字。<paramref name="RefId"/> は screen slot の <c>ReferenceID.ToString()</c> で
/// セッション内 exact 指定キー。<paramref name="Name"/> は <c>screen.Slot.Name</c> (第 2 の言語非依存 ID)。
/// <paramref name="Label"/> は localize 済み表示テキスト (debug / 人間向け)。
/// <paramref name="IsCurrent"/> は current screen か、<paramref name="Enabled"/> は遷移可能か
/// (例: ログアウト中の Contacts は false)。
/// </remarks>
public sealed record DashScreenSnapshot(
    string RefId,
    string Key,
    string Name,
    string Label,
    bool IsCurrent,
    bool Enabled
);

/// <summary>dash の全 screen 一覧の snapshot (proto <c>DashScreenList</c> から独立した Core 層 POCO)。</summary>
/// <remarks>
/// <paramref name="Screens"/> は <c>dash.Dash.Screens</c> の列挙順。<c>IsCurrent==true</c> は高々 1 件
/// (current が transient null なら 0 件あり得る)。
/// </remarks>
public sealed record DashScreenListSnapshot(IReadOnlyList<DashScreenSnapshot> Screens);

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
    /// <remarks>
    /// <paramref name="refId"/> の解決失敗・型不一致は例外でなく <c>Found</c> / <c>Ok</c> = false で返す
    /// (ContextMenu の index 版と違い、無効な ref_id は throw しない)。
    /// </remarks>
    /// <exception cref="DashNotReadyException">dash / userspace world がまだ準備できていない。</exception>
    Task<DashActionResultSnapshot> InvokeAsync(string refId, CancellationToken ct);

    /// <summary><paramref name="refId"/> の要素をハイライト (hover) する。実行はしない。</summary>
    /// <remarks><paramref name="refId"/> 未解決・hover 非対応は例外でなく <c>Found</c> / <c>Ok</c> = false で返す。</remarks>
    /// <exception cref="DashNotReadyException">dash / userspace world がまだ準備できていない。</exception>
    Task<DashActionResultSnapshot> HighlightAsync(string refId, CancellationToken ct);

    /// <summary><paramref name="refId"/> の要素に <paramref name="deltaX"/> / <paramref name="deltaY"/> のスクロールを当て、結果を返す。</summary>
    /// <remarks><paramref name="refId"/> 未解決・scroll 非対応は例外でなく <c>Found</c> / <c>Ok</c> = false で返す。</remarks>
    /// <exception cref="DashNotReadyException">dash / userspace world がまだ準備できていない。</exception>
    Task<DashActionResultSnapshot> ScrollAsync(
        string refId,
        float deltaX,
        float deltaY,
        CancellationToken ct
    );

    /// <summary>dash の全 screen snapshot を列挙する。dash が閉じていても screen 構成は存在するため列挙できる。</summary>
    /// <remarks>
    /// 各 <see cref="DashScreenSnapshot"/> は dash の現状を反映する。<c>IsCurrent==true</c> は高々 1 件
    /// (current が transient null なら 0 件あり得る)。
    /// </remarks>
    /// <exception cref="DashNotReadyException">dash / userspace world がまだ準備できていない。</exception>
    Task<DashScreenListSnapshot> ListScreensAsync(CancellationToken ct);

    /// <summary>指定 screen へ遷移する (<c>CurrentScreen.Target</c> 代入)。open 状態は変更しない。</summary>
    /// <remarks>
    /// <paramref name="refId"/> が非空ならそれで exact 解決し、空なら <paramref name="key"/> で解決する。
    /// 一致 screen があれば <c>Ok</c> / <c>Found</c> = true、<c>RefId</c> = 遷移後 current の ref_id。
    /// 未解決なら <c>Ok</c> / <c>Found</c> = false で返す (例外でなく soft-fail)。
    /// disabled screen も代入自体はブロックされないため遷移を実行し、<c>Ok=true</c> のまま
    /// <c>Detail="screen disabled"</c> を載せて返す。
    /// </remarks>
    /// <exception cref="DashNotReadyException">dash / userspace world がまだ準備できていない。</exception>
    Task<DashActionResultSnapshot> SetScreenAsync(string refId, string key, CancellationToken ct);
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
