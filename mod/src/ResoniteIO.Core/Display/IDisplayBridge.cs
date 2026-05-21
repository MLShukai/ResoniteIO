namespace ResoniteIO.Core.Display;

/// <summary>proto <c>DisplayConfig</c> / <c>DisplayState</c> から独立した Core 層 POCO。</summary>
/// <remarks>
/// 各 field の <c>0</c> は proto3 default = "engine 側で skip し変更しない" の
/// signal。Bridge は 0 でない field だけを書き込み、戻り snapshot には全 field
/// に actual 値を入れる。
/// </remarks>
public sealed record DisplayConfigSnapshot
{
    public uint Width { get; init; }

    public uint Height { get; init; }

    public float MaxFps { get; init; }
}

/// <summary>Mod 側 (Renderite) が実装し DI で注入する display 設定 read/write 抽象。</summary>
public interface IDisplayBridge
{
    /// <summary><paramref name="config"/> の 0 でない field を engine に書き込む。値は返さない。</summary>
    /// <remarks>
    /// engine 側の設定書き換えは <c>Settings.UpdateActiveSetting</c> が engine thread に
    /// 内部 dispatch するため、Apply 直後に現値を読み返しても適用前の snapshot が見える
    /// ケースがある。読み返しが必要な呼び出し側は Apply 完了後に <see cref="GetAsync"/>
    /// を別 RPC として呼ぶこと。
    /// </remarks>
    /// <exception cref="DisplayNotReadyException">engine がまだ制御不能 (renderer 未起動等)。</exception>
    Task ApplyAsync(DisplayConfigSnapshot config, CancellationToken ct);

    /// <summary>現在の display 設定の snapshot を engine から読む。</summary>
    /// <exception cref="DisplayNotReadyException">engine がまだ読めない状態。</exception>
    Task<DisplayConfigSnapshot> GetAsync(CancellationToken ct);
}

/// <summary>
/// Bridge が一時的に display を制御できない状態。Service 層は <c>FailedPrecondition</c>
/// に翻訳するので Client は時間を置いて retry できる。
/// </summary>
public sealed class DisplayNotReadyException : Exception
{
    public DisplayNotReadyException(string message)
        : base(message) { }

    public DisplayNotReadyException(string message, Exception innerException)
        : base(message, innerException) { }
}
