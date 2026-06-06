using Grpc.Core;
using ResoniteIO.Core.Inventory;
using ResoniteIO.Core.Tests.Common;
using ResoniteIO.Core.Tests.Common.Fakes;
using ResoniteIO.V1;
using Xunit;

namespace ResoniteIO.Core.Tests.Inventory;

/// <summary>
/// <see cref="Core.Inventory.InventoryService"/> の各 RPC round-trip と例外翻訳を検証する。
/// </summary>
public sealed class InventoryServiceTests
{
    [Fact]
    public async Task List_round_trips_entries_with_all_fields_and_kinds()
    {
        var bridge = new FakeInventoryBridge();
        await using var host = await InventoryServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Inventory.InventoryClient(channel);

        var listing = await client.ListAsync(new InventoryListRequest { Path = "/Inventory" });

        Assert.Equal("/Inventory", listing.Path);
        var avatars = Assert.Single(listing.Entries, e => e.Name == "Avatars");
        Assert.Equal(V1.InventoryEntryKind.Directory, avatars.Kind);
        Assert.Equal("/Inventory/Avatars", avatars.Path);

        var myAvatar = Assert.Single(listing.Entries, e => e.Name == "MyAvatar");
        Assert.Equal(V1.InventoryEntryKind.Object, myAvatar.Kind);
        Assert.Equal("R-myavatar", myAvatar.RecordId);
        Assert.Equal("resrec:///U-test/R-myavatar", myAvatar.AssetUri);
        Assert.True(myAvatar.IsPublic);
        Assert.Equal(1_700_000_000_000_000_000L, myAvatar.LastModifiedUnixNanos);
    }

    [Fact]
    public async Task MakeDir_creates_directory_and_returns_path()
    {
        var bridge = new FakeInventoryBridge();
        await using var host = await InventoryServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Inventory.InventoryClient(channel);

        var result = await client.MakeDirAsync(
            new InventoryMakeDirRequest { Path = "/Inventory/NewFolder" }
        );

        Assert.Equal("/Inventory/NewFolder", result.Path);
        Assert.NotEqual("", result.RecordId);
        Assert.True(bridge.Contains("/Inventory/NewFolder"));
    }

    [Fact]
    public async Task Copy_forwards_recursive_flag_to_bridge()
    {
        var bridge = new FakeInventoryBridge();
        await using var host = await InventoryServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Inventory.InventoryClient(channel);

        await client.CopyAsync(
            new InventoryCopyRequest
            {
                SourcePath = "/Inventory/Avatars",
                DestinationPath = "/Inventory/AvatarsCopy",
                Recursive = true,
            }
        );

        Assert.Contains(
            "Copy /Inventory/Avatars -> /Inventory/AvatarsCopy recursive=True",
            bridge.Calls
        );
        // 子も再帰コピーされている。
        Assert.True(bridge.Contains("/Inventory/AvatarsCopy/Robot"));
    }

    [Fact]
    public async Task Copy_leaf_without_recursive_succeeds()
    {
        var bridge = new FakeInventoryBridge();
        await using var host = await InventoryServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Inventory.InventoryClient(channel);

        var result = await client.CopyAsync(
            new InventoryCopyRequest
            {
                SourcePath = "/Inventory/MyAvatar",
                DestinationPath = "/Inventory/MyAvatarCopy",
            }
        );

        Assert.Equal("/Inventory/MyAvatarCopy", result.Path);
        Assert.True(bridge.Contains("/Inventory/MyAvatarCopy"));
    }

    [Fact]
    public async Task Copy_directory_without_recursive_translates_to_FailedPrecondition()
    {
        var bridge = new FakeInventoryBridge();
        await using var host = await InventoryServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Inventory.InventoryClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.CopyAsync(
                new InventoryCopyRequest
                {
                    SourcePath = "/Inventory/Avatars",
                    DestinationPath = "/Inventory/AvatarsCopy",
                    Recursive = false,
                }
            )
        );

