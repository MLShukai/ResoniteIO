namespace ResoniteIO.Core.Dash;

/// <summary>dash (userspace overlay) の開閉状態 snapshot (proto <c>DashState</c> から独立した Core 層 POCO)。</summary>
/// <remarks>
/// <paramref name="OpenLerp"/> は開閉アニメーションの lerp [0.0, 1.0]
/// (<c>UserspaceRadiantDash.OpenLerp</c>)。
/// </remarks>
public sealed record DashStateSnapshot(bool IsOpen, float OpenLerp);

/// <summary>dash 下部タブバーの 1 タブ (<c>RadiantDashScreen</c>) の snapshot (proto <c>DashTab</c> から独立した Core 層 POCO)。</summary>
/// <remarks>
/// <paramref name="RefId"/> は tab (screen) slot の <c>ReferenceID.ToString()</c> で
/// <see cref="IDashBridge.SetTabAsync"/> の exact 指定キー。
/// <paramref name="LocaleKey"/> は <c>LocaleStringDriver.Key</c> (例 "Dash.Screens.Worlds") で
/// 言語非依存キー。取得できない tab では空文字。
/// <paramref name="Name"/> は <c>screen.Slot.Name</c> (例 "Worlds")、第 2 の言語非依存 ID。
/// <paramref name="Label"/> は localize 済み表示テキスト (debug / 人間向け)。
/// <paramref name="IsCurrent"/> は現在表示中の tab か、<paramref name="Enabled"/> は遷移可能か。
/// </remarks>
public sealed record DashTabSnapshot(
    string RefId,
    string LocaleKey,
    string Name,
    string Label,
    bool IsCurrent,
    bool Enabled
);

/// <summary>dash の全 tab 一覧の snapshot (proto <c>DashTabList</c> から独立した Core 層 POCO)。</summary>
/// <remarks>
/// <paramref name="Tabs"/> は <c>radiant.Screens</c> の列挙順。<c>IsCurrent==true</c> は高々 1 件
/// (current が transient null なら 0 件あり得る)。
/// </remarks>
public sealed record DashTabListSnapshot(IReadOnlyList<DashTabSnapshot> Tabs);

/// <summary>現在の tab 内の操作可能な 1 control (<c>Button</c> / <c>ScrollRect</c>) の snapshot (proto <c>DashControl</c> から独立した Core 層 POCO)。</summary>
/// <remarks>
/// <paramref name="RefId"/> は control slot の <c>ReferenceID.ToString()</c> で
/// Invoke / Scroll / Highlight の主キー。
/// <paramref name="ControlType"/> は <c>"button"</c> | <c>"scroll"</c> (server 側で正規化済み)。
/// <paramref name="Label"/> は localize 済み表示ラベル (icon-only button 等では空文字あり)。
/// <paramref name="LocaleKey"/> は <c>LocaleStringDriver.Key</c> (生文字列ラベルでは空文字)。
/// <paramref name="ParentRefId"/> は直近の列挙済み control 祖先の ref_id (最上位は空文字)、
/// <paramref name="Depth"/> は列挙済み control 階層の深さ (最上位 = 0)。
/// </remarks>
public sealed record DashControlSnapshot(
    string RefId,
    string ControlType,
    string Label,
    string LocaleKey,
    bool Enabled,
    string ParentRefId,
    int Depth
);

/// <summary>現在の tab 内の control 一覧の snapshot (proto <c>DashControlList</c> から独立した Core 層 POCO)。</summary>
/// <remarks>
/// <paramref name="Controls"/> は reading 順 (上→下, 左→右)。tab が空 / 未解決なら空。
/// </remarks>
public sealed record DashControlListSnapshot(IReadOnlyList<DashControlSnapshot> Controls);

