using System.Runtime.InteropServices;
using Google.Protobuf;
using Grpc.Core;
using ResoniteIO.Core.Microphone;
using ResoniteIO.Core.Tests.Helpers;
using Xunit;
using V1 = ResoniteIO.V1;

namespace ResoniteIO.Core.Tests.Microphone;

/// <summary>
/// <see cref="Core.Microphone.MicrophoneService"/> の StreamAudio client-streaming
/// round-trip と disconnect 種別通知を SessionHost mount 越しに検証する。
/// SessionHostHarness が <c>RESONITE_IO_SOCKET</c> env を触るため
/// <c>SessionHostEnv</c> collection で直列化。
/// </summary>
[Collection("SessionHostEnv")]
public sealed class MicrophoneRoundTripTests
{
    [Fact]
    public async Task StreamAudio_AccumulatesFrames_AndReturnsSummary()
    {
        var bridge = new FakeMicrophoneBridge();
        await using var harness = await SessionHostHarness.StartAsync(microphoneBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Microphone.MicrophoneClient(channel);

        // 3 frame、それぞれ独自の sample 数 / frame_id / unix_nanos を持たせて
        // proto → Core POCO mapping と summary 集計を 1 ラウンドトリップで確認する。
        var frames = new[]
        {
            MakeProtoFrame(frameId: 0UL, sampleCount: 4, unixNanos: 1_000L, seed: 0.1f),
            MakeProtoFrame(frameId: 1UL, sampleCount: 8, unixNanos: 2_000L, seed: 0.2f),
            MakeProtoFrame(frameId: 2UL, sampleCount: 16, unixNanos: 3_000L, seed: 0.3f),
        };

        using var call = client.StreamAudio();
        foreach (var f in frames)
        {
            await call.RequestStream.WriteAsync(f);
        }
        await call.RequestStream.CompleteAsync();
        var summary = await call.ResponseAsync;

        Assert.Equal((long)frames.Length, summary.ReceivedFrames);
        Assert.Equal(4L + 8L + 16L, summary.ReceivedSamples);
        Assert.Equal(0L, summary.DroppedFrames);
        Assert.True(summary.UnixNanos > 0L);

        var received = bridge.Frames;
        Assert.Equal(frames.Length, received.Count);

        // proto → Core POCO の field mapping を全件 1 つずつ検証。順序保持も
        // ここで暗黙的に確認する (FakeMicrophoneBridge は受信順に append する)。
        for (var i = 0; i < frames.Length; i++)
        {
            var expected = frames[i];
            var actual = received[i];

            Assert.Equal((long)expected.FrameId, actual.FrameId);
            Assert.Equal(expected.UnixNanos, actual.UnixNanos);
            // Service は bytes 長から sample 数を再計算するため、proto.SampleCount
            // ではなく実 sample 数で一致する。
            Assert.Equal((int)expected.SampleCount, actual.SampleCount);
            Assert.Equal((int)expected.SampleCount, actual.Samples.Length);

            // bytes → float[] の解釈が変質していないことを sentinel pattern で検証。
            var expectedSamples = ToFloatArray(expected.Samples);
            Assert.Equal(expectedSamples, actual.Samples);
        }

        var disconnects = bridge.Disconnects;
        Assert.Single(disconnects);
        Assert.Equal(MicrophoneDisconnectReason.Graceful, disconnects[0]);
    }

    [Fact]
    public async Task StreamAudio_BridgeNull_ReturnsUnavailable()
    {
        await using var harness = await SessionHostHarness.StartAsync(microphoneBridge: null);
        using var channel = harness.CreateChannel();
        var client = new V1.Microphone.MicrophoneClient(channel);

        using var call = client.StreamAudio();

        // Server は MoveNext 前に Unavailable を返すため、RequestStream への
        // 書き込み / CompleteAsync / ResponseAsync のいずれかが RpcException を
        // 表面化する。Assert.ThrowsAsync が経路を吸収する。
        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
        {
            await call.RequestStream.WriteAsync(MakeProtoFrame(0UL, 4, 0L, 0f));
            await call.RequestStream.CompleteAsync();
            await call.ResponseAsync;
        });

        Assert.Equal(StatusCode.Unavailable, ex.StatusCode);
    }

