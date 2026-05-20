using System.Runtime.InteropServices;
using ResoniteIO.Core.Speaker;
using Xunit;

namespace ResoniteIO.Core.Tests.Speaker;

/// <summary>
/// <see cref="PushedAudioFrameSpeakerBridge"/> の push / consume 順序、frame_id 採番、
/// 容量超過時の <c>DropWrite</c> 戦略、dispose の idempotency を検証する。
/// </summary>
public sealed class PushedAudioFrameSpeakerBridgeTests
{
    private static float[] MakeBuffer(int sampleCount, float seed = 0f)
    {
        // interleaved stereo: length = sampleCount * 2
        var floats = new float[sampleCount * AudioFrame.ChannelCount];
        for (var i = 0; i < floats.Length; i++)
        {
            floats[i] = seed + i;
        }
        return floats;
    }

    private static async Task<List<AudioFrame>> CollectAsync(
        PushedAudioFrameSpeakerBridge bridge,
        int expected,
        TimeSpan timeout
    )
    {
        var result = new List<AudioFrame>();
        using var cts = new CancellationTokenSource(timeout);
        try
        {
            await foreach (var f in bridge.StreamFramesAsync(cts.Token))
            {
                result.Add(f);
                if (result.Count >= expected)
                {
                    break;
                }
            }
        }
        catch (OperationCanceledException) { }
        return result;
    }

    [Fact]
    public async Task Push_one_then_consume_yields_that_frame_with_frame_id_zero()
    {
        using var bridge = new PushedAudioFrameSpeakerBridge();
        var buffer = MakeBuffer(sampleCount: 8);

        Assert.True(bridge.Push(buffer, unixNanos: 12345L));

        var frames = await CollectAsync(bridge, expected: 1, TimeSpan.FromSeconds(2));

        Assert.Single(frames);
        var frame = frames[0];
        Assert.Equal(0L, frame.FrameId);
        Assert.Equal(12345L, frame.UnixNanos);
        Assert.Equal(8, frame.SampleCount);
        // sample_count * channels * sizeof(float) = 8 * 2 * 4 = 64
        Assert.Equal(64, frame.Samples.Length);

        // round-trip bytes equality (LE on x64 / arm64 — both supported targets)
        var expectedBytes = MemoryMarshal.AsBytes(buffer.AsSpan()).ToArray();
        Assert.Equal(expectedBytes, frame.Samples);
    }

    [Fact]
    public async Task Push_multiple_preserves_FIFO_order_and_monotonic_frame_ids()
    {
        using var bridge = new PushedAudioFrameSpeakerBridge();

        Assert.True(bridge.Push(MakeBuffer(2, seed: 0f), unixNanos: 100L));
        Assert.True(bridge.Push(MakeBuffer(2, seed: 100f), unixNanos: 200L));
        Assert.True(bridge.Push(MakeBuffer(2, seed: 200f), unixNanos: 300L));

        var frames = await CollectAsync(bridge, expected: 3, TimeSpan.FromSeconds(2));

        Assert.Equal(3, frames.Count);
        Assert.Equal(new long[] { 0L, 1L, 2L }, frames.Select(f => f.FrameId).ToArray());
        Assert.Equal(new long[] { 100L, 200L, 300L }, frames.Select(f => f.UnixNanos).ToArray());
    }

