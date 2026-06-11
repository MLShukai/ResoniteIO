namespace ResoniteIO.Core.Cursor;

/// <summary>
/// desktop カーソル位置の snapshot (proto <c>CursorState</c> から独立した Core 層 POCO)。
/// </summary>
/// <remarks>
/// 座標は正規化ウィンドウ座標 ([0,1]、中央 = 0.5)。<paramref name="WindowWidth"/> /
/// <paramref name="WindowHeight"/> は正規化↔ピクセル変換の基準となるウィンドウ解像度。
/// <paramref name="Held"/> は SetPosition による保持がこの snapshot 採取時点で有効か
/// どうか。Release 後 / world focus 切替後 / 未保持は false。
/// </remarks>
public sealed record CursorStateSnapshot(
    float X,
    float Y,
    int WindowWidth,
    int WindowHeight,
    bool Held
);

/// <summary>Mod 側 (FrooxEngine) が実装し DI で注入する desktop カーソル操作の抽象。</summary>
/// <remarks>
/// 各メソッドは engine thread に marshal し、操作後の最新 state を返す。
/// <c>SetPositionAsync</c> は call-scoped ではなく RPC を跨いで保持する: 保持は
/// <c>ReleaseAsync</c> が呼ばれるまで有効。
/// </remarks>
public interface ICursorBridge
{
    /// <summary>
    /// カーソルを正規化位置 (<paramref name="x"/>, <paramref name="y"/>) へ動かして
    /// <b>Release まで保持</b> し、反映後の state を返す。保持中の再呼び出しは保持位置を
    /// 更新する。
    /// </summary>
    /// <remarks>引数は呼び出し側 (Service) で [0,1] に検証済みである前提。</remarks>
    /// <exception cref="CursorNotReadyException">
    /// local user / input がまだ準備できていない、または保持機構が利用不能。
    /// </exception>
    Task<CursorStateSnapshot> SetPositionAsync(float x, float y, CancellationToken ct);

    /// <summary>現在のカーソル位置・解像度・保持状態を読む (副作用なし)。</summary>
    /// <exception cref="CursorNotReadyException">local user / input がまだ準備できていない。</exception>
    Task<CursorStateSnapshot> GetPositionAsync(CancellationToken ct);

    /// <summary>
    /// SetPosition による保持を解除し、解除後の state を返す。<b>冪等</b>: 未保持でも
    /// 成功し現在の state を返す。
    /// </summary>
    /// <exception cref="CursorNotReadyException">
    /// local user / input がまだ準備できていない、または保持機構が利用不能。
    /// </exception>
    Task<CursorStateSnapshot> ReleaseAsync(CancellationToken ct);
}

/// <summary>
/// Bridge が一時的にカーソルを操作できない状態。Service 層は <c>FailedPrecondition</c>
/// に翻訳するので Client は時間を置いて retry できる。
/// </summary>
public sealed class CursorNotReadyException : Exception
{
    public CursorNotReadyException(string message)
        : base(message) { }

    public CursorNotReadyException(string message, Exception innerException)
        : base(message, innerException) { }
}