/// <summary>状態変化系操作 (SetTab / Invoke / Highlight / Scroll) の結果 snapshot (proto <c>DashActionResult</c> から独立した Core 層 POCO)。</summary>
/// <remarks>
/// <paramref name="Found"/> は指定 ref_id の対象が解決できたか (false なら <paramref name="Ok"/> も false)。
/// <paramref name="RefId"/> は操作対象として解決した ref_id の echo back。
/// <paramref name="Detail"/> は lock / 非対応 / 未解決などの補足理由。
/// </remarks>
public sealed record DashActionResultSnapshot(bool Ok, bool Found, string RefId, string Detail);

/// <summary>Mod 側 (FrooxEngine) が実装し DI で注入する dash (userspace overlay) 操作の抽象。</summary>
/// <remarks>
/// 各メソッドは engine thread に one-shot で marshal し、操作後の最新 snapshot を返す。
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

    /// <summary>下部タブバーの全 tab を列挙する。dash が閉じていても tab 構成は存在するため列挙できる。</summary>
    /// <remarks><c>IsCurrent==true</c> は高々 1 件 (current が transient null なら 0 件あり得る)。</remarks>
    /// <exception cref="DashNotReadyException">dash / userspace world がまだ準備できていない。</exception>
    Task<DashTabListSnapshot> ListTabsAsync(CancellationToken ct);

    /// <summary>指定 tab へ切り替える (<c>CurrentScreen.Target</c> 代入)。open 状態は変更しない。</summary>
    /// <remarks>
    /// <paramref name="refId"/> が非空ならそれで exact 解決し、空なら <paramref name="localeKey"/> で解決する。
    /// 一致 tab があれば <c>Ok</c> / <c>Found</c> = true、<c>RefId</c> = 遷移後 current の ref_id。
    /// 未解決なら <c>Ok</c> / <c>Found</c> = false で返す (例外でなく soft-fail)。
    /// </remarks>
    /// <exception cref="DashNotReadyException">dash / userspace world がまだ準備できていない。</exception>
    Task<DashActionResultSnapshot> SetTabAsync(
        string refId,
        string localeKey,
        CancellationToken ct
    );

    /// <summary>現在の tab 内の操作可能な control を reading 順で列挙する。</summary>
    /// <remarks>
    /// <paramref name="includeDisabled"/> が true なら disabled control も含める (default は enabled のみ)。
    /// tab が空 / current が未解決なら空リスト (soft)。
    /// </remarks>
    /// <exception cref="DashNotReadyException">dash / userspace world がまだ準備できていない。</exception>
    Task<DashControlListSnapshot> ListControlsAsync(bool includeDisabled, CancellationToken ct);

    /// <summary><paramref name="refId"/> の control のアクションを実行 (<c>Button.SimulatePress</c>) し、結果を返す。</summary>
    /// <remarks>
    /// <paramref name="refId"/> の解決失敗・型不一致は例外でなく <c>Found</c> / <c>Ok</c> = false で返す。
    /// </remarks>
    /// <exception cref="DashNotReadyException">dash / userspace world がまだ準備できていない。</exception>
    Task<DashActionResultSnapshot> InvokeAsync(string refId, CancellationToken ct);

    /// <summary><paramref name="refId"/> の control に <paramref name="deltaX"/> / <paramref name="deltaY"/> のスクロールを当て、結果を返す。</summary>
    /// <remarks><paramref name="refId"/> 未解決・scroll 非対応は例外でなく <c>Found</c> / <c>Ok</c> = false で返す。</remarks>
    /// <exception cref="DashNotReadyException">dash / userspace world がまだ準備できていない。</exception>
    Task<DashActionResultSnapshot> ScrollAsync(
        string refId,
        float deltaX,
        float deltaY,
        CancellationToken ct
    );

    /// <summary><paramref name="refId"/> の control をハイライト (hover) する。実行はしない。</summary>
    /// <remarks><paramref name="refId"/> 未解決・hover 非対応は例外でなく <c>Found</c> / <c>Ok</c> = false で返す。</remarks>
    /// <exception cref="DashNotReadyException">dash / userspace world がまだ準備できていない。</exception>
    Task<DashActionResultSnapshot> HighlightAsync(string refId, CancellationToken ct);
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
