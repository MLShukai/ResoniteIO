using Grpc.Core;
using ResoniteIO.Core.Tests.Common;
using ResoniteIO.Core.Tests.Common.Fakes;
using ResoniteIO.Core.World;
using ResoniteIO.V1;
using Xunit;
using CoreRecordSort = ResoniteIO.Core.World.RecordSort;
using CoreRecordSortDirection = ResoniteIO.Core.World.RecordSortDirection;
using CoreRecordSource = ResoniteIO.Core.World.RecordSource;
using CoreSessionFilter = ResoniteIO.Core.World.SessionFilter;

namespace ResoniteIO.Core.Tests.World;

/// <summary>
/// <see cref="Core.World.WorldService"/> の 8 RPC を実 Kestrel + UDS gRPC で
/// end-to-end に流す integration-real テスト。検証対象:
/// <list type="number">
/// <item>各 RPC の request → Core query/target → Bridge → response field map。</item>
/// <item>ListSessions の page / page_size slicing と total_count を <em>Service</em> が行うこと。</item>
/// <item>proto enum → Core enum の map (UNSPECIFIED の既定値含む) が Bridge へ正しく届くこと。</item>
/// <item>bridge-null / 例外 → gRPC Status の翻訳。</item>
/// </list>
/// 仕様は <c>/tmp/world_contract_csharp.md</c> + <c>proto/resonite_io/v1/world.proto</c>。
/// </summary>
public sealed class WorldServiceTests
{
    // ===================================================================
    //  ListSessions — field map / paging (Service が slice する)
    // ===================================================================

    [Fact]
    public async Task ListSessions_round_trips_session_fields_including_repeated_and_unix_nanos()
    {
        var session = new WorldSessionSnapshot
        {
            SessionId = "S-MaTRiX-001",
            Name = "The Hub",
            Description = "central lobby",
            HostUserId = "U-host",
            HostUsername = "hostname",
            SessionUrls = new[] { "lnl-nat://a/b", "lnl-nat://c/d" },
            ThumbnailUrl = "https://example/thumb.png",
            JoinedUsers = 5,
            ActiveUsers = 3,
            MaximumUsers = 16,
            Tags = new[] { "game", "social" },
            AccessLevel = "Anyone",
            HeadlessHost = true,
            MobileFriendly = false,
            CorrespondingWorldId = "R-world",
            UniverseId = "uni-1",
            SessionBeginUnixNanos = 1_700_000_000_000_000_001L,
            LastUpdateUnixNanos = 1_700_000_000_000_000_999L,
        };
        var bridge = new FakeWorldBridge { NextSessions = new[] { session } };
        await using var host = await WorldServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.World.WorldClient(channel);

        var response = await client.ListSessionsAsync(new ListSessionsRequest());

        var ws = Assert.Single(response.Sessions);
        Assert.Equal("S-MaTRiX-001", ws.SessionId);
        Assert.Equal("The Hub", ws.Name);
        Assert.Equal("central lobby", ws.Description);
        Assert.Equal("U-host", ws.HostUserId);
        Assert.Equal("hostname", ws.HostUsername);
        Assert.Equal(new[] { "lnl-nat://a/b", "lnl-nat://c/d" }, ws.SessionUrls);
        Assert.Equal("https://example/thumb.png", ws.ThumbnailUrl);
        Assert.Equal(5, ws.JoinedUsers);
        Assert.Equal(3, ws.ActiveUsers);
        Assert.Equal(16, ws.MaximumUsers);
        Assert.Equal(new[] { "game", "social" }, ws.Tags);
        Assert.Equal("Anyone", ws.AccessLevel);
        Assert.True(ws.HeadlessHost);
        Assert.False(ws.MobileFriendly);
        Assert.Equal("R-world", ws.CorrespondingWorldId);
        Assert.Equal("uni-1", ws.UniverseId);
        Assert.Equal(1_700_000_000_000_000_001L, ws.SessionBeginUnixNanos);
        Assert.Equal(1_700_000_000_000_000_999L, ws.LastUpdateUnixNanos);
    }

