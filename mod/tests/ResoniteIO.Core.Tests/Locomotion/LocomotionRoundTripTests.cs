using Grpc.Core;
using ResoniteIO.Core.Tests.Helpers;
using ResoniteIO.V1;
using Xunit;

namespace ResoniteIO.Core.Tests.Locomotion;

/// <summary>
/// <see cref="Core.Locomotion.LocomotionService"/> の Drive client-streaming
/// round-trip と例外翻訳を SessionHost mount 越しに検証する。
/// </summary>
/// <remarks>
/// SessionHostHarness が <c>RESONITE_IO_SOCKET</c> env var を書き換えるため、
/// xunit collection <c>SessionHostEnv</c> で他テストと直列化する。
/// </remarks>
[Collection("SessionHostEnv")]
public sealed class LocomotionRoundTripTests
{
    [Fact]
    public async Task Drive_AppliesEachCommand_AndReturnsCount()
    {
        var bridge = new FakeLocomotionBridge();
        await using var harness = await SessionHostHarness.StartAsync(locomotionBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Locomotion.LocomotionClient(channel);

        // 移動 + velocity override + look + jump + crouch を 1 ケースで一通り
        // 覆って proto → Core POCO へのマッピングを検証する。
        var commands = new[]
        {
            new LocomotionCommand { MoveY = 1.0f, UnixNanos = 1L },
            new LocomotionCommand
            {
                MoveX = 1.0f,
                MoveY = 1.0f,
                Velocity = 3.0f,
                UnixNanos = 2L,
            },
            new LocomotionCommand
            {
                YawRate = 0.5f,
                PitchRate = -0.25f,
                UnixNanos = 3L,
            },
            new LocomotionCommand
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

        var received = bridge.Received;
        Assert.Equal(commands.Length, received.Count);

        // Default Velocity (0f) must round-trip unchanged: Bridge-side
        // 0→1.0 reinterpretation is the engine bridge's responsibility,
        // not the Service's, so the proto3 default has to reach Apply intact.
        Assert.Equal(1.0f, received[0].MoveY);
        Assert.Equal(0f, received[0].Velocity);
        Assert.Equal(1L, received[0].UnixNanos);

        Assert.Equal(1.0f, received[1].MoveX);
        Assert.Equal(1.0f, received[1].MoveY);
        Assert.Equal(3.0f, received[1].Velocity);

        Assert.Equal(0.5f, received[2].YawRate);
        Assert.Equal(-0.25f, received[2].PitchRate);

        Assert.True(received[3].Jump);
        Assert.Equal(0.75f, received[3].Crouch);
    }

    [Fact]
    public async Task Drive_TranslatesNotReady_ToFailedPrecondition()
    {
        var bridge = new FakeLocomotionBridge { ThrowNotReady = true };
        await using var harness = await SessionHostHarness.StartAsync(locomotionBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Locomotion.LocomotionClient(channel);

        using var call = client.Drive();
        await call.RequestStream.WriteAsync(new LocomotionCommand { MoveY = 1.0f });

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
        {
            // Drive completes via response. Either the next WriteAsync or
            // ResponseAsync will surface the FailedPrecondition status, so we
            // attempt CompleteAsync first and fall back to ResponseAsync.
            try
            {
                await call.RequestStream.CompleteAsync();
            }
            catch (RpcException)
            {
                throw;
            }
            await call.ResponseAsync;
        });

        Assert.Equal(StatusCode.FailedPrecondition, ex.StatusCode);
        Assert.Empty(bridge.Received);
    }

    [Fact]
    public async Task Drive_WithoutBridge_ReturnsUnavailable()
    {
        // locomotionBridge=null で起動 → LocomotionService は mount されるが、
        // bridge 未注入なので Drive を開始した時点で Unavailable に終わる。
        await using var harness = await SessionHostHarness.StartAsync(locomotionBridge: null);
        using var channel = harness.CreateChannel();
        var client = new V1.Locomotion.LocomotionClient(channel);

        using var call = client.Drive();

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
        {
            try
            {
                await call.RequestStream.WriteAsync(new LocomotionCommand());
                await call.RequestStream.CompleteAsync();
            }
            catch (RpcException)
            {
                throw;
            }
            await call.ResponseAsync;
        });

        Assert.Equal(StatusCode.Unavailable, ex.StatusCode);
    }
}
