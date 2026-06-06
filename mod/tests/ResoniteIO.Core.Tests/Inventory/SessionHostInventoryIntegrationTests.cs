using Grpc.Core;
using ResoniteIO.Core.Tests.Common;
using ResoniteIO.Core.Tests.Common.Fakes;
using ResoniteIO.V1;
using Xunit;

namespace ResoniteIO.Core.Tests.Inventory;

/// <summary>
/// <see cref="Core.Session.SessionHost"/> が <see cref="Core.Inventory.InventoryService"/>
/// を正しく mount し、注入された <see cref="Core.Inventory.IInventoryBridge"/> 経由で
/// RPC を end-to-end で配線できることを検証する統合テスト (DI / MapGrpcService 漏れの retro 検知)。
/// </summary>
[Collection("SessionHostEnv")]
public sealed class SessionHostInventoryIntegrationTests
{
    [Fact]
    public async Task SessionHost_mounts_InventoryService_with_injected_bridge()
    {
        var bridge = new FakeInventoryBridge();
        await using var harness = await SessionHostHarness.StartAsync(inventoryBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Inventory.InventoryClient(channel);

        var listing = await client.ListAsync(new InventoryListRequest { Path = "/Inventory" });
        Assert.Contains(listing.Entries, e => e.Name == "Avatars");

        var made = await client.MakeDirAsync(
            new InventoryMakeDirRequest { Path = "/Inventory/Wired" }
        );
        Assert.Equal("/Inventory/Wired", made.Path);
        Assert.True(bridge.Contains("/Inventory/Wired"));
    }

    [Fact]
    public async Task SessionHost_InventoryService_without_bridge_returns_Unavailable()
    {
        await using var harness = await SessionHostHarness.StartAsync(inventoryBridge: null);
        using var channel = harness.CreateChannel();
        var client = new V1.Inventory.InventoryClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.ListAsync(new InventoryListRequest { Path = "/Inventory" })
        );
        Assert.Equal(StatusCode.Unavailable, ex.StatusCode);
    }
}