    [Fact]
    public async Task ListSessions_forwards_query_fields_to_bridge()
    {
        var bridge = new FakeWorldBridge();
        await using var host = await WorldServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.World.WorldClient(channel);

        await client.ListSessionsAsync(
            new ListSessionsRequest
            {
                Search = "lobby",
                Filter = SessionFilter.Headless,
                MinActiveUsers = 4,
            }
        );

        Assert.NotNull(bridge.LastSessionQuery);
        Assert.Equal("lobby", bridge.LastSessionQuery!.Search);
        Assert.Equal(CoreSessionFilter.Headless, bridge.LastSessionQuery!.Filter);
        Assert.Equal(4, bridge.LastSessionQuery!.MinActiveUsers);
    }

    [Fact]
    public async Task ListSessions_reports_total_count_of_full_list_and_echoes_paging()
    {
        // Bridge が full filtered list (60 件) を返す。Service が total_count を算出し、
        // page / page_size を echo back する契約。
        var bridge = new FakeWorldBridge { NextSessions = MakeSessions(60) };
        await using var host = await WorldServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.World.WorldClient(channel);

        var response = await client.ListSessionsAsync(
            new ListSessionsRequest { Page = 0, PageSize = 25 }
        );

        Assert.Equal(60u, response.TotalCount);
        Assert.Equal(0u, response.Page);
        Assert.Equal(25u, response.PageSize);
        Assert.Equal(25, response.Sessions.Count);
        // page 0 / size 25 → items 0..24。
        Assert.Equal("sess-0", response.Sessions[0].SessionId);
        Assert.Equal("sess-24", response.Sessions[24].SessionId);
    }

    [Fact]
    public async Task ListSessions_page_1_slices_the_second_window()
    {
        // page=1 page_size=25 → items 25..49 (0-based page)。
        var bridge = new FakeWorldBridge { NextSessions = MakeSessions(60) };
        await using var host = await WorldServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.World.WorldClient(channel);

        var response = await client.ListSessionsAsync(
            new ListSessionsRequest { Page = 1, PageSize = 25 }
        );

        Assert.Equal(60u, response.TotalCount);
        Assert.Equal(1u, response.Page);
        Assert.Equal(25u, response.PageSize);
        Assert.Equal(25, response.Sessions.Count);
        Assert.Equal("sess-25", response.Sessions[0].SessionId);
        Assert.Equal("sess-49", response.Sessions[24].SessionId);
    }

    [Fact]
    public async Task ListSessions_last_partial_page_returns_remaining_items()
    {
        // 60 件 / size 25 → page 2 は items 50..59 (10 件のみ)。
        var bridge = new FakeWorldBridge { NextSessions = MakeSessions(60) };
        await using var host = await WorldServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.World.WorldClient(channel);

        var response = await client.ListSessionsAsync(
            new ListSessionsRequest { Page = 2, PageSize = 25 }
        );

        Assert.Equal(60u, response.TotalCount);
        Assert.Equal(10, response.Sessions.Count);
        Assert.Equal("sess-50", response.Sessions[0].SessionId);
        Assert.Equal("sess-59", response.Sessions[9].SessionId);
    }

    [Fact]
    public async Task ListSessions_page_size_zero_returns_all_sessions_unsliced()
    {
        // page_size == 0 → slicing なしで全件返す契約。
        var bridge = new FakeWorldBridge { NextSessions = MakeSessions(60) };
        await using var host = await WorldServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.World.WorldClient(channel);

        var response = await client.ListSessionsAsync(
            new ListSessionsRequest { Page = 0, PageSize = 0 }
        );

        Assert.Equal(60u, response.TotalCount);
        Assert.Equal(0u, response.PageSize);
        Assert.Equal(60, response.Sessions.Count);
        Assert.Equal("sess-0", response.Sessions[0].SessionId);
        Assert.Equal("sess-59", response.Sessions[59].SessionId);
    }

    [Fact]
    public async Task ListSessions_page_beyond_end_returns_empty_but_keeps_total_count()
    {
        var bridge = new FakeWorldBridge { NextSessions = MakeSessions(60) };
        await using var host = await WorldServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.World.WorldClient(channel);

        var response = await client.ListSessionsAsync(
            new ListSessionsRequest { Page = 99, PageSize = 25 }
        );

        Assert.Equal(60u, response.TotalCount);
        Assert.Empty(response.Sessions);
    }

    // ----- SessionFilter enum map (proto → Core) -----