    [Fact]
    public async Task Capacity_overflow_drops_newest_writes_keeping_old_frames()
    {
        // cap=2: 3 個 push すると 3 個目が DropWrite で silent drop される。
        // consumer 側には最初の 2 frame (FrameId 0, 1) だけが流れる。
        // 注意: FrameId 採番は Push 内で常に行われる (drop されても採番されるかは
        // 実装の詳細だが、本実装では _frameId Increment が POCO 構築の前に
        // 走るため drop された frame_id は欠番になる)。consumer に見える FrameId は
        // 0, 1 のみ。
        using var bridge = new PushedAudioFrameSpeakerBridge(capacity: 2);

        Assert.True(bridge.Push(MakeBuffer(1, seed: 0f), unixNanos: 1L));
        Assert.True(bridge.Push(MakeBuffer(1, seed: 100f), unixNanos: 2L));
        // 3 個目は DropWrite で捨てられるが、API contract 上 TryWrite は true を返す。
        Assert.True(bridge.Push(MakeBuffer(1, seed: 200f), unixNanos: 3L));

        var frames = await CollectAsync(bridge, expected: 2, TimeSpan.FromSeconds(2));

        Assert.Equal(2, frames.Count);
        Assert.Equal(0L, frames[0].FrameId);
        Assert.Equal(1L, frames[1].FrameId);
        Assert.Equal(1L, frames[0].UnixNanos);
        Assert.Equal(2L, frames[1].UnixNanos);

        // 3 個目以降が流れてこないことを短い timeout で確認する。
        using var cts = new CancellationTokenSource(TimeSpan.FromMilliseconds(100));
        var extra = 0;
        try
        {
            await foreach (var _ in bridge.StreamFramesAsync(cts.Token))
            {
                extra++;
            }
        }
        catch (OperationCanceledException) { }
        Assert.Equal(0, extra);
    }

    [Fact]
    public async Task Dispose_completes_channel_and_consumer_exits()
    {
        var bridge = new PushedAudioFrameSpeakerBridge();
        Assert.True(bridge.Push(MakeBuffer(1, seed: 0f), unixNanos: 1L));

        var collected = new List<AudioFrame>();
        var consumeTask = Task.Run(async () =>
        {
            await foreach (var f in bridge.StreamFramesAsync(CancellationToken.None))
            {
                collected.Add(f);
            }
        });

        // 1 個目が読まれたあと dispose で channel complete → consumer が自然終了する。
        await Task.Delay(50);
        bridge.Dispose();

        await consumeTask.WaitAsync(TimeSpan.FromSeconds(2));

        Assert.Single(collected);
        Assert.Equal(0L, collected[0].FrameId);
    }

    [Fact]
    public void Dispose_is_idempotent()
    {
        var bridge = new PushedAudioFrameSpeakerBridge();
        bridge.Dispose();
        // 2 回目以降は no-op (例外なし)。
        bridge.Dispose();
        bridge.Dispose();
    }

    [Fact]
    public void Push_after_dispose_returns_false()
    {
        var bridge = new PushedAudioFrameSpeakerBridge();
        bridge.Dispose();

        Assert.False(bridge.Push(MakeBuffer(1, seed: 0f), unixNanos: 1L));
    }

    [Fact]
    public void Push_with_odd_length_buffer_throws_ArgumentException()
    {
        using var bridge = new PushedAudioFrameSpeakerBridge();
        // 奇数長 (interleaved stereo として不整合) は defensive に弾く。
        var oddBuffer = new float[] { 1f, 2f, 3f };

        var ex = Assert.Throws<ArgumentException>(() => bridge.Push(oddBuffer, unixNanos: 1L));
        Assert.Equal("buffer", ex.ParamName);
    }

    [Fact]
    public void Constructor_rejects_non_positive_capacity()
    {
        Assert.Throws<ArgumentOutOfRangeException>(() =>
            new PushedAudioFrameSpeakerBridge(capacity: 0)
        );
        Assert.Throws<ArgumentOutOfRangeException>(() =>
            new PushedAudioFrameSpeakerBridge(capacity: -1)
        );
    }

    [Fact]
    public async Task Consumer_cancellation_propagates_OperationCanceledException()
    {
        using var bridge = new PushedAudioFrameSpeakerBridge();
        using var cts = new CancellationTokenSource();

        var consumeTask = Task.Run(async () =>
        {
            await foreach (var _ in bridge.StreamFramesAsync(cts.Token)) { }
        });

        cts.Cancel();
        // TaskCanceledException も OperationCanceledException 派生で受ける。
        await Assert.ThrowsAnyAsync<OperationCanceledException>(async () =>
            await consumeTask.WaitAsync(TimeSpan.FromSeconds(2))
        );
    }
}
