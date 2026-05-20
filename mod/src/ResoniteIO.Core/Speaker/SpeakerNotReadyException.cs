namespace ResoniteIO.Core.Speaker;

/// <summary>
/// Bridge が一時的に audio frame を返せない状態 (engine の AudioSystem 未初期化、
/// 対象 AudioOutputDriver の解決失敗等)。Service 層が <c>Status.FailedPrecondition</c>
/// に翻訳するため、Client は時間を置いて再 stream で retry できる。
/// </summary>
public sealed class SpeakerNotReadyException : Exception
{
    public SpeakerNotReadyException(string message)
        : base(message) { }

    public SpeakerNotReadyException(string message, Exception innerException)
        : base(message, innerException) { }
}