    [Theory]
    [InlineData(SessionFilter.Unspecified, CoreSessionFilter.All)]
    [InlineData(SessionFilter.Friends, CoreSessionFilter.Friends)]
    [InlineData(SessionFilter.Headless, CoreSessionFilter.Headless)]
    public async Task ListSessions_maps_proto_session_filter_to_core(
        SessionFilter wire,
        CoreSessionFilter expected
    )
    {
        // 仕様: UNSPECIFIED → All、それ以外は同名 straight across。
        var bridge = new FakeWorldBridge();
        await using var host = await WorldServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.World.WorldClient(channel);

        await client.ListSessionsAsync(new ListSessionsRequest { Filter = wire });

        Assert.NotNull(bridge.LastSessionQuery);
        Assert.Equal(expected, bridge.LastSessionQuery!.Filter);
    }

    // ===================================================================
    //  ListRecords — field map / server-side paging (bridge が honor)
    // ===================================================================

    [Fact]
    public async Task ListRecords_round_trips_record_fields_including_repeated_and_unix_nanos()
    {
        var record = new WorldRecordSnapshot
        {
            RecordId = "R-001",
            OwnerId = "U-owner",
            Name = "My World",
            Description = "a saved world",
            ThumbnailUrl = "https://example/r.png",
            Tags = new[] { "template", "showcase" },
            RecordUrl = "resrec:///U-owner/R-001",
            LastModificationUnixNanos = 1_699_999_999_000_000_123L,
        };
        var bridge = new FakeWorldBridge
        {
            NextRecordPage = new RecordPage
            {
                Records = new[] { record },
                HasMore = true,
                Offset = 30,
            },
        };
        await using var host = await WorldServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.World.WorldClient(channel);

        var response = await client.ListRecordsAsync(new ListRecordsRequest());

        var wr = Assert.Single(response.Records);
        Assert.Equal("R-001", wr.RecordId);
        Assert.Equal("U-owner", wr.OwnerId);
        Assert.Equal("My World", wr.Name);
        Assert.Equal("a saved world", wr.Description);
        Assert.Equal("https://example/r.png", wr.ThumbnailUrl);
        Assert.Equal(new[] { "template", "showcase" }, wr.Tags);
        Assert.Equal("resrec:///U-owner/R-001", wr.RecordUrl);
        Assert.Equal(1_699_999_999_000_000_123L, wr.LastModificationUnixNanos);
        // has_more / offset は bridge の page をそのまま echo (Service は slice しない)。
        Assert.True(response.HasMore);
        Assert.Equal(30u, response.Offset);
    }

    [Fact]
    public async Task ListRecords_forwards_query_fields_to_bridge()
    {
        var bridge = new FakeWorldBridge();
        await using var host = await WorldServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.World.WorldClient(channel);

        await client.ListRecordsAsync(
            new ListRecordsRequest
            {
                Source = RecordSource.Group,
                RequiredTags = { "game", "avatar" },
                OwnerId = "G-team",
                Offset = 60,
                Count = 30,
                Sort = RecordSort.TotalVisits,
                SortDirection = RecordSortDirection.Ascending,
            }
        );

        var q = bridge.LastRecordQuery;
        Assert.NotNull(q);
        Assert.Equal(CoreRecordSource.Group, q!.Source);
        Assert.Equal(new[] { "game", "avatar" }, q!.RequiredTags);
        Assert.Equal("G-team", q!.OwnerId);
        Assert.Equal(60, q!.Offset);
        Assert.Equal(30, q!.Count);
        Assert.Equal(CoreRecordSort.TotalVisits, q!.Sort);
        Assert.Equal(CoreRecordSortDirection.Ascending, q!.SortDirection);
    }

    // ----- RecordSource / Sort / SortDirection enum map (proto → Core) -----

    [Theory]
    [InlineData(RecordSource.Unspecified, CoreRecordSource.Public)]
    [InlineData(RecordSource.Public, CoreRecordSource.Public)]
    [InlineData(RecordSource.Featured, CoreRecordSource.Featured)]
    [InlineData(RecordSource.Own, CoreRecordSource.Own)]
    [InlineData(RecordSource.Group, CoreRecordSource.Group)]
    public async Task ListRecords_maps_proto_record_source_to_core(
        RecordSource wire,
        CoreRecordSource expected
    )
    {
        var bridge = new FakeWorldBridge();
        await using var host = await WorldServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.World.WorldClient(channel);

        await client.ListRecordsAsync(new ListRecordsRequest { Source = wire });

        Assert.NotNull(bridge.LastRecordQuery);
        Assert.Equal(expected, bridge.LastRecordQuery!.Source);
    }

