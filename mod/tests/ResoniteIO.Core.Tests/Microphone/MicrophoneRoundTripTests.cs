using System.Runtime.InteropServices;
using Google.Protobuf;
using Grpc.Core;
using ResoniteIO.Core.Microphone;
using ResoniteIO.Core.Tests.Common;
using ResoniteIO.Core.Tests.Common.Fakes;
using Xunit;
using V1 = ResoniteIO.V1;

namespace ResoniteIO.Core.Tests.Microphone;

/// <summary>
/// <see cref="Core.Microphone.MicrophoneService"/> の StreamAudio round-trip と
/// disconnect 種別通知を GrpcHost mount 越しに検証する。
/// </summary>
/// <remarks>
/// <c>GrpcHostHarness</c> が <c>RESONITE_IO_SOCKET</c> env を触るので
/// <c>GrpcHostEnv</c> collection で直列化する (他モダリティと同 pattern)。
/// </remarks>
[Collection("GrpcHostEnv")]
public sealed class MicrophoneRoundTripTests
{
    [Fact]
    public async Task StreamAudio_AccumulatesFrames_AndReturnsSummary()
    {
        var bridge = new FakeMicrophoneBridge();
        await using var harness = await GrpcHostHarness.StartAsync(microphoneBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Microphone.MicrophoneClient(channel);

        // 3 frame で proto → Core POCO mapping と summary 集計を 1 経路で検証する。
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

        // 順序保持は FakeMicrophoneBridge の append-only 性で暗黙的に検証される。
        for (var i = 0; i < frames.Length; i++)
        {
            var expected = frames[i];
            var actual = received[i];

            Assert.Equal((long)expected.FrameId, actual.FrameId);
            Assert.Equal(expected.UnixNanos, actual.UnixNanos);
            // Service は proto.SampleCount を信用せず bytes 長から再計算するので
            // ここでは実 sample 数が一致することだけを assert する。
            Assert.Equal((int)expected.SampleCount, actual.SampleCount);
            Assert.Equal((int)expected.SampleCount, actual.Samples.Length);

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
        await using var harness = await GrpcHostHarness.StartAsync(microphoneBridge: null);
        using var channel = harness.CreateChannel();
        var client = new V1.Microphone.MicrophoneClient(channel);

        using var call = client.StreamAudio();

        // Server は MoveNext 前に Unavailable を返すので Write / Complete /
        // ResponseAsync のいずれが RpcException を表面化するかは経路依存。
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
        await using var harness = await GrpcHostHarness.StartAsync(microphoneBridge: bridge);
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

        // Service の NotifyDisconnect は client の RpcException 受信より後に走る。
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
        await using var harness = await GrpcHostHarness.StartAsync(microphoneBridge: bridge);
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

        // 非同期な server-side NotifyDisconnect を poll で待つ。
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
        await using var harness = await GrpcHostHarness.StartAsync(microphoneBridge: bridge);
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
        // Distinct values per index so a bytes ↔ float reinterpret bug is detectable.
        var samples = new float[sampleCount];
        for (var i = 0; i < sampleCount; i++)
        {
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