    [Fact]
    public async Task StreamAudio_BridgeNotReady_ReturnsFailedPrecondition()
    {
        var bridge = new FakeMicrophoneBridge { ThrowNotReady = true };
        await using var harness = await SessionHostHarness.StartAsync(microphoneBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Microphone.MicrophoneClient(channel);

        using var call = client.StreamAudio();

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
        {
            await call.RequestStream.WriteAsync(MakeProtoFrame(0UL, 4, 0L, 0f));
            await call.RequestStream.CompleteAsync();
            await call.ResponseAsync;
        });

        Assert.Equal(StatusCode.FailedPrecondition, ex.StatusCode);

        // server-side completion は非同期なので poll で待つ。
        await TestPolling.WaitUntilAsync(
            () => bridge.Disconnects.Count > 0,
            TimeSpan.FromSeconds(5),
            "Bridge did not receive disconnect notification"
        );
        Assert.Equal(MicrophoneDisconnectReason.Errored, bridge.Disconnects[^1]);
    }

    [Fact]
    public async Task StreamAudio_BridgeGenericException_ReturnsInternal()
    {
        var bridge = new FakeMicrophoneBridge { ThrowGeneric = true };
        await using var harness = await SessionHostHarness.StartAsync(microphoneBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Microphone.MicrophoneClient(channel);

        using var call = client.StreamAudio();

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
        {
            await call.RequestStream.WriteAsync(MakeProtoFrame(0UL, 4, 0L, 0f));
            await call.RequestStream.CompleteAsync();
            await call.ResponseAsync;
        });

        Assert.Equal(StatusCode.Internal, ex.StatusCode);

        await TestPolling.WaitUntilAsync(
            () => bridge.Disconnects.Count > 0,
            TimeSpan.FromSeconds(5),
            "Bridge did not receive disconnect notification"
        );
        Assert.Equal(MicrophoneDisconnectReason.Errored, bridge.Disconnects[^1]);
    }

    [Fact]
    public async Task StreamAudio_ClientCancellation_NotifiesCancelledDisconnect()
    {
        var bridge = new FakeMicrophoneBridge();
        await using var harness = await SessionHostHarness.StartAsync(microphoneBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Microphone.MicrophoneClient(channel);

        using var cts = new CancellationTokenSource();
        using var call = client.StreamAudio(cancellationToken: cts.Token);

        await call.RequestStream.WriteAsync(MakeProtoFrame(0UL, 4, 1_000L, 0.1f));
        cts.Cancel();

        try
        {
            await call.ResponseAsync;
        }
        catch (OperationCanceledException) { }
        catch (RpcException ex) when (ex.StatusCode == StatusCode.Cancelled) { }

        // server-side completion は非同期なので poll で待つ。
        await TestPolling.WaitUntilAsync(
            () => bridge.Disconnects.Count > 0,
            TimeSpan.FromSeconds(5),
            "Bridge did not receive disconnect notification"
        );

        Assert.Equal(MicrophoneDisconnectReason.Cancelled, bridge.Disconnects[^1]);
    }

    private static V1.MicrophoneAudioFrame MakeProtoFrame(
        ulong frameId,
        int sampleCount,
        long unixNanos,
        float seed
    )
    {
        var samples = new float[sampleCount];
        for (var i = 0; i < sampleCount; i++)
        {
            // deterministic sentinel pattern: bytes ↔ float の解釈ズレを検出するのに十分。
            samples[i] = seed + (float)i;
        }
        var bytes = MemoryMarshal.AsBytes(samples.AsSpan()).ToArray();
        return new V1.MicrophoneAudioFrame
        {
            FrameId = frameId,
            UnixNanos = unixNanos,
            SampleCount = (uint)sampleCount,
            Samples = ByteString.CopyFrom(bytes),
        };
    }

    private static float[] ToFloatArray(ByteString bytes)
    {
        var span = bytes.Span;
        var count = span.Length / sizeof(float);
        var floats = new float[count];
        if (count > 0)
        {
            MemoryMarshal.Cast<byte, float>(span).CopyTo(floats);
        }
        return floats;
    }
}
