using Grpc.Core;
using ResoniteIO.Core.Locomotion;
using ResoniteIO.Core.Tests.Common;
using ResoniteIO.Core.Tests.Common.Fakes;
using Xunit;
using V1 = ResoniteIO.V1;

namespace ResoniteIO.Core.Tests.Locomotion;

/// <summary>
/// <see cref="Core.Locomotion.LocomotionService"/> の Drive client-streaming
/// round-trip と disconnect 種別通知を GrpcHost mount 越しに検証する。
/// 各 <c>LocomotionCommand</c> は proto3 <c>optional</c> field presence を持つ
/// 部分更新なので、Service が present field のみを <see cref="LocomotionPartialInput"/>
/// へ map し、未送信 field は null として届くこと、Bridge 側 held-state が
/// 累積することを実 protobuf wire で押さえる。
/// GrpcHostHarness が <c>RESONITE_IO_SOCKET</c> env を触るため
/// <c>GrpcHostEnv</c> collection で直列化。
/// </summary>
[Collection("GrpcHostEnv")]
public sealed class LocomotionRoundTripTests
{
    [Fact]
    public async Task Drive_PartialCommands_AccumulateHeldState_AndOmittedFieldsAreNull()
    {
        var bridge = new FakeLocomotionBridge();
        await using var harness = await GrpcHostHarness.StartAsync(locomotionBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Locomotion.LocomotionClient(channel);

        // 部分更新: 1 件目は MoveForward のみ、2 件目は YawRate のみ present。
        // 部分更新で送らなかった field は wire に乗らず delta では null、
        // Bridge の held-state では前回値 (MoveForward) が保持される。
        using var call = client.Drive();
        await call.RequestStream.WriteAsync(
            new V1.LocomotionCommand { MoveForward = 1.0f, UnixNanos = 1L }
        );
        await call.RequestStream.WriteAsync(
            new V1.LocomotionCommand { YawRate = 0.5f, UnixNanos = 2L }
        );
        await call.RequestStream.CompleteAsync();
        var summary = await call.ResponseAsync;

        Assert.Equal(2L, summary.ReceivedCount);
        Assert.Equal(0L, summary.DroppedCount);
        Assert.True(summary.UnixNanos > 0L);

        var deltas = bridge.Deltas;
        Assert.Equal(2, deltas.Count);

        // 1 件目: MoveForward だけ present、他は未送信 = null。
        Assert.Equal(1.0f, deltas[0].MoveForward!.Value);
        Assert.Null(deltas[0].MoveRight);
        Assert.Null(deltas[0].MoveUp);
        Assert.Null(deltas[0].YawRate);
        Assert.Null(deltas[0].PitchRate);
        Assert.Null(deltas[0].Jump);
        Assert.Null(deltas[0].Velocity);
        Assert.Null(deltas[0].Crouch);
        Assert.Equal(1L, deltas[0].UnixNanos);

        // 2 件目: YawRate だけ present。MoveForward は前 tick で送ったが
        // この delta には乗らない (null) — held は Bridge が担う。
        Assert.Null(deltas[1].MoveForward);
        Assert.Equal(0.5f, deltas[1].YawRate!.Value);
        Assert.Equal(2L, deltas[1].UnixNanos);

        // held-state: Neutral 起点に 2 delta を畳み込むと MoveForward=1.0 が
        // 保持されつつ YawRate=0.5 が加わる。velocity は一度も送っていないので
        // Neutral の単位元 1.0 を保つ。
        var held = bridge.MergedState;
        Assert.Equal(1.0f, held.MoveForward);
        Assert.Equal(0.5f, held.YawRate);
        Assert.Equal(1.0f, held.Velocity);
        Assert.Equal(0f, held.MoveRight);
        Assert.Equal(0f, held.MoveUp);

        var disconnects = bridge.Disconnects;
        Assert.Single(disconnects);
        Assert.Equal(LocomotionDisconnectReason.Graceful, disconnects[0]);
    }

    [Fact]
    public async Task Drive_AllFieldsPresent_MapEachToDistinctDelta()
    {
        var bridge = new FakeLocomotionBridge();
        await using var harness = await GrpcHostHarness.StartAsync(locomotionBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Locomotion.LocomotionClient(channel);

        // 全 field present の 1 command。移動 3 軸 (MoveForward / MoveRight /
        // MoveUp) は別々の値を載せ、取り違え (例: MoveUp が MoveRight に
        // 流れ込む) を検出可能にする。
        using var call = client.Drive();
        await call.RequestStream.WriteAsync(
            new V1.LocomotionCommand
            {
                MoveForward = 0.25f,
                MoveRight = 0.5f,
                MoveUp = -0.75f,
                YawRate = 0.5f,
                PitchRate = -0.25f,
                Jump = true,
                Velocity = 3.0f,
                Crouch = 0.75f,
                UnixNanos = 9L,
            }
        );
        await call.RequestStream.CompleteAsync();
        var summary = await call.ResponseAsync;

        Assert.Equal(1L, summary.ReceivedCount);

        var deltas = bridge.Deltas;
        Assert.Single(deltas);
        var d = deltas[0];

        // present field はすべて非 null で正しい軸に届く。
        Assert.Equal(0.25f, d.MoveForward!.Value);
        Assert.Equal(0.5f, d.MoveRight!.Value);
        Assert.Equal(-0.75f, d.MoveUp!.Value);
        Assert.Equal(0.5f, d.YawRate!.Value);
        Assert.Equal(-0.25f, d.PitchRate!.Value);
        Assert.True(d.Jump!.Value);
        Assert.Equal(3.0f, d.Velocity!.Value);
        Assert.Equal(0.75f, d.Crouch!.Value);
        Assert.Equal(9L, d.UnixNanos);
    }

    [Fact]
    public async Task Drive_ClientCancellation_NotifiesCancelledDisconnect()
    {
        var bridge = new FakeLocomotionBridge();
        await using var harness = await GrpcHostHarness.StartAsync(locomotionBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Locomotion.LocomotionClient(channel);

        using var cts = new CancellationTokenSource();
        using var call = client.Drive(cancellationToken: cts.Token);

        await call.RequestStream.WriteAsync(new V1.LocomotionCommand { MoveForward = 1.0f });
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
        await using var harness = await GrpcHostHarness.StartAsync(locomotionBridge: null);
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
