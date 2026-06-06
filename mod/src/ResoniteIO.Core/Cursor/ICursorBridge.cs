namespace ResoniteIO.Core.Cursor;

/// <summary>
/// desktop カーソル位置の snapshot (proto <c>CursorState</c> から独立した Core 層 POCO)。
/// </summary>
/// <remarks>
/// 座標は正規化ウィンドウ座標 ([0,1]、中央 = 0.5)。<paramref name="WindowWidth"/> /
/// <paramref name="WindowHeight"/> は正規化↔ピクセル変換の基準となるウィンドウ解像度。
/// </remarks>
public sealed record CursorStateSnapshot(float X, float Y, int WindowWidth, int WindowHeight);

/// <summary>Mod 側 (FrooxEngine) が実装し DI で注入する desktop カーソル操作の抽象。</summary>
/// <remarks>各メソッドは engine thread に one-shot で marshal し、操作後の最新 state を返す。</remarks>
public interface ICursorBridge
{
    /// <summary>
    /// カーソルを正規化位置 (<paramref name="x"/>, <paramref name="y"/>) へ動かし、
    /// 反映後の state を返す。
    /// </summary>
    /// <remarks>引数は呼び出し側 (Service) で [0,1] に検証済みである前提。</remarks>
    /// <exception cref="CursorNotReadyException">local user / input がまだ準備できていない。</exception>
    Task<CursorStateSnapshot> SetPositionAsync(float x, float y, CancellationToken ct);

    /// <summary>現在のカーソル位置とウィンドウ解像度を読む (副作用なし)。</summary>
    /// <exception cref="CursorNotReadyException">local user / input がまだ準備できていない。</exception>
    Task<CursorStateSnapshot> GetPositionAsync(CancellationToken ct);
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
