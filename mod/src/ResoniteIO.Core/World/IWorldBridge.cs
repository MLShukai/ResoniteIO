namespace ResoniteIO.Core.World;

/// <summary>ライブセッション 1 件の snapshot (proto <c>WorldSession</c> から独立した Core POCO)。</summary>
public sealed record WorldSessionSnapshot
{
    public string SessionId { get; init; } = "";
    public string Name { get; init; } = "";
    public string Description { get; init; } = "";
    public string HostUserId { get; init; } = "";
    public string HostUsername { get; init; } = "";
    public IReadOnlyList<string> SessionUrls { get; init; } = Array.Empty<string>();
    public string ThumbnailUrl { get; init; } = "";
    public int JoinedUsers { get; init; }
    public int ActiveUsers { get; init; }
    public int MaximumUsers { get; init; }
    public IReadOnlyList<string> Tags { get; init; } = Array.Empty<string>();
    public string AccessLevel { get; init; } = "";
    public bool HeadlessHost { get; init; }
    public bool MobileFriendly { get; init; }
    public string CorrespondingWorldId { get; init; } = "";
    public string UniverseId { get; init; } = "";
    public long SessionBeginUnixNanos { get; init; }
    public long LastUpdateUnixNanos { get; init; }
}

/// <summary>ワールドレコード 1 件の snapshot (proto <c>WorldRecord</c> から独立した Core POCO)。</summary>
public sealed record WorldRecordSnapshot
{
    public string RecordId { get; init; } = "";
    public string OwnerId { get; init; } = "";
    public string Name { get; init; } = "";
    public string Description { get; init; } = "";
    public string ThumbnailUrl { get; init; } = "";
    public IReadOnlyList<string> Tags { get; init; } = Array.Empty<string>();
    public string RecordUrl { get; init; } = "";
    public long LastModificationUnixNanos { get; init; }
}

/// <summary>ローカルに開いているワールド 1 件の snapshot (proto <c>OpenWorld</c> から独立した Core POCO)。</summary>
public sealed record OpenWorldSnapshot
{
    public int Handle { get; init; }
    public string SessionId { get; init; } = "";
    public string Name { get; init; } = "";
    public bool Focused { get; init; }
    public int UserCount { get; init; }
    public string AccessLevel { get; init; } = "";
}

/// <summary><see cref="IWorldBridge.ListRecordsAsync"/> のサーバ側ページング結果。</summary>
public sealed record RecordPage
{
    public IReadOnlyList<WorldRecordSnapshot> Records { get; init; } =
        Array.Empty<WorldRecordSnapshot>();
    public bool HasMore { get; init; }
    public int Offset { get; init; }
}

/// <summary>ライブセッションの filter (proto <c>SessionFilter</c> の Core 対応)。</summary>
public enum SessionFilter
{
    All = 0,
    Friends = 1,
    Headless = 2,
}

/// <summary>ワールドレコードのソース (proto <c>RecordSource</c> の Core 対応)。</summary>
public enum RecordSource
{
    Public = 0,
    Featured = 1,
    Own = 2,
    Group = 3,
}

/// <summary>レコード検索の並べ替え (proto <c>RecordSort</c> の Core 対応)。</summary>
public enum RecordSort
{
    CreationDate = 0,
    LastUpdate = 1,
    FirstPublish = 2,
    TotalVisits = 3,
    Name = 4,
    Random = 5,
}

/// <summary>並べ替え方向 (proto <c>RecordSortDirection</c> の Core 対応)。</summary>
public enum RecordSortDirection
{
    Descending = 0,
    Ascending = 1,
}

/// <summary>ライブセッション一覧の問い合わせ。filter / 検索条件のみで、ページングは Service が行う。</summary>
public sealed record SessionListQuery
{
    public string Search { get; init; } = "";
    public SessionFilter Filter { get; init; } = SessionFilter.All;
    public int MinActiveUsers { get; init; }
}

/// <summary>ワールドレコード一覧の問い合わせ (サーバ側ページング込み)。</summary>
public sealed record RecordListQuery
{
    public RecordSource Source { get; init; } = RecordSource.Public;
    public IReadOnlyList<string> RequiredTags { get; init; } = Array.Empty<string>();
    public string OwnerId { get; init; } = "";
    public int Offset { get; init; }

