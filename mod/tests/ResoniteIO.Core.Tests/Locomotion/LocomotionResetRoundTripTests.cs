using Grpc.Core;
using ResoniteIO.Core.Locomotion;
using ResoniteIO.Core.Tests.Common;
using ResoniteIO.Core.Tests.Common.Fakes;
using Xunit;
using V1 = ResoniteIO.V1;

namespace ResoniteIO.Core.Tests.Locomotion;

/// <summary>
/// <see cref="Core.Locomotion.LocomotionService"/> の Reset RPC を
/// SessionHost mount 越しに検証する。特に proto3 wire default = 0 を
/// Service 層で "全 reset" に展開する規約を全 false / 部分 / 全 true で押さえる。
/// SessionHostHarness が <c>RESONITE_IO_SOCKET</c> env を触るため
/// <c>SessionHostEnv</c> collection で直列化。
/// </summary>
[Collection("SessionHostEnv")]
public sealed class LocomotionResetRoundTripTests
{
    [Fact]
    public async Task Reset_WithoutBridge_ReturnsUnavailable()
    {
        await using var harness = await SessionHostHarness.StartAsync(locomotionBridge: null);
        using var channel = harness.CreateChannel();
        var client = new V1.Locomotion.LocomotionClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
        {
            await client.ResetAsync(new V1.LocomotionResetRequest());
        });

