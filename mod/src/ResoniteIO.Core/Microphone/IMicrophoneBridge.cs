namespace ResoniteIO.Core.Microphone;

/// <summary>
/// Mod 側 (FrooxEngine) が実装し DI で注入する virtual capture device 抽象。
/// </summary>
/// <remarks>
/// <para>
/// 契約: <see cref="SubmitFrame"/> / <see cref="NotifyDisconnect"/> は任意スレッド
/// から呼ばれる (gRPC server thread)。engine thread への dispatch は実装側で隠蔽する。
/// </para>
/// <para>
/// Sample format は固定: 48 kHz / Mono / float32 LE。
/// <see cref="MicrophoneFrame.Samples"/> は Service 層が proto bytes から defensive
/// copy 済みなので Bridge が長期保有してよい。
/// </para>
/// </remarks>
public interface IMicrophoneBridge
{
    /// <summary>
    /// 受信した frame を Bridge state に push する。任意スレッド safe。
    /// 永続的な precondition 失敗 (engine の AudioSystem 未初期化等) のときに限り
    /// <see cref="MicrophoneNotReadyException"/> を投げる; transient 状態は実装内で吸収する。
    /// </summary>
    void SubmitFrame(MicrophoneFrame frame);

    /// <summary>
    /// gRPC StreamAudio stream の終了種別を通知する。Graceful は ring buffer 維持
    /// (再生中の余韻を切らない)、それ以外は ring buffer を safety reset する。
    /// </summary>
    /// <remarks>
    /// 契約上 **must not throw** — Service 側は本メソッドをガードせず呼ぶ。
    /// </remarks>
    void NotifyDisconnect(MicrophoneDisconnectReason reason);
}

/// <summary>
/// proto 生成型 <c>V1.MicrophoneAudioFrame</c> から独立した Core 層 POCO。
/// 各 field の semantics は <c>proto/resonite_io/v1/microphone.proto</c> が一次正典。
/// </summary>
public readonly record struct MicrophoneFrame(
    float[] Samples,
    int SampleCount,
    long UnixNanos,
    long FrameId
)
{
    /// <summary>固定 channel 数 (mono)。proto も同値で固定。</summary>
    public const int ChannelCount = 1;

    /// <summary>固定 sample rate (Hz)。proto に negotiation を持たない。</summary>
    public const int SampleRate = 48_000;
}

/// <summary><see cref="IMicrophoneBridge.NotifyDisconnect"/> に渡す stream 終了種別。</summary>
public enum MicrophoneDisconnectReason
{
    /// <summary>client が <c>CompleteAsync</c> で正常終了。ring buffer 維持。</summary>
    Graceful,

    /// <summary>UDS 切断 / client cancel / deadline 超過。ring buffer を reset。</summary>
    Cancelled,

    /// <summary>Bridge / Service 側の予期せぬ例外。ring buffer を reset。</summary>
    Errored,
}
