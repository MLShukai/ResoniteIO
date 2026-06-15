using Grpc.Core;
using ResoniteIO.Core.Tests.Common;
using ResoniteIO.Core.Tests.Common.Fakes;
using ResoniteIO.V1;
using Xunit;

namespace ResoniteIO.Core.Tests.Session;

/// <summary>
/// <see cref="Core.Hosting.GrpcHost"/> が <see cref="Core.Session.SessionService"/> を正しく mount し、
/// 注入された <see cref="Core.Session.ISessionBridge"/> 経由で RPC を end-to-end で配線できることを
/// 検証する統合テスト (DI / MapGrpcService 漏れの retro 検知)。
/// </summary>
[Collection("GrpcHostEnv")]
public sealed class GrpcHostSessionIntegrationTests
{
    [Fact]
    public async Task GrpcHost_mounts_SessionService_with_injected_bridge()
    {
        var bridge = new FakeSessionBridge();
        await using var harness = await GrpcHostHarness.StartAsync(sessionBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Session.SessionClient(channel);

        // Apply -> Get で wiring を通す (ApplySettings の patch が effective に反映され、
        // 後続 GetSettings がそれを読めることまで end-to-end で確認)。
        await client.ApplySettingsAsync(new SessionSettingsPatch { WorldName = "Wired World" });
        var settings = await client.GetSettingsAsync(new GetSettingsRequest());
        Assert.Equal("Wired World", settings.WorldName);

        var users = await client.ListUsersAsync(new ListUsersRequest());
        Assert.Contains(users.Users, u => u.UserId == "U-host");
    }

    [Fact]
    public async Task GrpcHost_SessionService_without_bridge_returns_Unavailable()
    {
        await using var harness = await GrpcHostHarness.StartAsync(sessionBridge: null);
        using var channel = harness.CreateChannel();
        var client = new V1.Session.SessionClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.GetSettingsAsync(new GetSettingsRequest())
        );
        Assert.Equal(StatusCode.Unavailable, ex.StatusCode);
    }
}
