namespace ResoniteIO.Core.Display;

/// <summary>
/// proto <c>DisplayConfig</c> / <c>DisplayState</c> から独立した Core 層 POCO。
/// </summary>
/// <remarks>
/// <para>
/// "0 = 変更しない" のセマンティクスは proto と同じ: 各 field の <c>0</c> は
/// engine 側で当該設定を skip する signal として解釈する。Bridge 実装は
/// <see cref="Width"/> / <see cref="Height"/> / <see cref="MaxFps"/> のうち 0 でない
/// 値だけを engine に書き込み、戻りの snapshot には field 全てに actual 値を入れる。
/// </para>
/// </remarks>
public sealed record DisplayConfigSnapshot
{
    /// <summary>解像度幅 (pixel)。<c>0</c> は「変更しない」。</summary>
    public uint Width { get; init; }

    /// <summary>解像度高さ (pixel)。<c>0</c> は「変更しない」。</summary>
    public uint Height { get; init; }

    /// <summary>fps 上限 (<c>Application.targetFrameRate</c> 相当)。<c>0</c> は「変更しない」。</summary>
    public float MaxFps { get; init; }
}

/// <summary>
/// Mod 側 (Renderite) が実装し DI で注入する display 設定 read/write 抽象。
/// </summary>
/// <remarks>
/// <para>
/// 実装は engine の update tick 上にディスパッチする可能性が高い (Renderite の
/// Application.targetFrameRate 書き換え等は main thread を要求する)。本 IF は
/// 任意スレッドから呼ばれることを前提に <see cref="Task"/> 返り値とする。
/// </para>
/// </remarks>
public interface IDisplayBridge
{
    /// <summary>
    /// <paramref name="config"/> の 0 でない field を engine に適用し、適用後の現値
    /// snapshot を返す。
    /// </summary>
    /// <exception cref="DisplayNotReadyException">
    /// engine がまだ display を制御できる状態に無い (Renderite renderer 未起動等)。
    /// </exception>
    Task<DisplayConfigSnapshot> ApplyAsync(DisplayConfigSnapshot config, CancellationToken ct);

    /// <summary>現在の display 設定の snapshot を engine から読む。</summary>
    /// <exception cref="DisplayNotReadyException">
    /// engine がまだ display を読める状態に無い。
    /// </exception>
    Task<DisplayConfigSnapshot> GetAsync(CancellationToken ct);
}

/// <summary>
/// Bridge が一時的に display を制御できない状態。Service 層が
/// <c>Status.FailedPrecondition</c> に翻訳するため、Client は時間を置いて
/// retry できる (<see cref="Bridge.CameraNotReadyException"/> と同じ pattern)。
/// </summary>
public sealed class DisplayNotReadyException : Exception
{
    public DisplayNotReadyException(string message)
        : base(message) { }

    public DisplayNotReadyException(string message, Exception innerException)
        : base(message, innerException) { }
}