    [Theory]
    [InlineData(RecordSort.Unspecified, CoreRecordSort.CreationDate)]
    [InlineData(RecordSort.CreationDate, CoreRecordSort.CreationDate)]
    [InlineData(RecordSort.LastUpdate, CoreRecordSort.LastUpdate)]
    [InlineData(RecordSort.FirstPublish, CoreRecordSort.FirstPublish)]
    [InlineData(RecordSort.TotalVisits, CoreRecordSort.TotalVisits)]
    [InlineData(RecordSort.Name, CoreRecordSort.Name)]
    [InlineData(RecordSort.Random, CoreRecordSort.Random)]
    public async Task ListRecords_maps_proto_record_sort_to_core(
        RecordSort wire,
        CoreRecordSort expected
    )
    {
        var bridge = new FakeWorldBridge();
        await using var host = await WorldServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.World.WorldClient(channel);

        await client.ListRecordsAsync(new ListRecordsRequest { Sort = wire });

        Assert.NotNull(bridge.LastRecordQuery);
        Assert.Equal(expected, bridge.LastRecordQuery!.Sort);
    }

    [Theory]
    [InlineData(RecordSortDirection.Unspecified, CoreRecordSortDirection.Descending)]
    [InlineData(RecordSortDirection.Descending, CoreRecordSortDirection.Descending)]
    [InlineData(RecordSortDirection.Ascending, CoreRecordSortDirection.Ascending)]
    public async Task ListRecords_maps_proto_sort_direction_to_core(
        RecordSortDirection wire,
        CoreRecordSortDirection expected
    )
    {
        var bridge = new FakeWorldBridge();
        await using var host = await WorldServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.World.WorldClient(channel);

        await client.ListRecordsAsync(new ListRecordsRequest { SortDirection = wire });

        Assert.NotNull(bridge.LastRecordQuery);
        Assert.Equal(expected, bridge.LastRecordQuery!.SortDirection);
    }

    // ===================================================================
    //  Join / StartWorld — target map + OpenWorld round-trip
    // ===================================================================

    [Fact]
    public async Task Join_forwards_target_to_bridge_and_round_trips_open_world()
    {
        var bridge = new FakeWorldBridge { NextOpenWorld = SampleOpenWorld() };
        await using var host = await WorldServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.World.WorldClient(channel);

        var response = await client.JoinAsync(
            new JoinRequest
            {
                SessionId = "S-join",
                SessionUrl = "lnl-nat://x/y",
                Focus = true,
            }
        );

        Assert.NotNull(bridge.LastJoinTarget);
        Assert.Equal("S-join", bridge.LastJoinTarget!.SessionId);
        Assert.Equal("lnl-nat://x/y", bridge.LastJoinTarget!.SessionUrl);
        Assert.True(bridge.LastJoinTarget!.Focus);
        AssertOpenWorldRoundTrips(SampleOpenWorld(), response.World);
    }

    [Fact]
    public async Task StartWorld_forwards_target_to_bridge_and_round_trips_open_world()
    {
        var bridge = new FakeWorldBridge { NextOpenWorld = SampleOpenWorld() };
        await using var host = await WorldServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.World.WorldClient(channel);

        var response = await client.StartWorldAsync(
            new StartWorldRequest
            {
                RecordId = "R-start",
                OwnerId = "U-me",
                Focus = false,
            }
        );

        Assert.NotNull(bridge.LastStartWorldTarget);
        Assert.Equal("R-start", bridge.LastStartWorldTarget!.RecordId);
        Assert.Equal("U-me", bridge.LastStartWorldTarget!.OwnerId);
        Assert.False(bridge.LastStartWorldTarget!.Focus);
        AssertOpenWorldRoundTrips(SampleOpenWorld(), response.World);
    }

    // ===================================================================
    //  ListOpenWorlds / Focus / Leave
    // ===================================================================

