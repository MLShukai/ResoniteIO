using Grpc.Core;
using ResoniteIO.Core.Locomotion;
using ResoniteIO.Core.Tests.Common;
using ResoniteIO.Core.Tests.Common.Fakes;
using Xunit;
using V1 = ResoniteIO.V1;

namespace ResoniteIO.Core.Tests.Locomotion;

/// <summary>
/// <see cref="Core.Locomotion.LocomotionService"/> の Drive client-streaming
/// round-trip と disconnect 種別通知を SessionHost mount 越しに検証する。
/// SessionHostHarness が <c>RESONITE_IO_SOCKET</c> env を触るため
/// <c>SessionHostEnv</c> collection で直列化。
/// </summary>
[Collection("SessionHostEnv")]
public sealed class LocomotionRoundTripTests
{
    [Fact]
    public async Task Drive_RecordsLatestState_AndReturnsCount()
    {
        var bridge = new FakeLocomotionBridge();
        await using var harness = await SessionHostHarness.StartAsync(locomotionBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Locomotion.LocomotionClient(channel);

        // 全 field の proto → Core POCO mapping を 1 round-trip で確認する。
        var commands = new[]
        {
            new V1.LocomotionCommand { MoveY = 1.0f, UnixNanos = 1L },
            new V1.LocomotionCommand
            {
                MoveX = 1.0f,
                MoveY = 1.0f,
                Velocity = 3.0f,
                UnixNanos = 2L,
            },
            new V1.LocomotionCommand
            {
                YawRate = 0.5f,
                PitchRate = -0.25f,
                UnixNanos = 3L,
            },
            new V1.LocomotionCommand
            {
                Jump = true,
                Crouch = 0.75f,
                UnixNanos = 4L,
            },
        };

        using var call = client.Drive();
        foreach (var c in commands)
        {
            await call.RequestStream.WriteAsync(c);
        }
        await call.RequestStream.CompleteAsync();
        var summary = await call.ResponseAsync;

        Assert.Equal((long)commands.Length, summary.ReceivedCount);
        Assert.Equal(0L, summary.DroppedCount);
        Assert.True(summary.UnixNanos > 0L);

        var setStates = bridge.SetStates;
        Assert.Equal(commands.Length, setStates.Count);

        // Service は proto.Velocity を素のまま POCO に詰めるだけ (proto3 wire
        // default = 0)。convenience default=1.0 は Python `LocomotionCmd` 側で
        // 担保する設計のため、ここで 0 のまま見えるのは規約通り。
        Assert.Equal(1.0f, setStates[0].MoveY);
        Assert.Equal(0f, setStates[0].Velocity);
        Assert.Equal(1L, setStates[0].UnixNanos);

        Assert.Equal(1.0f, setStates[1].MoveX);
        Assert.Equal(1.0f, setStates[1].MoveY);
        Assert.Equal(3.0f, setStates[1].Velocity);

        Assert.Equal(0.5f, setStates[2].YawRate);
        Assert.Equal(-0.25f, setStates[2].PitchRate);

        Assert.True(setStates[3].Jump);
        Assert.Equal(0.75f, setStates[3].Crouch);

        var disconnects = bridge.Disconnects;
        Assert.Single(disconnects);
        Assert.Equal(LocomotionDisconnectReason.Graceful, disconnects[0]);
    }

    [Fact]
    public async Task Drive_ClientCancellation_NotifiesCancelledDisconnect()
    {
        var bridge = new FakeLocomotionBridge();
        await using var harness = await SessionHostHarness.StartAsync(locomotionBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Locomotion.LocomotionClient(channel);

        using var cts = new CancellationTokenSource();
        using var call = client.Drive(cancellationToken: cts.Token);

        await call.RequestStream.WriteAsync(new V1.LocomotionCommand { MoveY = 1.0f });
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

        Assert.Equal(LocomotionDisconnectReason.Cancelled, bridge.Disconnects[^1]);
    }

    [Fact]
    public async Task Drive_WithoutBridge_ReturnsUnavailable()
    {
        await using var harness = await SessionHostHarness.StartAsync(locomotionBridge: null);
        using var channel = harness.CreateChannel();
        var client = new V1.Locomotion.LocomotionClient(channel);

        using var call = client.Drive();

        // Server は MoveNext 前に Unavailable を返すため、RequestStream への
        // 書き込み / CompleteAsync / ResponseAsync のいずれかが RpcException を
        // 表面化する。Assert.ThrowsAsync が経路を吸収する。
        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
        {
            await call.RequestStream.WriteAsync(new V1.LocomotionCommand());
            await call.RequestStream.CompleteAsync();
            await call.ResponseAsync;
        });

        Assert.Equal(StatusCode.Unavailable, ex.StatusCode);
    }
}
