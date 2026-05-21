using Grpc.Core;
using ResoniteIO.Core.Tests.Helpers;
using ResoniteIO.V1;
using Xunit;

namespace ResoniteIO.Core.Tests.Display;

/// <summary>
/// <see cref="Core.Session.SessionHost"/> が <see cref="Core.Display.DisplayService"/>
/// を正しく mount し、注入された <see cref="Core.Display.IDisplayBridge"/> 経由で
/// Apply / Get RPC を end-to-end で配線できることを検証する統合テスト。
/// </summary>
/// <remarks>
/// 単独 Service の round-trip は <see cref="DisplayServiceTests"/> (Helpers/DisplayServiceHost
/// 経由) が担う。本テストは Wave 4 で SessionHost に DisplayService を mount した
/// **wiring** の retro 検知を目的とする (例えば DI 登録漏れや MapGrpcService 漏れを
/// 早期検出する)。
/// </remarks>
[Collection("SessionHostEnv")]
public sealed class SessionHostDisplayIntegrationTests
{
    [Fact]
    public async Task SessionHost_mounts_DisplayService_with_injected_bridge()
    {
        var bridge = new FakeDisplayBridge
        {
            CurrentState = new()
            {
                Width = 1280,
                Height = 720,
                MaxFps = 60.0f,
            },
        };
        await using var harness = await SessionHostHarness.StartAsync(displayBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Display.DisplayClient(channel);

        // Apply の応答は Empty。state は bridge への書き込みと follow-up Get で検証する。
        var ack = await client.ApplyAsync(
            new DisplayConfig
            {
                Width = 1920,
                Height = 1080,
                MaxFps = 120f,
            }
        );
        Assert.NotNull(ack);
        Assert.NotNull(bridge.LastApplied);

        var current = await client.GetAsync(new DisplayGetRequest());
        Assert.Equal(1920u, current.Width);
        Assert.Equal(1080u, current.Height);
        Assert.Equal(120f, current.MaxFps);
    }

    [Fact]
    public async Task SessionHost_DisplayService_without_bridge_returns_Unavailable()
    {
        // displayBridge=null で起動 → DisplayService は MapGrpcService で mount される
        // が、bridge 未注入なので各 RPC は Status.Unavailable を返す (Service 既存契約)。
        await using var harness = await SessionHostHarness.StartAsync(displayBridge: null);
        using var channel = harness.CreateChannel();
        var client = new V1.Display.DisplayClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.GetAsync(new DisplayGetRequest())
        );
        Assert.Equal(StatusCode.Unavailable, ex.StatusCode);
    }
}
