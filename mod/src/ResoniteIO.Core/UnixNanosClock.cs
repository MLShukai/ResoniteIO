namespace ResoniteIO.Core;

/// <summary>
/// Unix epoch (UTC 1970-01-01) からのナノ秒経過時間を返す共通 clock。
/// </summary>
/// <remarks>
/// 実効解像度は OS の system tick 依存 (Windows / Wine では実効 ~1ms)。
/// 戻り値が <see cref="long"/> (signed) なので 2262 年付近で overflow するが、本プロジェクトの
/// 寿命の範囲では問題にならない。
/// </remarks>
public static class UnixNanosClock
{
    /// <summary>現在時刻を Unix epoch からのナノ秒で返す。</summary>
    public static long Now() => (DateTimeOffset.UtcNow.UtcTicks - DateTime.UnixEpoch.Ticks) * 100L;
}
