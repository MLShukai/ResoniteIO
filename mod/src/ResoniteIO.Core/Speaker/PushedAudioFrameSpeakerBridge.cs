using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;
using System.Threading.Channels;

namespace ResoniteIO.Core.Speaker;

/// <summary>External-push 型の <see cref="ISpeakerBridge"/>。WASAPI tap が push、Service が pull。</summary>
/// <remarks>
/// <para>
/// 内部 channel は cap=32 + <c>DropWrite</c> で「容量超過時は新しい frame を捨てて
/// 古い frame の連続性を保つ」戦略を取る (audio drop は不可逆だが、最近 frame を
/// 落とした方が古い波形の continuity を壊さないため。実機で問題が出たら DropOldest
/// に切り替える余地は残す)。
/// </para>
/// <para>
/// <c>FrameId</c> は <see cref="Push"/> 内で monotonic 採番 (stream 開始時に 0 から)。
/// Service 側は再採番しない (Camera と異なる挙動なので注意)。
/// </para>
/// </remarks>
public sealed class PushedAudioFrameSpeakerBridge : ISpeakerBridge
{
    /// <summary>デフォルト channel 容量 (frame 数)。typical 1024-sample @ 48 kHz frame ≒ 21 ms/frame、32 frame ≒ 680 ms buffer。</summary>
    public const int DefaultCapacity = 32;

    private readonly Channel<AudioFrame> _channel;
    private long _frameId = -1;
    private int _disposed;

    public PushedAudioFrameSpeakerBridge(int capacity = DefaultCapacity)
    {
        if (capacity <= 0)
        {
            throw new ArgumentOutOfRangeException(
                nameof(capacity),
                capacity,
                "capacity must be positive."
            );
        }

        _channel = Channel.CreateBounded<AudioFrame>(
            new BoundedChannelOptions(capacity)
            {
                // DropWrite: channel が満杯のとき、これから書こうとする (新しい) frame を捨て、
                // 既に enqueue 済みの古い frame 群を残す。TryWrite は満杯でも false を返さず
                // true を返して捨てる (silent drop)。
                FullMode = BoundedChannelFullMode.DropWrite,
                SingleReader = false,
                SingleWriter = false,
            }
        );
    }

    /// <summary>
    /// WASAPI tap から受け取った interleaved (L, R) float32 buffer を <see cref="AudioFrame"/>
    /// に詰めて channel へ enqueue する。<paramref name="unixNanos"/> は tap 受信時刻。
    /// </summary>
    /// <returns>
    /// enqueue 成功なら <c>true</c>、dispose 済みなら <c>false</c>。channel が満杯で
    /// DropWrite された場合も <c>true</c> を返す (silent drop)。
    /// </returns>
    /// <exception cref="ArgumentException">
    /// <paramref name="buffer"/> の長さが奇数 (interleaved stereo として不整合) のとき。
    /// </exception>
    public bool Push(ReadOnlySpan<float> buffer, long unixNanos)
    {
        if (Volatile.Read(ref _disposed) != 0)
        {
            return false;
        }
        if ((buffer.Length % AudioFrame.ChannelCount) != 0)
        {
            throw new ArgumentException(
                $"Interleaved stereo buffer length must be even (got {buffer.Length}).",
                nameof(buffer)
            );
        }

        var sampleCount = buffer.Length / AudioFrame.ChannelCount;
        var byteSpan = MemoryMarshal.AsBytes(buffer);

        var id = Interlocked.Increment(ref _frameId);

        // Defensive copy: WASAPI buffer は callback 復帰後に engine 側で再利用される
        // 可能性があるため Channel に積む前に owned bytes へコピーする。
        var frame = new AudioFrame(
            Samples: byteSpan.ToArray(),
            SampleCount: sampleCount,
            UnixNanos: unixNanos,
            FrameId: id
        );

        // DropWrite なので満杯でも TryWrite は true を返す。false が返るのは
        // 既に Writer.Complete() 済みのとき。
        return _channel.Writer.TryWrite(frame);
    }

    /// <inheritdoc/>
    public async IAsyncEnumerable<AudioFrame> StreamFramesAsync(
        [EnumeratorCancellation] CancellationToken ct
    )
    {
        // ReadAllAsync は Dispose 後 (Writer.Complete) を正常終了として静かに抜ける。
        await foreach (var frame in _channel.Reader.ReadAllAsync(ct).ConfigureAwait(false))
        {
            yield return frame;
        }
    }

    public void Dispose()
    {
        if (Interlocked.Exchange(ref _disposed, 1) != 0)
        {
            return;
        }
        _channel.Writer.TryComplete();
    }

    /// <summary>frame 数 (テスト用)。</summary>
    internal int Count => _channel.Reader.Count;
}