    /// <summary>取得件数。0 なら bridge が既定値 (60) を適用する。</summary>
    public int Count { get; init; }
    public RecordSort Sort { get; init; } = RecordSort.CreationDate;
    public RecordSortDirection SortDirection { get; init; } = RecordSortDirection.Descending;
}

/// <summary>既存セッションへの join 先指定。</summary>
public sealed record JoinTarget
{
    public string SessionId { get; init; } = "";
    public string SessionUrl { get; init; } = "";
    public bool Focus { get; init; }
}

/// <summary>レコードから新規セッションを起動する対象指定。</summary>
public sealed record StartWorldTarget
{
    public string RecordId { get; init; } = "";
    public string OwnerId { get; init; } = "";
    public bool Focus { get; init; }
}

/// <summary>
/// Mod 側 (FrooxEngine) が実装し DI で注入する world 操作抽象。Service はこの IF にのみ依存する。
/// </summary>
public interface IWorldBridge
{
    /// <summary>filter 済みのライブセッション全件を返す (page / page_size の slicing と total_count は Service が行う)。</summary>
    /// <exception cref="WorldNotReadyException">cloud / engine がまだ準備できていない。</exception>
    Task<IReadOnlyList<WorldSessionSnapshot>> ListSessionsAsync(
        SessionListQuery query,
        CancellationToken ct
    );

    /// <summary>サーバ側ページング済みのワールドレコードを返す (offset / count を bridge が解釈する)。</summary>
    /// <exception cref="WorldNotReadyException">cloud / engine がまだ準備できていない。</exception>
    Task<RecordPage> ListRecordsAsync(RecordListQuery query, CancellationToken ct);

    /// <summary>既存セッションへ join し、開いたワールドの snapshot を返す。</summary>
    /// <exception cref="WorldNotReadyException">cloud / engine がまだ準備できていない。</exception>
    /// <exception cref="WorldNotFoundException">session id / url が解決できない。</exception>
    Task<OpenWorldSnapshot> JoinAsync(JoinTarget target, CancellationToken ct);

    /// <summary>レコードから新規セッションを起動し、開いたワールドの snapshot を返す。</summary>
    /// <exception cref="WorldNotReadyException">cloud / engine がまだ準備できていない。</exception>
    /// <exception cref="WorldNotFoundException">record id が解決できない。</exception>
    Task<OpenWorldSnapshot> StartWorldAsync(StartWorldTarget target, CancellationToken ct);

    /// <summary>ローカルに開いているワールド一覧を返す。</summary>
    /// <exception cref="WorldNotReadyException">cloud / engine がまだ準備できていない。</exception>
    Task<IReadOnlyList<OpenWorldSnapshot>> ListOpenWorldsAsync(CancellationToken ct);

    /// <summary>handle 指定でワールドを focus する。</summary>
    /// <exception cref="WorldNotReadyException">cloud / engine がまだ準備できていない。</exception>
    /// <exception cref="WorldNotFoundException">handle に対応するワールドが無い。</exception>
    Task<OpenWorldSnapshot> FocusAsync(int handle, CancellationToken ct);

    /// <summary>handle 指定でワールドから退出する。</summary>
    /// <exception cref="WorldNotReadyException">cloud / engine がまだ準備できていない。</exception>
    /// <exception cref="WorldNotFoundException">handle に対応するワールドが無い。</exception>
    Task LeaveAsync(int handle, CancellationToken ct);

    /// <summary>現在 focus 中のワールド snapshot。focus 中のワールドが無ければ null。</summary>
    /// <exception cref="WorldNotReadyException">cloud / engine がまだ準備できていない。</exception>
    Task<OpenWorldSnapshot?> GetCurrentAsync(CancellationToken ct);
}

/// <summary>
/// cloud / engine がまだ world 操作を受けられない状態。Service は <c>FailedPrecondition</c> に
/// 翻訳するので Client は時間を置いて retry できる。
/// </summary>
public sealed class WorldNotReadyException : Exception
{
    public WorldNotReadyException(string message)
        : base(message) { }

    public WorldNotReadyException(string message, Exception innerException)
        : base(message, innerException) { }
}

/// <summary>
/// 指定された session id / handle / record id が解決できない状態。Service は <c>NotFound</c> に翻訳する。
/// </summary>
public sealed class WorldNotFoundException : Exception
{
    public WorldNotFoundException(string message)
        : base(message) { }

    public WorldNotFoundException(string message, Exception innerException)
        : base(message, innerException) { }
}
