using Grpc.Core;
using ResoniteIO.Core.Tests.Common;
using ResoniteIO.Core.Tests.Common.Fakes;
using ResoniteIO.V1;
using Xunit;

namespace ResoniteIO.Core.Tests.Speaker;

// SessionHostHarness は RESONITE_IO_SOCKET env var を書き換えるため、SessionHostEnv
// collection 内で直列化する。
[Collection("SessionHostEnv")]
public sealed class SpeakerRoundTripTests
{
    [Fact]
    public async Task Stream_returns_Unavailable_when_bridge_not_configured()
    {
        await using var harness = await SessionHostHarness.StartAsync(speakerBridge: null);
        using var channel = harness.CreateChannel();
        var client = new V1.Speaker.SpeakerClient(channel);

        using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        using var call = client.StreamAudio(
            new SpeakerStreamRequest(),
            cancellationToken: cts.Token
        );

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
        {
            await foreach (var _ in call.ResponseStream.ReadAllAsync(cts.Token)) { }
        });
        Assert.Equal(StatusCode.Unavailable, ex.StatusCode);
    }

    [Fact]
    public async Task Stream_translates_SpeakerNotReadyException_to_FailedPrecondition()
    {
        var bridge = new FakeSpeakerBridge { ThrowNotReady = true };
        await using var harness = await SessionHostHarness.StartAsync(speakerBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Speaker.SpeakerClient(channel);

        using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        using var call = client.StreamAudio(
            new SpeakerStreamRequest(),
            cancellationToken: cts.Token
        );

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
        {
            await foreach (var _ in call.ResponseStream.ReadAllAsync(cts.Token)) { }
        });
        Assert.Equal(StatusCode.FailedPrecondition, ex.StatusCode);
    }

    [Fact]
    public async Task Stream_translates_generic_bridge_exception_to_Internal()
    {
        var bridge = new FakeSpeakerBridge { ThrowGeneric = true };
        await using var harness = await SessionHostHarness.StartAsync(speakerBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Speaker.SpeakerClient(channel);

        using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        using var call = client.StreamAudio(
            new SpeakerStreamRequest(),
            cancellationToken: cts.Token
        );

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
        {
            await foreach (var _ in call.ResponseStream.ReadAllAsync(cts.Token)) { }
        });
        Assert.Equal(StatusCode.Internal, ex.StatusCode);
    }

    [Fact]
    public async Task Stream_relays_bridge_frames_with_frame_id_and_samples_preserved()
    {
        var bridge = new FakeSpeakerBridge();
        bridge.Frames.Add(
            FakeSpeakerBridge.MakeFrame(frameId: 0L, sampleCount: 4, unixNanos: 1_000L)
        );
        bridge.Frames.Add(
            FakeSpeakerBridge.MakeFrame(frameId: 1L, sampleCount: 4, unixNanos: 2_000L)
        );
        bridge.Frames.Add(
            FakeSpeakerBridge.MakeFrame(frameId: 2L, sampleCount: 4, unixNanos: 3_000L)
        );

        await using var harness = await SessionHostHarness.StartAsync(speakerBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Speaker.SpeakerClient(channel);

        using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        using var call = client.StreamAudio(
            new SpeakerStreamRequest(),
            cancellationToken: cts.Token
        );

        var received = new List<AudioFrame>();
        await foreach (var frame in call.ResponseStream.ReadAllAsync(cts.Token))
        {
            received.Add(frame);
            if (received.Count >= 3)
            {
                break;
            }
        }

        Assert.Equal(3, received.Count);
        for (var i = 0; i < received.Count; i++)
        {
            var actual = received[i];
            var expected = bridge.Frames[i];

            // Service は frame_id を再採番しない (Bridge 側で stamp 済み)。
            Assert.Equal((ulong)expected.FrameId, actual.FrameId);
            Assert.Equal(expected.UnixNanos, actual.UnixNanos);
            Assert.Equal((uint)expected.SampleCount, actual.SampleCount);
            // samples = sample_count * 2 (ch) * 4 (bytes) で長さ一致。
            Assert.Equal(expected.SampleCount * 2 * 4, actual.Samples.Length);
            Assert.Equal(expected.Samples, actual.Samples.ToByteArray());
        }
    }
}