        Assert.Equal(StatusCode.Unavailable, ex.StatusCode);
    }

    [Fact]
    public async Task Reset_BridgeThrows_ReturnsInternal()
    {
        // Bridge.Reset が例外を投げると Service が catch して Internal に翻訳する規約 (A2)。
        var bridge = new FakeLocomotionBridge
        {
            ResetThrows = new InvalidOperationException("simulated bridge failure"),
        };
        await using var harness = await SessionHostHarness.StartAsync(locomotionBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Locomotion.LocomotionClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
        {
            await client.ResetAsync(new V1.LocomotionResetRequest());
        });

        Assert.Equal(StatusCode.Internal, ex.StatusCode);
    }

    [Fact]
    public async Task Reset_DefaultRequest_PassesAllFlags()
    {
        // 全 bool false (proto3 wire default) → Service が All に展開する規約。
        var bridge = new FakeLocomotionBridge();
        await using var harness = await SessionHostHarness.StartAsync(locomotionBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Locomotion.LocomotionClient(channel);

        var summary = await client.ResetAsync(new V1.LocomotionResetRequest());

        Assert.Single(bridge.Resets);
        Assert.Equal(LocomotionResetFlags.All, bridge.Resets[0]);

        Assert.True(summary.Move);
        Assert.True(summary.Look);
        Assert.True(summary.Crouch);
        Assert.True(summary.Jump);
        Assert.True(summary.UnixNanos > 0L);
    }

    [Fact]
    public async Task Reset_PartialRequest_PassesSpecifiedFlags()
    {
        var bridge = new FakeLocomotionBridge();
        await using var harness = await SessionHostHarness.StartAsync(locomotionBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Locomotion.LocomotionClient(channel);

        var summary = await client.ResetAsync(
            new V1.LocomotionResetRequest { Move = true, Look = true }
        );

        Assert.Single(bridge.Resets);
        Assert.Equal(LocomotionResetFlags.Move | LocomotionResetFlags.Look, bridge.Resets[0]);

        Assert.True(summary.Move);
        Assert.True(summary.Look);
        Assert.False(summary.Crouch);
        Assert.False(summary.Jump);
    }

    [Fact]
    public async Task Reset_AllExplicit_ReturnsAllInSummary()
    {
        var bridge = new FakeLocomotionBridge();
        await using var harness = await SessionHostHarness.StartAsync(locomotionBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Locomotion.LocomotionClient(channel);

        var summary = await client.ResetAsync(
            new V1.LocomotionResetRequest
            {
                Move = true,
                Look = true,
                Crouch = true,
                Jump = true,
                UnixNanos = 42L,
            }
        );

        Assert.Single(bridge.Resets);
        Assert.Equal(LocomotionResetFlags.All, bridge.Resets[0]);

        Assert.True(summary.Move);
        Assert.True(summary.Look);
        Assert.True(summary.Crouch);
        Assert.True(summary.Jump);
    }

    [Fact]
    public async Task Drive_FollowedByReset_ClearsState()
    {
        // graceful close は state を維持する規約と、後続の Reset(All) が
        // Bridge.Resets に積まれることをまとめて押さえる (derived state は
        // LocomotionInput.ApplyReset の単体テストで担保するため、ここでは
        // append-only な timeline を直接 assert する)。
        var bridge = new FakeLocomotionBridge();
        await using var harness = await SessionHostHarness.StartAsync(locomotionBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Locomotion.LocomotionClient(channel);

        var sent = new V1.LocomotionCommand
        {
            MoveX = 0.5f,
            MoveY = 1.0f,
            YawRate = 0.25f,
            PitchRate = 0.1f,
            Jump = true,
            Velocity = 2.0f,
            Crouch = 0.75f,
        };

        using (var call = client.Drive())
        {
            await call.RequestStream.WriteAsync(sent);
            await call.RequestStream.CompleteAsync();
            _ = await call.ResponseAsync;
        }

        Assert.Equal(LocomotionDisconnectReason.Graceful, bridge.Disconnects[^1]);
        var lastSetState = bridge.SetStates[^1];
        Assert.Equal(sent.MoveY, lastSetState.MoveY);

        var summary = await client.ResetAsync(new V1.LocomotionResetRequest());

        Assert.True(summary.Move);
        Assert.True(summary.Look);
        Assert.True(summary.Crouch);
        Assert.True(summary.Jump);

        // Reset(All) は最後の SetState を ApplyReset(All) した値と一致するはず。
        // proto velocity 単位元 1.0 を含む semantics は LocomotionInputTests 参照。
        Assert.Single(bridge.Resets);
        Assert.Equal(LocomotionResetFlags.All, bridge.Resets[0]);

        var expectedFinal = lastSetState.ApplyReset(bridge.Resets[0]);
        Assert.Equal(0f, expectedFinal.MoveX);
        Assert.Equal(0f, expectedFinal.MoveY);
        Assert.Equal(0f, expectedFinal.YawRate);
        Assert.Equal(0f, expectedFinal.PitchRate);
        Assert.False(expectedFinal.Jump);
        Assert.Equal(1.0f, expectedFinal.Velocity);
        Assert.Equal(0f, expectedFinal.Crouch);
    }

    [Fact]
    public async Task Reset_DuringActiveDrive_DoesNotAffectStream()
    {
        // active Drive stream と平行する Reset RPC が stream 自体を中断しないこと。
        var bridge = new FakeLocomotionBridge();
        await using var harness = await SessionHostHarness.StartAsync(locomotionBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Locomotion.LocomotionClient(channel);

        using var call = client.Drive();

        await call.RequestStream.WriteAsync(new V1.LocomotionCommand { MoveY = 1.0f });

        var summary = await client.ResetAsync(new V1.LocomotionResetRequest { Move = true });
        Assert.True(summary.Move);
        Assert.False(summary.Look);

        // post-reset command が SetState される = Drive がまだ生きている証拠。
        await call.RequestStream.WriteAsync(new V1.LocomotionCommand { YawRate = 0.5f });
        await call.RequestStream.CompleteAsync();

        var driveSummary = await call.ResponseAsync;
        Assert.Equal(2L, driveSummary.ReceivedCount);

        Assert.Equal(2, bridge.SetStates.Count);
        Assert.Single(bridge.Resets);
        Assert.Equal(LocomotionResetFlags.Move, bridge.Resets[0]);
        Assert.Equal(LocomotionDisconnectReason.Graceful, bridge.Disconnects[^1]);
    }

    [Fact]
    public async Task Reset_OrderingWithSetState_LatestSetStatePrevails()
    {
        // Reset(Move) を先に発火し、後続の SetState(MoveY=1) が "後勝ち" で
        // bridge.SetStates の末尾に記録されることを timeline で示す。
        // (Bridge 側は append-only な list なので derived state ではなく
        //  SetStates[^1] と Resets を直接 assert する)。
        var bridge = new FakeLocomotionBridge();
        await using var harness = await SessionHostHarness.StartAsync(locomotionBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Locomotion.LocomotionClient(channel);

        await client.ResetAsync(new V1.LocomotionResetRequest { Move = true });

        using (var call = client.Drive())
        {
            await call.RequestStream.WriteAsync(new V1.LocomotionCommand { MoveY = 1.0f });
            await call.RequestStream.CompleteAsync();
            _ = await call.ResponseAsync;
        }

        Assert.Single(bridge.Resets);
        Assert.Equal(LocomotionResetFlags.Move, bridge.Resets[0]);
        Assert.Single(bridge.SetStates);
        Assert.Equal(1.0f, bridge.SetStates[^1].MoveY);
        Assert.Equal(LocomotionDisconnectReason.Graceful, bridge.Disconnects[^1]);
    }

    [Fact]
    public async Task Drive_Reconnect_AfterCancel_StartsFromNeutral()
    {
        // 1st Drive を client cancel すると Bridge.NotifyDisconnect(Cancelled)
        // が積まれる (Bridge 側で safety reset)。直後に新しい Drive を張り、
        // 最初の SetState が独立した event (Resets count が増えず、Bridge が
        // 「前回 cancel → 今回 1 件目」の 2 event 構造として観測される) と
        // なることを timeline 上で確認する。
        var bridge = new FakeLocomotionBridge();
        await using var harness = await SessionHostHarness.StartAsync(locomotionBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Locomotion.LocomotionClient(channel);

        using (var cts = new CancellationTokenSource())
        {
            using var call = client.Drive(cancellationToken: cts.Token);
            await call.RequestStream.WriteAsync(new V1.LocomotionCommand { MoveY = 0.5f });
            cts.Cancel();

            try
            {
                await call.ResponseAsync;
            }
            catch (OperationCanceledException) { }
            catch (RpcException ex) when (ex.StatusCode == StatusCode.Cancelled) { }

            await TestPolling.WaitUntilAsync(
                () => bridge.Disconnects.Count >= 1,
                TimeSpan.FromSeconds(5),
                "First Drive did not produce a Cancelled disconnect"
            );
        }
        Assert.Equal(LocomotionDisconnectReason.Cancelled, bridge.Disconnects[^1]);

        var setStatesBeforeReconnect = bridge.SetStates.Count;

        using (var call2 = client.Drive())
        {
            await call2.RequestStream.WriteAsync(new V1.LocomotionCommand { MoveY = 1.0f });
            await call2.RequestStream.CompleteAsync();
            _ = await call2.ResponseAsync;
        }

        // 2nd Drive の SetState は 1st とは独立した append。Disconnects は
        // Cancelled (1st) + Graceful (2nd) の 2 件、最後は Graceful。
        Assert.Equal(setStatesBeforeReconnect + 1, bridge.SetStates.Count);
        Assert.Equal(1.0f, bridge.SetStates[^1].MoveY);
        Assert.Equal(2, bridge.Disconnects.Count);
        Assert.Equal(LocomotionDisconnectReason.Graceful, bridge.Disconnects[^1]);
    }
}
