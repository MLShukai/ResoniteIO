using Grpc.Core;
using ResoniteIO.Core.Logging;

#pragma warning disable CA1031 // catch (Exception) は Bridge 側の任意例外を gRPC Status に翻訳するために必要

namespace ResoniteIO.Core.World;

/// <summary><c>resonite_io.v1.World</c> サービスの Core 実装。</summary>
/// <remarks>
/// <see cref="IWorldBridge"/> は optional DI: null なら全 RPC が <c>Unavailable</c> を返し、
/// Core 単体テストや world 非対応 engine 構成も成立させる (他モダリティと同 pattern)。
/// 例外翻訳は <see cref="WorldNotReadyException"/> → <c>FailedPrecondition</c>、
/// <see cref="WorldNotFoundException"/> → <c>NotFound</c>、その他 → <c>Internal</c>。
/// ListSessions の page / page_size slicing と total_count 計算は本 Service が行う。
/// </remarks>
public sealed class WorldService : V1.World.WorldBase
{
    private readonly IWorldBridge? _bridge;
    private readonly ILogSink _log;

    public WorldService(ILogSink log, IWorldBridge? bridge = null)
    {
        _log = log;
        _bridge = bridge;
    }

    public override async Task<V1.ListSessionsResponse> ListSessions(
        V1.ListSessionsRequest request,
        ServerCallContext context
    )
    {
        var bridge = RequireBridge("ListSessions");

        var query = new SessionListQuery
        {
            Search = request.Search,
            Filter = MapFilter(request.Filter),
            MinActiveUsers = request.MinActiveUsers,
        };

        IReadOnlyList<WorldSessionSnapshot> sessions;
        try
        {
            sessions = await bridge
                .ListSessionsAsync(query, context.CancellationToken)
                .ConfigureAwait(false);
        }
        catch (Exception ex)
        {
            throw Translate("ListSessions", ex, context);
        }

        var totalCount = sessions.Count;
        var page = request.Page;
        var pageSize = request.PageSize;

        IEnumerable<WorldSessionSnapshot> pageItems = sessions;
        if (pageSize != 0)
        {
            pageItems = sessions.Skip(checked((int)(page * pageSize))).Take((int)pageSize);
        }

        var response = new V1.ListSessionsResponse
        {
            TotalCount = (uint)totalCount,
            Page = page,
            PageSize = pageSize,
        };
        foreach (var session in pageItems)
        {
            response.Sessions.Add(ToProto(session));
        }
        return response;
    }

    public override async Task<V1.ListRecordsResponse> ListRecords(
        V1.ListRecordsRequest request,
        ServerCallContext context
    )
    {
        var bridge = RequireBridge("ListRecords");

        var query = new RecordListQuery
        {
            Source = MapSource(request.Source),
            RequiredTags = request.RequiredTags.ToArray(),
            OwnerId = request.OwnerId,
            Offset = (int)request.Offset,
            Count = (int)request.Count,
            Sort = MapSort(request.Sort),
            SortDirection = MapSortDirection(request.SortDirection),
        };

        RecordPage pageResult;
        try
        {
            pageResult = await bridge
                .ListRecordsAsync(query, context.CancellationToken)
                .ConfigureAwait(false);
        }
        catch (Exception ex)
        {
            throw Translate("ListRecords", ex, context);
        }

        var response = new V1.ListRecordsResponse
        {
            HasMore = pageResult.HasMore,
            Offset = (uint)pageResult.Offset,
        };
        foreach (var record in pageResult.Records)
        {
            response.Records.Add(ToProto(record));
        }
        return response;
    }

    public override async Task<V1.JoinResponse> Join(
        V1.JoinRequest request,
        ServerCallContext context
    )
    {
        var bridge = RequireBridge("Join");

        var target = new JoinTarget
        {
            SessionId = request.SessionId,
            SessionUrl = request.SessionUrl,
            Focus = request.Focus,
        };

        OpenWorldSnapshot world;
        try
        {
            world = await bridge.JoinAsync(target, context.CancellationToken).ConfigureAwait(false);
        }
        catch (Exception ex)
        {
            throw Translate("Join", ex, context);
        }

        return new V1.JoinResponse { World = ToProto(world) };
    }

