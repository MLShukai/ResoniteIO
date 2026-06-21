namespace ResoniteIO.Core.Grabber;

/// <summary>操作対象の手 (Grab / Release を行う側) を指定する Core 層セレクタ。</summary>
/// <remarks>
/// proto <c>GrabberHand</c> から独立。<c>Primary</c> は desktop の
/// <c>InputInterface.PrimaryHand</c> に対応 (Bridge 側で解決)。
/// </remarks>
public enum GrabberHandSelector
{
    Primary,
    Left,
    Right,
}

/// <summary>Use / Unuse する仮想ボタンを指定する Core 層セレクタ (proto <c>GrabberButton</c> から独立)。</summary>
/// <remarks><c>Primary</c> = 左クリック相当 (整列 / tool 機能発現)、<c>Secondary</c> = 右クリック相当。</remarks>
public enum GrabberButtonSelector
{
    Primary,
    Secondary,
}

/// <summary>操作後の保持状態 snapshot (proto <c>GrabberGrabState</c> から独立した Core 層 POCO)。</summary>
/// <remarks>
/// <paramref name="Hand"/> は解決後の手 (Primary は実際の Left/Right に解決済みで
/// <c>Unspecified</c> にはならない)。Primary を渡した呼び出し元がどちらの手に解決したか
/// 知れるよう echo back する。
/// <paramref name="ObjectNames"/> は保持中 grabbable の slot 名 (best-effort、空のことがある)。
/// <paramref name="IsToolEquipped"/> は tool を装備中か (<c>ActiveTool != null</c>)、
/// <paramref name="EquippedToolName"/> は装備中 tool の slot 名 (未装備は空文字)。
/// <paramref name="HeldButtons"/> は現在 hold 中 (Use 済み Unuse 前) のボタン (順不同)。
/// </remarks>
public sealed record GrabSnapshot(
    GrabberHandSelector Hand,
    bool IsHolding,
    IReadOnlyList<string> ObjectNames,
    bool IsToolEquipped,
    string EquippedToolName,
    IReadOnlyList<GrabberButtonSelector> HeldButtons
);

/// <summary>Grab 呼び出しの結果 (proto <c>GrabberGrabResult</c> から独立した Core 層 POCO)。</summary>
/// <remarks>
/// <paramref name="Grabbed"/> はこの呼び出しで新たに掴めたか。レイ miss / 範囲に grabbable が
/// 無い場合も false を返すだけでエラーにはしない。<paramref name="State"/> は実行後の保持状態。
/// </remarks>
public sealed record GrabOutcome(bool Grabbed, GrabSnapshot State);

/// <summary>Mod 側 (FrooxEngine) が実装し DI で注入する grab / release 操作の抽象。</summary>
/// <remarks>
/// 各メソッドは engine thread に one-shot で marshal し、操作後の最新 state を返す。
/// </remarks>
public interface IGrabberBridge
{
    /// <summary>
    /// 指定 <paramref name="hand"/> で、現在のデスクトップカーソルレイの hit 点を中心に
    /// <paramref name="radius"/> 内の grabbable を掴み、掴めたか (miss は
    /// <c>Grabbed=false</c>) と実行後の state を返す。
    /// </summary>
    /// <exception cref="GrabberNotReadyException">
    /// local user / handler が未準備、または desktop (screen) モードが非 active (VR)。
    /// </exception>
    Task<GrabOutcome> GrabAsync(GrabberHandSelector hand, float radius, CancellationToken ct);

    /// <summary>指定 <paramref name="hand"/> が保持中の全オブジェクトを離し、実行後の state を返す。</summary>
    /// <exception cref="GrabberNotReadyException">local user / handler がまだ準備できていない。</exception>
    Task<GrabSnapshot> ReleaseAsync(GrabberHandSelector hand, CancellationToken ct);

    /// <summary>指定 <paramref name="hand"/> の現在の保持状態を読む。</summary>
    /// <exception cref="GrabberNotReadyException">local user / handler がまだ準備できていない。</exception>
    Task<GrabSnapshot> GetStateAsync(GrabberHandSelector hand, CancellationToken ct);

    /// <summary>
    /// 指定 <paramref name="hand"/> の item を <paramref name="button"/> で押下する (hold 開始)。
    /// grab 中なら整列、装備 tool 中なら機能発現。<see cref="UnuseAsync"/> まで hold が継続する。
    /// </summary>
    /// <exception cref="GrabberNotReadyException">
    /// local user / handler が未準備、または desktop (screen) モードが非 active (VR)。
    /// </exception>
    Task<GrabSnapshot> UseAsync(
        GrabberHandSelector hand,
        GrabberButtonSelector button,
        CancellationToken ct
    );

    /// <summary>
    /// <see cref="UseAsync"/> で押下中の <paramref name="button"/> を離す (hold 終了)。
    /// 押下していなければ no-op。
    /// </summary>
    /// <exception cref="GrabberNotReadyException">local user / handler が未準備、または VR。</exception>
    Task<GrabSnapshot> UnuseAsync(
        GrabberHandSelector hand,
        GrabberButtonSelector button,
        CancellationToken ct
    );

    /// <summary>
    /// 指定 <paramref name="hand"/> が grab 中の grabbable から ITool を探して装備する。
    /// tool が無ければ no-op。
    /// </summary>
    /// <exception cref="GrabberNotReadyException">local user / handler がまだ準備できていない。</exception>
    Task<GrabSnapshot> EquipAsync(GrabberHandSelector hand, CancellationToken ct);

    /// <summary>指定 <paramref name="hand"/> の装備中 tool を外す。未装備なら no-op。</summary>
    /// <exception cref="GrabberNotReadyException">local user / handler がまだ準備できていない。</exception>
    Task<GrabSnapshot> DequipAsync(GrabberHandSelector hand, CancellationToken ct);
}

/// <summary>
/// Bridge が一時的に grab / release を操作できない状態、または要求が現在の入力モードで
/// 成立しない状態 (VR active 等)。Service 層は <c>FailedPrecondition</c> に翻訳するので
/// Client は状態を変えて retry できる。
/// </summary>
public sealed class GrabberNotReadyException : Exception
{
    public GrabberNotReadyException(string message)
        : base(message) { }

    public GrabberNotReadyException(string message, Exception innerException)
        : base(message, innerException) { }
}
