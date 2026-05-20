using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;
using ResoniteIO.Core.Speaker;

namespace ResoniteIO.Core.Tests.Helpers;

/// <summary>
/// テスト用 <see cref="ISpeakerBridge"/>. 構成可能な frame シーケンスを yield する。
/// </summary>
/// <remarks>
/// <list type="bullet">
/// <item><see cref="ThrowNotReady"/> = <c>true</c> なら最初の enumeration で
/// <see cref="SpeakerNotReadyException"/> を投げる。</item>
/// <item><see cref="ThrowGeneric"/> = <c>true</c> なら最初の enumeration で
/// 一般例外を投げる (Service が <c>Internal</c> に翻訳する経路の検証用)。</item>
/// <item>それ以外なら <see cref="Frames"/> を順に yield して enumeration を終える
/// (channel.Complete に相当する正常 end-of-stream)。</item>
/// </list>
/// </remarks>
internal sealed class FakeSpeakerBridge : ISpeakerBridge
{
    public List<AudioFrame> Frames { get; } = new();
    public bool ThrowNotReady { get; set; }
    public bool ThrowGeneric { get; set; }

    public bool Disposed { get; private set; }

    public static AudioFrame MakeFrame(long frameId, int sampleCount = 4, long unixNanos = 0L)
    {
        var floats = new float[sampleCount * AudioFrame.ChannelCount];
        for (var i = 0; i < floats.Length; i++)
        {
            // deterministic sentinel pattern
            floats[i] = (float)i + ((float)frameId * 0.01f);
        }
        var bytes = MemoryMarshal.AsBytes(floats.AsSpan()).ToArray();
        return new AudioFrame(
            Samples: bytes,
            SampleCount: sampleCount,
            UnixNanos: unixNanos == 0L ? 1_700_000_000_000_000_000L + frameId : unixNanos,
            FrameId: frameId
        );
    }

#pragma warning disable CS1998 // async without await: yield 前に throw する制御パスを通すため。
    public async IAsyncEnumerable<AudioFrame> StreamFramesAsync(
        [EnumeratorCancellation] CancellationToken ct
    )
    {
        if (ThrowNotReady)
        {
            throw new SpeakerNotReadyException("FakeSpeakerBridge: simulated not-ready state.");
        }
        if (ThrowGeneric)
        {
            throw new InvalidOperationException("FakeSpeakerBridge: simulated faulted state.");
        }

        foreach (var frame in Frames)
        {
            ct.ThrowIfCancellationRequested();
            yield return frame;
        }
    }
#pragma warning restore CS1998

    public void Dispose() => Disposed = true;
}
