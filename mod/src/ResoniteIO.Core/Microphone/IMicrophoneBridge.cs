namespace ResoniteIO.Core.Microphone;

/// <summary>
/// Mod 側 (FrooxEngine) が実装し DI で注入する Microphone (virtual capture device)
/// 注入抽象。
/// </summary>
/// <remarks>
/// <para>
/// push 型: Service が <see cref="SubmitFrame"/> で受信した音声 frame を Bridge
/// 内部 ring buffer に append し、engine tick で <c>WriteSamples&lt;MonoSample&gt;</c>
/// 経由で voice 配信ストリームへ流す (Speaker は engine → Python の pull-from-channel
/// 型なので 1:1 対称ではない)。
/// </para>
/// <para>
/// 本契約は **任意スレッドから呼ばれる**。engine thread への dispatch は実装側で
/// 隠蔽する。precondition 失敗 (engine の AudioSystem 未初期化等) のうち
/// 永続性のあるものは <see cref="MicrophoneNotReadyException"/> を投げ、Service が
/// <c>FailedPrecondition</c> に翻訳して client に retry を促す。
/// </para>
/// <para>
/// sample format は **固定**: 48 kHz / Mono / float32 LE。<see cref="MicrophoneFrame.Samples"/>
/// は Service 層で proto bytes から defensive copy された <c>float[]</c> で、Bridge が
/// 長期保有してよい (proto buffer の再利用と衝突しない)。
/// </para>
/// </remarks>
public interface IMicrophoneBridge
{
    /// <summary>
    /// 受信した frame を Bridge state に push する。任意スレッド safe。
    /// 永続的な precondition 失敗時のみ <see cref="MicrophoneNotReadyException"/>
    /// を投げる (transient 状態は実装内で吸収する)。
    /// </summary>
    void SubmitFrame(MicrophoneFrame frame);

    /// <summary>
    /// gRPC StreamAudio stream の終了種別を通知する。
    /// <see cref="MicrophoneDisconnectReason.Graceful"/> は ring buffer を維持
    /// (再生中の余韻を切らない)、それ以外は Bridge 側で ring buffer を safety
    /// reset する。本メソッドは must not throw — Service 側は本契約を信頼して
    /// ガードしない。
    /// </summary>
    void NotifyDisconnect(MicrophoneDisconnectReason reason);
}

/// <summary>proto 生成型 <c>V1.MicrophoneAudioFrame</c> から独立した Core 層 POCO。</summary>
/// <remarks>
/// <para>
/// <see cref="Samples"/> は mono の float32 sample 列 (length = <see cref="SampleCount"/>)。
/// Service 層で proto <c>bytes</c> から defensive copy 済みのため Bridge が長期保有
/// してよい。
/// </para>
/// <para>各 field の semantics は <c>proto/resonite_io/v1/microphone.proto</c>。</para>
/// </remarks>
public readonly record struct MicrophoneFrame(
    float[] Samples,
    int SampleCount,
    long UnixNanos,
    long FrameId
)
{
    /// <summary>固定 channel 数 (mono)。proto も同じ値で固定。</summary>
    public const int ChannelCount = 1;

    /// <summary>固定 sample rate (Hz)。proto に negotiation を持たない。</summary>
    public const int SampleRate = 48_000;
}

/// <summary>
/// <see cref="IMicrophoneBridge.NotifyDisconnect"/> に渡される stream 終了種別。
/// </summary>
public enum MicrophoneDisconnectReason
{
    /// <summary>client が <c>CompleteAsync</c> で stream を正常終了。ring buffer 維持。</summary>
    Graceful,

    /// <summary>UDS 切断 / client cancel / deadline 超過。ring buffer を reset。</summary>
    Cancelled,

    /// <summary>Bridge 内部 / Service 内部の予期せぬ例外。ring buffer を reset。</summary>
    Errored,
}