        Assert.Equal(StatusCode.FailedPrecondition, ex.StatusCode);
    }

    [Fact]
    public async Task Move_directory_moves_subtree()
    {
        var bridge = new FakeInventoryBridge();
        await using var host = await InventoryServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Inventory.InventoryClient(channel);

        await client.MoveAsync(
            new InventoryMoveRequest
            {
                SourcePath = "/Inventory/Avatars",
                DestinationPath = "/Inventory/Characters",
            }
        );

        Assert.False(bridge.Contains("/Inventory/Avatars"));
        Assert.False(bridge.Contains("/Inventory/Avatars/Robot"));
        Assert.True(bridge.Contains("/Inventory/Characters"));
        Assert.True(bridge.Contains("/Inventory/Characters/Robot"));
    }

    [Fact]
    public async Task Remove_leaf_returns_removed_path()
    {
        var bridge = new FakeInventoryBridge();
        await using var host = await InventoryServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Inventory.InventoryClient(channel);

        var result = await client.RemoveAsync(
            new InventoryRemoveRequest { Path = "/Inventory/MyAvatar" }
        );

        Assert.Equal("/Inventory/MyAvatar", result.Path);
        Assert.False(bridge.Contains("/Inventory/MyAvatar"));
    }

    [Fact]
    public async Task Remove_directory_without_recursive_translates_to_FailedPrecondition()
    {
        var bridge = new FakeInventoryBridge();
        await using var host = await InventoryServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Inventory.InventoryClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.RemoveAsync(
                new InventoryRemoveRequest { Path = "/Inventory/Avatars", Recursive = false }
            )
        );

        Assert.Equal(StatusCode.FailedPrecondition, ex.StatusCode);
        Assert.True(bridge.Contains("/Inventory/Avatars"));
    }

    [Fact]
    public async Task Remove_directory_recursive_removes_subtree()
    {
        var bridge = new FakeInventoryBridge();
        await using var host = await InventoryServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Inventory.InventoryClient(channel);

        await client.RemoveAsync(
            new InventoryRemoveRequest { Path = "/Inventory/Avatars", Recursive = true }
        );

        Assert.False(bridge.Contains("/Inventory/Avatars"));
        Assert.False(bridge.Contains("/Inventory/Avatars/Robot"));
    }

    [Fact]
    public async Task Spawn_returns_slot_info()
    {
        var bridge = new FakeInventoryBridge();
        await using var host = await InventoryServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Inventory.InventoryClient(channel);

        var result = await client.SpawnAsync(
            new InventorySpawnRequest { Path = "/Inventory/MyAvatar" }
        );

        Assert.Equal("/Inventory/MyAvatar", result.SourcePath);
        Assert.Equal("MyAvatar", result.SpawnedSlotName);
        Assert.NotEqual("", result.SpawnedSlotId);
    }

    [Fact]
    public async Task List_translates_InventoryNotFoundException_to_NotFound()
    {
        var bridge = new FakeInventoryBridge();
        await using var host = await InventoryServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Inventory.InventoryClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.ListAsync(new InventoryListRequest { Path = "/Inventory/DoesNotExist" })
        );

        Assert.Equal(StatusCode.NotFound, ex.StatusCode);
    }

    [Fact]
    public async Task MakeDir_translates_InventoryNotReadyException_to_FailedPrecondition()
    {
        var bridge = new FakeInventoryBridge
        {
            ThrowOnNextCall = new InventoryNotReadyException("not logged in"),
        };
        await using var host = await InventoryServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Inventory.InventoryClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.MakeDirAsync(new InventoryMakeDirRequest { Path = "/Inventory/X" })
        );

        Assert.Equal(StatusCode.FailedPrecondition, ex.StatusCode);
    }

    [Fact]
    public async Task MakeDir_translates_conflict_to_AlreadyExists()
    {
        var bridge = new FakeInventoryBridge();
        await using var host = await InventoryServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Inventory.InventoryClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.MakeDirAsync(new InventoryMakeDirRequest { Path = "/Inventory/Avatars" })
        );

        Assert.Equal(StatusCode.AlreadyExists, ex.StatusCode);
    }

    [Fact]
    public async Task List_translates_cloud_failure_to_Unavailable()
    {
        var bridge = new FakeInventoryBridge
        {
            ThrowOnNextCall = new InventoryCloudException("cloud unreachable"),
        };
        await using var host = await InventoryServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Inventory.InventoryClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.ListAsync(new InventoryListRequest { Path = "/Inventory" })
        );

        Assert.Equal(StatusCode.Unavailable, ex.StatusCode);
    }

    [Fact]
    public async Task List_without_bridge_returns_Unavailable()
    {
        await using var host = await InventoryServiceHost.StartAsync(bridge: null);
        using var channel = host.CreateChannel();
        var client = new V1.Inventory.InventoryClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.ListAsync(new InventoryListRequest { Path = "/Inventory" })
        );

        Assert.Equal(StatusCode.Unavailable, ex.StatusCode);
    }
}