    public override async Task<V1.StartWorldResponse> StartWorld(
        V1.StartWorldRequest request,
        ServerCallContext context
    )
    {
        var bridge = RequireBridge("StartWorld");

        var target = new StartWorldTarget
        {
            RecordId = request.RecordId,
            OwnerId = request.OwnerId,
            Focus = request.Focus,
        };

        OpenWorldSnapshot world;
        try
        {
            world = await bridge
                .StartWorldAsync(target, context.CancellationToken)
                .ConfigureAwait(false);
        }
        catch (Exception ex)
        {
            throw Translate("StartWorld", ex, context);
        }

        return new V1.StartWorldResponse { World = ToProto(world) };
    }

    public override async Task<V1.ListOpenWorldsResponse> ListOpenWorlds(
        V1.ListOpenWorldsRequest request,
        ServerCallContext context
    )
    {
        var bridge = RequireBridge("ListOpenWorlds");

        IReadOnlyList<OpenWorldSnapshot> worlds;
        try
        {
            worlds = await bridge
                .ListOpenWorldsAsync(context.CancellationToken)
                .ConfigureAwait(false);
        }
        catch (Exception ex)
        {
            throw Translate("ListOpenWorlds", ex, context);
        }

        var response = new V1.ListOpenWorldsResponse();
        foreach (var world in worlds)
        {
            response.Worlds.Add(ToProto(world));
        }
        return response;
    }

    public override async Task<V1.FocusResponse> Focus(
        V1.FocusRequest request,
        ServerCallContext context
    )
    {
        var bridge = RequireBridge("Focus");

        OpenWorldSnapshot world;
        try
        {
            world = await bridge
                .FocusAsync(request.Handle, context.CancellationToken)
                .ConfigureAwait(false);
        }
        catch (Exception ex)
        {
            throw Translate("Focus", ex, context);
        }

        return new V1.FocusResponse { World = ToProto(world) };
    }

    public override async Task<V1.LeaveResponse> Leave(
        V1.LeaveRequest request,
        ServerCallContext context
    )
    {
        var bridge = RequireBridge("Leave");

        try
        {
            await bridge
                .LeaveAsync(request.Handle, context.CancellationToken)
                .ConfigureAwait(false);
        }
        catch (Exception ex)
        {
            throw Translate("Leave", ex, context);
        }

        return new V1.LeaveResponse();
    }

    public override async Task<V1.GetCurrentResponse> GetCurrent(
        V1.GetCurrentRequest request,
        ServerCallContext context
    )
    {
        var bridge = RequireBridge("GetCurrent");

        OpenWorldSnapshot? world;
        try
        {
            world = await bridge.GetCurrentAsync(context.CancellationToken).ConfigureAwait(false);
        }
        catch (Exception ex)
        {
            throw Translate("GetCurrent", ex, context);
        }

        var response = new V1.GetCurrentResponse { HasWorld = world is not null };
        if (world is not null)
        {
            response.World = ToProto(world);
        }
        return response;
    }

    private IWorldBridge RequireBridge(string rpc)
    {
        if (_bridge is null)
        {
            _log.LogWarning(
                $"World.{rpc} called but no IWorldBridge is registered; returning Unavailable."
            );
            throw new RpcException(
                new Status(StatusCode.Unavailable, "World bridge is not configured.")
            );
        }

        return _bridge;
    }

    private RpcException Translate(string rpc, Exception ex, ServerCallContext context)
    {
        if (
            ex is OperationCanceledException or IOException
            && context.CancellationToken.IsCancellationRequested
        )
        {
            // client cancelled: そのまま伝播させる。
            throw ex;
        }

        switch (ex)
        {
            case WorldNotReadyException notReady:
                _log.LogInfo($"World.{rpc}: bridge not ready: {notReady.Message}");
                return new RpcException(
                    new Status(StatusCode.FailedPrecondition, notReady.Message)
                );
            case WorldNotFoundException notFound:
                _log.LogInfo($"World.{rpc}: not found: {notFound.Message}");
                return new RpcException(new Status(StatusCode.NotFound, notFound.Message));
            default:
                _log.LogError($"World.{rpc}: bridge faulted: {ex}");
                return new RpcException(
                    new Status(StatusCode.Internal, $"World bridge faulted: {ex.Message}")
                );
        }
    }

