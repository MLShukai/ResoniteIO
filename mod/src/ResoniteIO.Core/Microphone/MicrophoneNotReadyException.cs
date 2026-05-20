namespace ResoniteIO.Core.Microphone;

/// <summary>
/// Bridge が一時的に audio frame を受け取れない状態 (AudioSystem 未初期化、
/// virtual AudioInput 登録失敗等)。Service が <c>FailedPrecondition</c> に翻訳し
/// client は時間を置いて再 stream すれば良い。
/// </summary>
public sealed class MicrophoneNotReadyException : Exception
{
    public MicrophoneNotReadyException(string message)
        : base(message) { }

    public MicrophoneNotReadyException(string message, Exception innerException)
        : base(message, innerException) { }
}
