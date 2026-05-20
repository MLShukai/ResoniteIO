namespace ResoniteIO.Core.Camera;

/// <summary>
/// Mod 側 (FrooxEngine) が実装し DI で注入する映像フレーム取得抽象。
/// </summary>
/// <remarks>
/// <see cref="CaptureAsync"/> は任意スレッドから呼ばれる。engine update tick への
/// dispatch が必要なら実装側で隠蔽する。
/// </remarks>
public interface ICameraBridge
{
    /// <summary>
    /// 1 フレームをキャプチャする。pixels は <see cref="CameraFrameFormat.Rgba8"/> 時
    /// row 0 = 画像上端 (top-left origin) で返すことを Bridge IF レベルの契約とする。
    /// </summary>
    /// <exception cref="CameraNotReadyException">
    /// engine がまだフレームを返せる状態に無い (LocalUser 未生成、world 切り替え中等)。
    /// </exception>
    Task<CameraFrame> CaptureAsync(int width, int height, CancellationToken ct);
}

/// <summary>proto 生成型 <c>V1.CameraFrame</c> から独立した Core 層 POCO。</summary>
public readonly record struct CameraFrame(
    byte[] Pixels,
    int Width,
    int Height,
    long UnixNanos,
    long FrameId,
    CameraFrameFormat Format
);

public enum CameraFrameFormat
{
    Unspecified = 0,

    /// <summary>1 ピクセル 4 byte (R, G, B, A の順)、row 0 = 画像上端 (top-left origin)。</summary>
    Rgba8 = 1,
}

/// <summary>
/// Bridge が一時的にフレームを返せない状態。Service 層が
/// <c>Status.FailedPrecondition</c> に翻訳するため、Client は再 stream で retry できる。
/// </summary>
public sealed class CameraNotReadyException : Exception
{
    public CameraNotReadyException(string message)
        : base(message) { }

    public CameraNotReadyException(string message, Exception innerException)
        : base(message, innerException) { }
}