    [Fact]
    public async Task ListOpenWorlds_round_trips_each_open_world()
    {
        var a = new OpenWorldSnapshot
        {
            Handle = 7,
            SessionId = "S-a",
            Name = "World A",
            Focused = true,
            UserCount = 2,
            AccessLevel = "Anyone",
        };
        var b = new OpenWorldSnapshot
        {
            Handle = 9,
            SessionId = "S-b",
            Name = "World B",
            Focused = false,
            UserCount = 0,
            AccessLevel = "Private",
        };
        var bridge = new FakeWorldBridge { NextOpenWorlds = new[] { a, b } };
        await using var host = await WorldServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.World.WorldClient(channel);

        var response = await client.ListOpenWorldsAsync(new ListOpenWorldsRequest());

        Assert.True(bridge.ListOpenWorldsCalled);
        Assert.Equal(2, response.Worlds.Count);
        AssertOpenWorldRoundTrips(a, response.Worlds[0]);
        AssertOpenWorldRoundTrips(b, response.Worlds[1]);
    }

    [Fact]
    public async Task Focus_forwards_handle_to_bridge_and_round_trips_open_world()
    {
        var bridge = new FakeWorldBridge { NextOpenWorld = SampleOpenWorld() };
        await using var host = await WorldServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.World.WorldClient(channel);

        var response = await client.FocusAsync(new FocusRequest { Handle = 42 });

        Assert.Equal(42, bridge.LastFocusHandle);
        AssertOpenWorldRoundTrips(SampleOpenWorld(), response.World);
    }

    [Fact]
    public async Task Leave_forwards_handle_to_bridge()
    {
        var bridge = new FakeWorldBridge();
        await using var host = await WorldServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.World.WorldClient(channel);

        // LeaveResponse は空。handle が Bridge に届くことを検証する。
        await client.LeaveAsync(new LeaveRequest { Handle = 13 });

        Assert.Equal(13, bridge.LastLeaveHandle);
    }

    // ===================================================================
    //  GetCurrent — has_world true / false
    // ===================================================================

    [Fact]
    public async Task GetCurrent_returns_world_with_has_world_true_when_focused()
    {
        var bridge = new FakeWorldBridge { NextCurrent = SampleOpenWorld() };
        await using var host = await WorldServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.World.WorldClient(channel);

        var response = await client.GetCurrentAsync(new GetCurrentRequest());

        Assert.True(bridge.GetCurrentCalled);
        Assert.True(response.HasWorld);
        AssertOpenWorldRoundTrips(SampleOpenWorld(), response.World);
    }

    [Fact]
    public async Task GetCurrent_returns_has_world_false_when_bridge_returns_null()
    {
        // userspace のみ (移動可能なワールドに focus していない) → bridge は null を返し、
        // Service は has_world=false を返す契約 (world.proto GetCurrentResponse 参照)。
        var bridge = new FakeWorldBridge { NextCurrent = null };
        await using var host = await WorldServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.World.WorldClient(channel);

        var response = await client.GetCurrentAsync(new GetCurrentRequest());

        Assert.True(bridge.GetCurrentCalled);
        Assert.False(response.HasWorld);
    }

    // ===================================================================
    //  bridge-null → Unavailable (全 RPC)
    // ===================================================================

    [Fact]
    public async Task ListSessions_without_bridge_returns_Unavailable()
    {
        await AssertUnavailableAsync(client =>
            client.ListSessionsAsync(new ListSessionsRequest()).ResponseAsync
        );
    }

    [Fact]
    public async Task ListRecords_without_bridge_returns_Unavailable()
    {
        await AssertUnavailableAsync(client =>
            client.ListRecordsAsync(new ListRecordsRequest()).ResponseAsync
        );
    }

    [Fact]
    public async Task Join_without_bridge_returns_Unavailable()
    {
        await AssertUnavailableAsync(client => client.JoinAsync(new JoinRequest()).ResponseAsync);
    }

    [Fact]
    public async Task StartWorld_without_bridge_returns_Unavailable()
    {
        await AssertUnavailableAsync(client =>
            client.StartWorldAsync(new StartWorldRequest()).ResponseAsync
        );
    }

    [Fact]
    public async Task ListOpenWorlds_without_bridge_returns_Unavailable()
    {
        await AssertUnavailableAsync(client =>
            client.ListOpenWorldsAsync(new ListOpenWorldsRequest()).ResponseAsync
        );
    }

    [Fact]
    public async Task Focus_without_bridge_returns_Unavailable()
    {
        await AssertUnavailableAsync(client => client.FocusAsync(new FocusRequest()).ResponseAsync);
    }

