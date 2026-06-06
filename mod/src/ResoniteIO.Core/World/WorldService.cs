using Google.Protobuf;
using Grpc.Core;
using ResoniteIO.Core.Logging;
using ResoniteIO.Core.Rpc;

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

    /// <summary>
    /// filter 済み全件を bridge から受け取り、Service 側で page / page_size に slice する
    /// (total_count は slice 前の全件数)。page_size=0 は全件を 1 ページで返す。
    /// </summary>
    public override async Task<V1.ListSessionsResponse> ListSessions(
        V1.ListSessionsRequest request,
        ServerCallContext context
    )
    {
        var query = new SessionListQuery
        {
            Search = request.Search,
            Filter = MapFilter(request.Filter),
            MinActiveUsers = request.MinActiveUsers,
        };

        var sessions = await CallBridgeAsync(
                "ListSessions",
                context,
                (bridge, ct) => bridge.ListSessionsAsync(query, ct)
            )
            .ConfigureAwait(false);

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

    /// <summary>サーバ側ページング (offset / count) を bridge に委ね、結果をそのまま返す。</summary>
    public override async Task<V1.ListRecordsResponse> ListRecords(
        V1.ListRecordsRequest request,
        ServerCallContext context
    )
    {
        var query = new RecordListQuery
        {
            Source = MapSource(request.Source),
            RequiredTags = request.RequiredTags.ToArray(),
            Search = request.Search,
            OwnerId = request.OwnerId,
            Offset = (int)request.Offset,
            Count = (int)request.Count,
            Sort = MapSort(request.Sort),
            SortDirection = MapSortDirection(request.SortDirection),
        };

        var pageResult = await CallBridgeAsync(
                "ListRecords",
                context,
                (bridge, ct) => bridge.ListRecordsAsync(query, ct)
            )
            .ConfigureAwait(false);

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

    /// <summary>既存セッションへ join する (bridge が Running まで block する)。</summary>
    public override async Task<V1.JoinResponse> Join(
        V1.JoinRequest request,
        ServerCallContext context
    )
    {
        var target = new JoinTarget
        {
            SessionId = request.SessionId,
            SessionUrl = request.SessionUrl,
            Focus = request.Focus,
        };

        var world = await CallBridgeAsync(
                "Join",
                context,
                (bridge, ct) => bridge.JoinAsync(target, ct)
            )
            .ConfigureAwait(false);

        return new V1.JoinResponse { World = ToProto(world) };
    }

    /// <summary>レコードから新規セッションを起動する (bridge が Running まで block する)。</summary>
    public override async Task<V1.StartWorldResponse> StartWorld(
        V1.StartWorldRequest request,
        ServerCallContext context
    )
    {
        var target = new StartWorldTarget
        {
            RecordId = request.RecordId,
            OwnerId = request.OwnerId,
            Focus = request.Focus,
        };

        var world = await CallBridgeAsync(
                "StartWorld",
                context,
                (bridge, ct) => bridge.StartWorldAsync(target, ct)
            )
            .ConfigureAwait(false);

        return new V1.StartWorldResponse { World = ToProto(world) };
    }

    /// <summary>ローカルに開いているワールド (userspace 除く) を列挙する。</summary>
    public override async Task<V1.ListOpenWorldsResponse> ListOpenWorlds(
        V1.ListOpenWorldsRequest request,
        ServerCallContext context
    )
    {
        var worlds = await CallBridgeAsync(
                "ListOpenWorlds",
                context,
                (bridge, ct) => bridge.ListOpenWorldsAsync(ct)
            )
            .ConfigureAwait(false);

        var response = new V1.ListOpenWorldsResponse();
        foreach (var world in worlds)
        {
            response.Worlds.Add(ToProto(world));
        }
        return response;
    }

    /// <summary>handle 指定のワールドを focus し、その snapshot を返す。</summary>
    public override async Task<V1.FocusResponse> Focus(
        V1.FocusRequest request,
        ServerCallContext context
    )
    {
        var world = await CallBridgeAsync(
                "Focus",
                context,
                (bridge, ct) => bridge.FocusAsync(request.Handle, ct)
            )
            .ConfigureAwait(false);

        return new V1.FocusResponse { World = ToProto(world) };
    }

    /// <summary>handle 指定のワールドから退出する。</summary>
    public override async Task<V1.LeaveResponse> Leave(
        V1.LeaveRequest request,
        ServerCallContext context
    )
    {
        await CallBridgeAsync(
                "Leave",
                context,
                async (bridge, ct) =>
                {
                    await bridge.LeaveAsync(request.Handle, ct).ConfigureAwait(false);
                    return true;
                }
            )
            .ConfigureAwait(false);

        return new V1.LeaveResponse();
    }

    /// <summary>
    /// focus 中のワールド snapshot を返す。focus 中が無い (userspace のみ) 場合は
    /// <c>has_world=false</c> を返す。
    /// </summary>
    public override async Task<V1.GetCurrentResponse> GetCurrent(
        V1.GetCurrentRequest request,
        ServerCallContext context
    )
    {
        var world = await CallBridgeAsync(
                "GetCurrent",
                context,
                (bridge, ct) => bridge.GetCurrentAsync(ct)
            )
            .ConfigureAwait(false);

        var response = new V1.GetCurrentResponse { HasWorld = world is not null };
        if (world is not null)
        {
            response.World = ToProto(world);
        }
        return response;
    }

    /// <summary>
    /// 指定 URI のサムネイル画像を bridge 経由で取得する。uri が空なら bridge を呼ばず
    /// <c>InvalidArgument</c> を返す。
    /// </summary>
    public override async Task<V1.FetchThumbnailResponse> FetchThumbnail(
        V1.FetchThumbnailRequest request,
        ServerCallContext context
    )
    {
        if (string.IsNullOrWhiteSpace(request.Uri))
        {
            throw new RpcException(
                new Status(StatusCode.InvalidArgument, "uri must not be empty.")
            );
        }

        var snapshot = await CallBridgeAsync(
                "FetchThumbnail",
                context,
                (bridge, ct) => bridge.FetchThumbnailAsync(request.Uri, ct)
            )
            .ConfigureAwait(false);

        return new V1.FetchThumbnailResponse
        {
            Data = ByteString.CopyFrom(snapshot.Data),
            ContentType = snapshot.ContentType,
        };
    }

    /// <summary>
    /// bridge 未登録なら <c>Unavailable</c>、bridge 呼び出しが投げた例外は
    /// gRPC Status (FailedPrecondition / NotFound / Internal) に翻訳する共通ラッパ。
    /// client cancel (<see cref="OperationCanceledException"/> / <see cref="IOException"/> かつ
    /// token cancel 済み) はそのまま伝播させる。
    /// </summary>
    private async Task<T> CallBridgeAsync<T>(
        string rpc,
        ServerCallContext context,
        Func<IWorldBridge, CancellationToken, Task<T>> call
    )
    {
        var bridge = BridgeGuard.Require(_bridge, _log, "World", "IWorldBridge", rpc);

        try
        {
            return await call(bridge, context.CancellationToken).ConfigureAwait(false);
        }
        catch (Exception ex)
            when (ex is not (OperationCanceledException or IOException)
                || !context.CancellationToken.IsCancellationRequested
            )
        {
            // client cancel は filter で除外され、ここには来ない (そのまま伝播)。
            throw Translate(rpc, ex);
        }
    }

    private RpcException Translate(string rpc, Exception ex)
    {
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
