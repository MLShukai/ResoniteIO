namespace ResoniteIO.Core.Manipulation;

/// <summary>操作対象の手 (Grab / Release を行う側) を指定する Core 層セレクタ。</summary>
/// <remarks>
/// proto <c>ManipulationHand</c> から独立。<c>Primary</c> は desktop の
/// <c>InputInterface.PrimaryHand</c> に対応 (Bridge 側で解決)。
/// </remarks>
public enum ManipulationHandSelector
{
    Primary,
    Left,
    Right,
}

/// <summary>操作後の保持状態 snapshot (proto <c>ManipulationGrabState</c> から独立した Core 層 POCO)。</summary>
/// <remarks>
/// <paramref name="Hand"/> は解決後の手 (Primary は実際の Left/Right に解決済みで
/// <c>Unspecified</c> にはならない)。Primary を渡した呼び出し元がどちらの手に解決したか
/// 知れるよう echo back する。
/// <paramref name="ObjectNames"/> は保持中 grabbable の slot 名 (best-effort、空のことがある)。
/// </remarks>
public sealed record GrabSnapshot(
    ManipulationHandSelector Hand,
    bool IsHolding,
    IReadOnlyList<string> ObjectNames
);

/// <summary>Grab 呼び出しの結果 (proto <c>ManipulationGrabResult</c> から独立した Core 層 POCO)。</summary>
/// <remarks>
/// <paramref name="Grabbed"/> はこの呼び出しで新たに掴めたか。レイ miss / 範囲に grabbable が
/// 無い場合も false を返すだけでエラーにはしない。<paramref name="State"/> は実行後の保持状態。
/// </remarks>
public sealed record GrabOutcome(bool Grabbed, GrabSnapshot State);

/// <summary>Mod 側 (FrooxEngine) が実装し DI で注入する grab / release 操作の抽象。</summary>
/// <remarks>
/// 各メソッドは engine thread に one-shot で marshal し、操作後の最新 state を返す。
/// </remarks>
public interface IManipulationBridge
{
    /// <summary>
    /// 指定 <paramref name="hand"/> で、現在のデスクトップカーソルレイの hit 点を中心に
    /// <paramref name="radius"/> 内の grabbable を掴み、掴めたか (miss は
    /// <c>Grabbed=false</c>) と実行後の state を返す。
    /// </summary>
    /// <exception cref="ManipulationNotReadyException">
    /// local user / handler が未準備、または desktop (screen) モードが非 active (VR)。
    /// </exception>
    Task<GrabOutcome> GrabAsync(ManipulationHandSelector hand, float radius, CancellationToken ct);

    /// <summary>指定 <paramref name="hand"/> が保持中の全オブジェクトを離し、実行後の state を返す。</summary>
    /// <exception cref="ManipulationNotReadyException">local user / handler がまだ準備できていない。</exception>
    Task<GrabSnapshot> ReleaseAsync(ManipulationHandSelector hand, CancellationToken ct);

    /// <summary>指定 <paramref name="hand"/> の現在の保持状態を読む。</summary>
    /// <exception cref="ManipulationNotReadyException">local user / handler がまだ準備できていない。</exception>
    Task<GrabSnapshot> GetStateAsync(ManipulationHandSelector hand, CancellationToken ct);
}

/// <summary>
/// Bridge が一時的に grab / release を操作できない状態、または要求が現在の入力モードで
/// 成立しない状態 (VR active 等)。Service 層は <c>FailedPrecondition</c> に翻訳するので
/// Client は状態を変えて retry できる。
/// </summary>
public sealed class ManipulationNotReadyException : Exception
{
    public ManipulationNotReadyException(string message)
        : base(message) { }

    public ManipulationNotReadyException(string message, Exception innerException)
        : base(message, innerException) { }
}
