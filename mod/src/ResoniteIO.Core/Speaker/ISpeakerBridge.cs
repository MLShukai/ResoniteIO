namespace ResoniteIO.Core.Speaker;

/// <summary>
/// Mod 側 (FrooxEngine) が実装し DI で注入する Speaker (final audio mix) 取得抽象。
/// </summary>
/// <remarks>
/// <para>
/// Camera と異なり push 型: WASAPI audio thread から engine が tap で受け取った
/// final mix が Bridge 内部 channel に push される。Service は
/// <see cref="StreamFramesAsync"/> を <c>await foreach</c> で消費する。
/// </para>
/// <para>
/// <c>FrameId</c> は Bridge 側で stream 開始から monotonic に採番する
/// (Camera Service の proto <c>frame_id</c> 再採番とは異なり、Service は再採番しない)。
/// 例外契約: Bridge は基本的に例外を投げず、未準備時は frame を yield しない
/// (consumer は cancel か dispose で抜ける)。engine 側 audio system が
/// 永続的に死んだ等の致命的状態のみ <see cref="SpeakerNotReadyException"/>
/// を投げる (Service が <c>FailedPrecondition</c> に翻訳して client が retry)。
/// </para>
/// </remarks>
public interface ISpeakerBridge : IDisposable
{
    /// <summary>
    /// Bridge 内部 channel に蓄積された <see cref="AudioFrame"/> を順に yield する。
    /// channel が complete されたら enumeration も終了する。
    /// </summary>
    IAsyncEnumerable<AudioFrame> StreamFramesAsync(CancellationToken ct);
}

/// <summary>
/// proto 生成型 <c>V1.AudioFrame</c> から独立した Core 層 POCO。
/// <para>
/// <c>Samples</c> は <see cref="ChannelCount"/> 個ずつのインターリーブ stereo として
/// float32 LE bytes を保持する (length = <c>SampleCount</c> * <see cref="ChannelCount"/>
/// * 4)。bytes に encode 済みなのは WASAPI tap で float[] から ReadOnlySpan&lt;byte&gt;
/// 経由でゼロアロケ寄りにコピーするため。
/// </para>
/// </summary>
public readonly record struct AudioFrame(
    byte[] Samples,
    int SampleCount,
    long UnixNanos,
    long FrameId
)
{
    /// <summary>固定 channel 数 (stereo)。proto も同じ値で固定。</summary>
    public const int ChannelCount = 2;

    /// <summary>固定 sample rate (Hz)。proto に negotiation を持たない。</summary>
    public const int SampleRate = 48_000;
}