    private static SessionFilter MapFilter(V1.SessionFilter filter) =>
        filter switch
        {
            V1.SessionFilter.Friends => SessionFilter.Friends,
            V1.SessionFilter.Headless => SessionFilter.Headless,
            // SESSION_FILTER_UNSPECIFIED → 全件。
            _ => SessionFilter.All,
        };

    private static RecordSource MapSource(V1.RecordSource source) =>
        source switch
        {
            V1.RecordSource.Featured => RecordSource.Featured,
            V1.RecordSource.Own => RecordSource.Own,
            V1.RecordSource.Group => RecordSource.Group,
            // RECORD_SOURCE_UNSPECIFIED → PUBLIC。
            _ => RecordSource.Public,
        };

    private static RecordSort MapSort(V1.RecordSort sort) =>
        sort switch
        {
            V1.RecordSort.LastUpdate => RecordSort.LastUpdate,
            V1.RecordSort.FirstPublish => RecordSort.FirstPublish,
            V1.RecordSort.TotalVisits => RecordSort.TotalVisits,
            V1.RecordSort.Name => RecordSort.Name,
            V1.RecordSort.Random => RecordSort.Random,
            // RECORD_SORT_UNSPECIFIED → CREATION_DATE。
            _ => RecordSort.CreationDate,
        };

    private static RecordSortDirection MapSortDirection(V1.RecordSortDirection direction) =>
        direction switch
        {
            V1.RecordSortDirection.Ascending => RecordSortDirection.Ascending,
            // RECORD_SORT_DIRECTION_UNSPECIFIED → DESCENDING。
            _ => RecordSortDirection.Descending,
        };

    private static V1.WorldSession ToProto(WorldSessionSnapshot snapshot)
    {
        var proto = new V1.WorldSession
        {
            SessionId = snapshot.SessionId,
            Name = snapshot.Name,
            Description = snapshot.Description,
            HostUserId = snapshot.HostUserId,
            HostUsername = snapshot.HostUsername,
            ThumbnailUrl = snapshot.ThumbnailUrl,
            JoinedUsers = snapshot.JoinedUsers,
            ActiveUsers = snapshot.ActiveUsers,
            MaximumUsers = snapshot.MaximumUsers,
            AccessLevel = snapshot.AccessLevel,
            HeadlessHost = snapshot.HeadlessHost,
            MobileFriendly = snapshot.MobileFriendly,
            CorrespondingWorldId = snapshot.CorrespondingWorldId,
            UniverseId = snapshot.UniverseId,
            SessionBeginUnixNanos = snapshot.SessionBeginUnixNanos,
            LastUpdateUnixNanos = snapshot.LastUpdateUnixNanos,
        };
        proto.SessionUrls.AddRange(snapshot.SessionUrls);
        proto.Tags.AddRange(snapshot.Tags);
        return proto;
    }

    private static V1.WorldRecord ToProto(WorldRecordSnapshot snapshot)
    {
        var proto = new V1.WorldRecord
        {
            RecordId = snapshot.RecordId,
            OwnerId = snapshot.OwnerId,
            Name = snapshot.Name,
            Description = snapshot.Description,
            ThumbnailUrl = snapshot.ThumbnailUrl,
            RecordUrl = snapshot.RecordUrl,
            LastModificationUnixNanos = snapshot.LastModificationUnixNanos,
        };
        proto.Tags.AddRange(snapshot.Tags);
        return proto;
    }

    private static V1.OpenWorld ToProto(OpenWorldSnapshot snapshot) =>
        new()
        {
            Handle = snapshot.Handle,
            SessionId = snapshot.SessionId,
            Name = snapshot.Name,
            Focused = snapshot.Focused,
            UserCount = snapshot.UserCount,
            AccessLevel = snapshot.AccessLevel,
        };
}