    [Fact]
    public async Task Leave_without_bridge_returns_Unavailable()
    {
        await AssertUnavailableAsync(client => client.LeaveAsync(new LeaveRequest()).ResponseAsync);
    }

    [Fact]
    public async Task GetCurrent_without_bridge_returns_Unavailable()
    {
        await AssertUnavailableAsync(client =>
            client.GetCurrentAsync(new GetCurrentRequest()).ResponseAsync
        );
    }

    // ===================================================================
    //  例外翻訳: WorldNotReady → FailedPrecondition / WorldNotFound → NotFound
    // ===================================================================

    [Fact]
    public async Task Join_translates_WorldNotReadyException_to_FailedPrecondition()
    {
        var bridge = new FakeWorldBridge
        {
            ThrowOnNextCall = new WorldNotReadyException("cloud not ready yet"),
        };
        await using var host = await WorldServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.World.WorldClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.JoinAsync(new JoinRequest())
        );
        Assert.Equal(StatusCode.FailedPrecondition, ex.StatusCode);
        Assert.Contains("cloud not ready", ex.Status.Detail);
    }

    [Fact]
    public async Task Focus_translates_WorldNotFoundException_to_NotFound()
    {
        var bridge = new FakeWorldBridge
        {
            ThrowOnNextCall = new WorldNotFoundException("no world for handle 99"),
        };
        await using var host = await WorldServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.World.WorldClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.FocusAsync(new FocusRequest { Handle = 99 })
        );
        Assert.Equal(StatusCode.NotFound, ex.StatusCode);
        Assert.Contains("handle 99", ex.Status.Detail);
    }

    [Fact]
    public async Task Leave_translates_WorldNotFoundException_to_NotFound()
    {
        var bridge = new FakeWorldBridge
        {
            ThrowOnNextCall = new WorldNotFoundException("unknown handle"),
        };
        await using var host = await WorldServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.World.WorldClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.LeaveAsync(new LeaveRequest { Handle = 5 })
        );
        Assert.Equal(StatusCode.NotFound, ex.StatusCode);
    }

    [Fact]
    public async Task ListSessions_translates_generic_exception_to_Internal()
    {
        var bridge = new FakeWorldBridge
        {
            ThrowOnNextCall = new InvalidOperationException("engine fault"),
        };
        await using var host = await WorldServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.World.WorldClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.ListSessionsAsync(new ListSessionsRequest())
        );
        Assert.Equal(StatusCode.Internal, ex.StatusCode);
    }

    // ===================================================================
    //  helpers
    // ===================================================================

    private static IReadOnlyList<WorldSessionSnapshot> MakeSessions(int count)
    {
        var sessions = new WorldSessionSnapshot[count];
        for (var i = 0; i < count; i++)
        {
            sessions[i] = new WorldSessionSnapshot { SessionId = $"sess-{i}", Name = $"name-{i}" };
        }
        return sessions;
    }

    private static OpenWorldSnapshot SampleOpenWorld() =>
        new()
        {
            Handle = 3,
            SessionId = "S-current",
            Name = "Current World",
            Focused = true,
            UserCount = 4,
            AccessLevel = "ContactsPlus",
        };

    private static void AssertOpenWorldRoundTrips(OpenWorldSnapshot expected, OpenWorld actual)
    {
        Assert.Equal(expected.Handle, actual.Handle);
        Assert.Equal(expected.SessionId, actual.SessionId);
        Assert.Equal(expected.Name, actual.Name);
        Assert.Equal(expected.Focused, actual.Focused);
        Assert.Equal(expected.UserCount, actual.UserCount);
        Assert.Equal(expected.AccessLevel, actual.AccessLevel);
    }

    private static async Task AssertUnavailableAsync(Func<V1.World.WorldClient, Task> rpc)
    {
        // bridge=null で起動 → Service は mount されるが bridge 未注入なので
        // 各 RPC は Status.Unavailable を返す (WorldService 契約)。
        await using var host = await WorldServiceHost.StartAsync(bridge: null);
        using var channel = host.CreateChannel();
        var client = new V1.World.WorldClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () => await rpc(client));
        Assert.Equal(StatusCode.Unavailable, ex.StatusCode);
    }
}
