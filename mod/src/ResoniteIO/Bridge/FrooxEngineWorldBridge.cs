using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using FrooxEngine;
using ResoniteIO.Core.Logging;
using ResoniteIO.Core.World;
using SkyFrost.Base;
using FrooxWorld = FrooxEngine.World;
using FrooxWorldManager = FrooxEngine.WorldManager;

namespace ResoniteIO.Bridge;

/// <summary>
/// SkyFrost cloud (Sessions / Records / Contacts) と FrooxEngine の world 操作
/// (<see cref="Userspace.OpenWorld(WorldStartSettings)"/> /
/// <see cref="Userspace.LeaveSession(FrooxWorld)"/> /
/// <see cref="FrooxWorldManager.FocusWorld(FrooxWorld)"/>) を橋渡しする
/// <see cref="IWorldBridge"/> 実装。
/// </summary>
/// <remarks>
/// <para>
/// read-only な cloud 呼び出し (<c>Sessions.GetSessions</c> / <c>Records.FindRecords</c> /
/// <c>Contacts.*</c>) はそれ自体が thread-safe (内部 lock) なので engine thread への
/// marshal は不要。一方 world graph を変更する操作 (OpenWorld / LeaveSession /
/// FocusWorld、および open world 列挙のような engine state 参照) は
/// <see cref="RunOnEngineAsync{T}"/> で engine update tick 上に one-shot で marshal する
/// (memory/feedback_bridge_engine_thread_dispatch.md / FrooxEngineContextMenuBridge と同型)。
/// </para>
/// <para>
/// cloud / engine が未準備 (未ログイン、focused world 無し等) のときは
/// <see cref="WorldNotReadyException"/>、未知の handle / session id / record の場合は
/// <see cref="WorldNotFoundException"/> を投げ、Service 層がそれぞれ FailedPrecondition /
/// NotFound に翻訳する。
/// </para>
/// </remarks>
internal sealed class FrooxEngineWorldBridge : IWorldBridge
{
    private const int _defaultRecordCount = 60;

    private readonly Engine _engine;
    private readonly SkyFrostInterface _cloud;
    private readonly FrooxWorldManager _worldManager;
    private readonly SessionsManager _sessions;
    private readonly RecordsManager _records;
    private readonly ContactManager _contacts;
    private readonly RecordManager _recordManager;
    private readonly ILogSink _log;
    private readonly ThumbnailFetcher _thumbnails;

    public FrooxEngineWorldBridge(Engine engine, ILogSink log)
    {
        ArgumentNullException.ThrowIfNull(engine);
        ArgumentNullException.ThrowIfNull(log);

        _engine = engine;
        _cloud = engine.Cloud;
        _worldManager = engine.WorldManager;
        _sessions = engine.Cloud.Sessions;
        _records = engine.Cloud.Records;
        _contacts = engine.Cloud.Contacts;
        _recordManager = engine.RecordManager;
        _log = log;
        _thumbnails = new ThumbnailFetcher(engine, log);
    }

    /// <inheritdoc/>
    public Task<IReadOnlyList<WorldSessionSnapshot>> ListSessionsAsync(
        SessionListQuery query,
        CancellationToken ct
    )
    {
        ct.ThrowIfCancellationRequested();
        ArgumentNullException.ThrowIfNull(query);

        var sessions = _sessions ?? throw NotReady("SessionsManager");

        var infos = new List<SessionInfo>();
        sessions.GetSessions(infos);

        var search = query.Search;
        var result = new List<WorldSessionSnapshot>(infos.Count);
        foreach (var info in infos)
        {
            if (info is null)
            {
                continue;
            }

            if (info.ActiveUsers < query.MinActiveUsers)
            {
                continue;
            }

            if (
                !string.IsNullOrEmpty(search)
                && (
                    info.Name is null
                    || info.Name.IndexOf(search, StringComparison.OrdinalIgnoreCase) < 0
                )
            )
            {
                continue;
            }

            if (!MatchesFilter(info, query.Filter))
            {
                continue;
            }

            result.Add(ToSessionSnapshot(info));
        }

        return Task.FromResult<IReadOnlyList<WorldSessionSnapshot>>(result);
    }

    /// <inheritdoc/>
    public async Task<RecordPage> ListRecordsAsync(RecordListQuery query, CancellationToken ct)
    {
        ct.ThrowIfCancellationRequested();
        ArgumentNullException.ThrowIfNull(query);

        var records = _records ?? throw NotReady("RecordsManager");

        var count = query.Count > 0 ? query.Count : _defaultRecordCount;
        var search = new SearchParameters
        {
            Count = count,
            Offset = query.Offset,
            RecordType = "world",
            SortBy = MapSort(query.Sort),
            SortDirection = MapSortDirection(query.SortDirection),
        };

        if (query.RequiredTags.Count > 0)
        {
            search.RequiredTags = new List<string>(query.RequiredTags);
        }

        ApplySource(search, query);

        if (!string.IsNullOrWhiteSpace(query.Search))
        {
            return await SearchRecordsAsync(search, query, count, ct).ConfigureAwait(false);
        }

        ct.ThrowIfCancellationRequested();
        var cloudResult = await records.FindRecords<Record>(search).ConfigureAwait(false);
        if (cloudResult is null || !cloudResult.IsOK || cloudResult.Entity is null)
        {
            throw NotReady($"FindRecords failed: {cloudResult?.State.ToString() ?? "no response"}");
        }

        var entity = cloudResult.Entity;
        var found = entity.Records ?? new List<Record>();
        var snapshots = new List<WorldRecordSnapshot>(found.Count);
        foreach (var record in found)
        {
            if (record is null)
            {
                continue;
            }
            snapshots.Add(ToRecordSnapshot(record));
        }

        return new RecordPage
        {
            Records = snapshots,
            HasMore = entity.HasMoreResults,
            Offset = query.Offset,
        };
    }

    /// <summary>
    /// 自由文検索パス (<see cref="ListRecordsAsync"/> の <c>query.Search</c> が非空のときのみ。
    /// 空の場合の <c>FindRecords</c> パスはこれを通らず従来どおり)。
    /// <see cref="SearchQueryParser"/> で検索フレーズを optional / required / excluded 語に分解し
    /// (タグ語 <c>+term</c>=必須 / <c>-term</c>=除外 / <c>"phrase"</c>=フレーズ / 無印=任意)、
    /// Resonite 自身のページング wrapper (engine UI と同じ <see cref="RecordSearch{R}"/>) で候補を
    /// fetch しつつ、engine UI が使う <c>MergedWorldData.MatchesSearchParameters</c> と同じ
    /// substring セマンティクスを Name / Description / Tags 上で再現して絞り込む (この判定は
    /// public でないため <see cref="MatchesSearchTerms"/> で写経している)。
    /// <paramref name="count"/> 件の確定一致が貯まるか、サーバ側の残りが尽きるか、scan 上限
    /// (500) に達するまで <see cref="RecordSearch{R}.EnsureResults"/> を BatchSize 刻みで広げる。
    /// </summary>
    private async Task<RecordPage> SearchRecordsAsync(
        SearchParameters search,
        RecordListQuery query,
        int count,
        CancellationToken ct
    )
    {
        var optional = new List<string>();
        var required = new List<string>();
        var excluded = new List<string>();
        SearchQueryParser.Parse(query.Search, optional, required, excluded);

        // 明示 --tag の必須タグと、検索フレーズの "+term" 必須語をマージする。
        required.AddRange(query.RequiredTags);

        search.OptionalTags = NonEmptyOrNull(optional);
        search.RequiredTags = NonEmptyOrNull(required);
        search.ExcludedTags = NonEmptyOrNull(excluded);

        var recordSearch = new RecordSearch<Record>(search, _cloud);

        const int scanCap = 500;
        var matches = new List<WorldRecordSnapshot>(count);
        var scanned = 0;
        var target = recordSearch.BatchSize;

        while (true)
        {
            ct.ThrowIfCancellationRequested();
            await recordSearch.EnsureResults(target, throwOnError: false).ConfigureAwait(false);

            var fetched = recordSearch.Records;
            for (; scanned < fetched.Count && matches.Count < count; scanned++)
            {
                var record = fetched[scanned];
                if (record is null)
                {
                    continue;
                }
                if (MatchesSearchTerms(record, optional, required, excluded))
                {
                    matches.Add(ToRecordSnapshot(record));
                }
            }

            if (matches.Count >= count || !recordSearch.HasMoreResults || fetched.Count >= scanCap)
            {
                break;
            }

            target = fetched.Count + recordSearch.BatchSize;
        }

        return new RecordPage
        {
            Records = matches,
            HasMore = recordSearch.HasMoreResults,
            Offset = query.Offset,
        };
    }

    /// <summary>
    /// engine UI の <c>MergedWorldData.MatchesSearchParameters</c> と同じ substring 判定を
    /// レコード単体に対して再現する。excluded 語が 1 つでも見つかれば不一致、required 語が
    /// すべて含まれなければ不一致、required があれば一致、無ければ optional のいずれかが
    /// 含まれれば一致 (optional も空なら一致)。判定は Name / Description / 各 Tag への
    /// case-insensitive な <see cref="string.IndexOf(string, StringComparison)"/>。
    /// </summary>
    private static bool MatchesSearchTerms(
        Record record,
        List<string> optional,
        List<string> required,
        List<string> excluded
    )
    {
        foreach (var term in excluded)
        {
            if (ContainsTerm(record, term))
            {
                return false;
            }
        }
        foreach (var term in required)
        {
            if (!ContainsTerm(record, term))
            {
                return false;
            }
        }
        if (required.Count > 0)
        {
            return true;
        }
        if (optional.Count == 0)
        {
            return true;
        }
        foreach (var term in optional)
        {
            if (ContainsTerm(record, term))
            {
                return true;
            }
        }
        return false;
    }

    /// <summary>レコードの Name / Description / 各 Tag に <paramref name="term"/> が含まれるか (case-insensitive)。</summary>
    private static bool ContainsTerm(Record record, string term)
    {
        if (ContainsSubstring(record.Name, term) || ContainsSubstring(record.Description, term))
        {
            return true;
        }
        if (record.Tags is not null)
        {
            foreach (var tag in record.Tags)
            {
                if (ContainsSubstring(tag, term))
                {
                    return true;
                }
            }
        }
        return false;
    }

    private static bool ContainsSubstring(string? str, string term) =>
        !string.IsNullOrEmpty(str) && str.IndexOf(term, StringComparison.OrdinalIgnoreCase) >= 0;

    /// <summary>
    /// <see cref="SearchParameters"/> の tag リストへ代入する用。空なら <c>null</c> を返し
    /// (= 未指定扱い)、非空ならコピーを返す。元 <paramref name="terms"/> を共有しないよう複製する。
    /// </summary>
    private static List<string>? NonEmptyOrNull(List<string> terms) =>
        terms.Count > 0 ? new List<string>(terms) : null;

    /// <inheritdoc/>
    public async Task<OpenWorldSnapshot> JoinAsync(JoinTarget target, CancellationToken ct)
    {
        ct.ThrowIfCancellationRequested();
        ArgumentNullException.ThrowIfNull(target);

        var uris = ResolveJoinUris(target);

        var settings = new WorldStartSettings
        {
            URIs = uris,
            AutoFocus = target.Focus,
            Relation = Userspace.WorldRelation.Nest,
        };

        var world = await OpenWorldOnEngineAsync(settings, ct).ConfigureAwait(false);
        await WaitUntilWorldReadyAsync(world, ct).ConfigureAwait(false);
        if (target.Focus)
        {
            await WaitUntilFocusedAsync(world, ct).ConfigureAwait(false);
        }
        return await RunOnEngineAsync(() => ToOpenWorldSnapshot(world), ct).ConfigureAwait(false);
    }

    /// <inheritdoc/>
    public async Task<OpenWorldSnapshot> StartWorldAsync(
        StartWorldTarget target,
        CancellationToken ct
    )
    {
        ct.ThrowIfCancellationRequested();
        ArgumentNullException.ThrowIfNull(target);

        if (string.IsNullOrEmpty(target.OwnerId) || string.IsNullOrEmpty(target.RecordId))
        {
            throw new WorldNotFoundException("StartWorld requires both owner_id and record_id.");
        }

        var recordManager = _recordManager ?? throw NotReady("RecordManager");

        ct.ThrowIfCancellationRequested();
        var fetched = await recordManager
            .FetchRecord(target.OwnerId, target.RecordId)
            .ConfigureAwait(false);
        if (fetched is null || !fetched.IsOK || fetched.Entity is null)
        {
            throw new WorldNotFoundException(
                $"Record {target.OwnerId}:{target.RecordId} could not be fetched "
                    + $"({fetched?.State.ToString() ?? "no response"})."
            );
        }

        var settings = new WorldStartSettings
        {
            Record = fetched.Entity,
            AutoFocus = target.Focus,
            Relation = Userspace.WorldRelation.Nest,
        };

        var world = await OpenWorldOnEngineAsync(settings, ct).ConfigureAwait(false);
        await WaitUntilWorldReadyAsync(world, ct).ConfigureAwait(false);
        if (target.Focus)
        {
            await WaitUntilFocusedAsync(world, ct).ConfigureAwait(false);
        }
        return await RunOnEngineAsync(() => ToOpenWorldSnapshot(world), ct).ConfigureAwait(false);
    }

    /// <inheritdoc/>
    public Task<IReadOnlyList<OpenWorldSnapshot>> ListOpenWorldsAsync(CancellationToken ct)
    {
        ct.ThrowIfCancellationRequested();

        return RunOnEngineAsync<IReadOnlyList<OpenWorldSnapshot>>(
            () =>
            {
                var result = new List<OpenWorldSnapshot>();
                foreach (var world in _worldManager.Worlds)
                {
                    if (world is null || world.IsDisposed || world.IsUserspace())
                    {
                        continue;
                    }
                    result.Add(ToOpenWorldSnapshot(world));
                }
                return result;
            },
            ct
        );
    }

    /// <inheritdoc/>
    public async Task<OpenWorldSnapshot> FocusAsync(int handle, CancellationToken ct)
    {
        ct.ThrowIfCancellationRequested();

        var world = await RunOnEngineAsync(() => ResolveWorld(handle), ct).ConfigureAwait(false);

        await ResolveDispatchWorld()
            .RunOnEngineAsync(() => _worldManager.FocusWorld(world), ct)
            .ConfigureAwait(false);

        // FocusWorld は _setWorldFocus に積むだけで、FocusedWorld の更新は後続 tick。
        // 実際に focus が適用されてから snapshot しないと focused=false を返してしまう。
        await WaitUntilFocusedAsync(world, ct).ConfigureAwait(false);

        return await RunOnEngineAsync(() => ToOpenWorldSnapshot(world), ct).ConfigureAwait(false);
    }

    /// <inheritdoc/>
    public async Task LeaveAsync(int handle, CancellationToken ct)
    {
        ct.ThrowIfCancellationRequested();

        var world = await RunOnEngineAsync(() => ResolveWorld(handle), ct).ConfigureAwait(false);

        // LeaveSession は engine 側の Coroutines.StartTask で world 操作を行うため、
        // engine thread に marshal してから await する。
        await RunOnEngineTaskAsync(() => Userspace.LeaveSession(world), ct).ConfigureAwait(false);

        // LeaveSession / DestroyWorld は world 破棄を deferred で行う。実際に open world
        // から外れる (dispose 済み) まで待ってから返す。
        await WaitOnEngineUntilAsync(
                () => world.IsDisposed || !_worldManager.Worlds.Contains(world),
                $"world handle {handle} to leave",
                ct
            )
            .ConfigureAwait(false);
    }

    /// <inheritdoc/>
    public Task<OpenWorldSnapshot?> GetCurrentAsync(CancellationToken ct)
    {
        ct.ThrowIfCancellationRequested();

        return RunOnEngineAsync<OpenWorldSnapshot?>(
            () =>
            {
                var world = _worldManager.FocusedWorld;
                if (world is null || world.IsDisposed || world.IsUserspace())
                {
                    return null;
                }
                return ToOpenWorldSnapshot(world);
            },
            ct
        );
    }

    /// <inheritdoc/>
    public async Task<ThumbnailBytesSnapshot> FetchThumbnailAsync(string uri, CancellationToken ct)
    {
        try
        {
            var (data, contentType) = await _thumbnails.FetchAsync(uri, ct).ConfigureAwait(false);
            return new ThumbnailBytesSnapshot(data, contentType);
        }
        catch (ThumbnailUnavailableException ex)
        {
            throw new WorldNotFoundException(ex.Message, ex);
        }
    }

    /// <summary>
    /// session を filter 条件に照合する。Friends は host が相互フォロー contact、または
    /// session 内に在席 contact が居れば一致 (contacts 未準備なら除外)。
    /// </summary>
    private bool MatchesFilter(SessionInfo info, SessionFilter filter)
    {
        switch (filter)
        {
            case SessionFilter.Headless:
                return info.HeadlessHost;
            case SessionFilter.Friends:
                var contacts = _contacts;
                if (contacts is null)
                {
                    return false;
                }
                return contacts.IsContact(info.HostUserId, mutuallyAccepted: true)
                    || contacts.CountPresentContacts(info) > 0;
            case SessionFilter.All:
            default:
                return true;
        }
    }

    /// <summary>
    /// join 先 URI を解決する。session_url 指定ならそれを直接、session_id 指定なら cloud の
    /// session cache (<c>TryGetInfo</c>) を引いて URL 群を得る。どちらも無効なら NotFound。
    /// </summary>
    private List<Uri> ResolveJoinUris(JoinTarget target)
    {
        if (!string.IsNullOrEmpty(target.SessionUrl))
        {
            if (!Uri.TryCreate(target.SessionUrl, UriKind.Absolute, out var uri))
            {
                throw new WorldNotFoundException(
                    $"session_url '{target.SessionUrl}' is not a valid absolute URI."
                );
            }
            return new List<Uri> { uri };
        }

        if (string.IsNullOrEmpty(target.SessionId))
        {
            throw new WorldNotFoundException("Join requires either session_id or session_url.");
        }

        var sessions = _sessions ?? throw NotReady("SessionsManager");
        var info = sessions.TryGetInfo(target.SessionId);
        if (info is null)
        {
            throw new WorldNotFoundException(
                $"Session '{target.SessionId}' is not known to the cloud session cache."
            );
        }

        var uris = info.GetSessionURLs();
        if (uris is null || uris.Count == 0)
        {
            throw new WorldNotFoundException(
                $"Session '{target.SessionId}' has no joinable URLs (it may have ended)."
            );
        }
        return uris;
    }

    private void ApplySource(SearchParameters search, RecordListQuery query)
    {
        switch (query.Source)
        {
            case RecordSource.Featured:
                search.OnlyFeatured = true;
                break;
            case RecordSource.Own:
                search.ByOwner = ResolveOwnUserId();
                search.OwnerType = OwnerType.User;
                break;
            case RecordSource.Group:
                if (string.IsNullOrEmpty(query.OwnerId))
                {
                    throw new WorldNotFoundException(
                        "RecordSource.Group requires owner_id (the group id)."
                    );
                }
                search.ByOwner = query.OwnerId;
                search.OwnerType = OwnerType.Group;
                break;
            case RecordSource.Public:
            default:
                break;
        }
    }

    private string ResolveOwnUserId()
    {
        var userId = _engine.Cloud.CurrentUserID;
        if (string.IsNullOrEmpty(userId))
        {
            throw NotReady("not logged in (no current user id)");
        }
        return userId;
    }

    /// <summary>handle に対応する open world を解決する。前提: engine thread 上で呼ぶ。</summary>
    private FrooxWorld ResolveWorld(int handle)
    {
        var world = _worldManager.GetWorld(handle);
        if (world is null || world.IsDisposed)
        {
            throw new WorldNotFoundException($"No open world with handle {handle}.");
        }
        return world;
    }

    /// <summary>engine thread 上で <c>OpenWorld</c> を起動し、戻り <see cref="Task{World}"/> を await する。</summary>
    private async Task<FrooxWorld> OpenWorldOnEngineAsync(
        WorldStartSettings settings,
        CancellationToken ct
    )
    {
        var openTask = await RunOnEngineAsync(() => Userspace.OpenWorld(settings), ct)
            .ConfigureAwait(false);
        var world = await openTask.ConfigureAwait(false);
        if (world is null)
        {
            throw new WorldNotFoundException(
                "OpenWorld returned no world (the target session/record may be unavailable)."
            );
        }
        return world;
    }

    /// <summary>
    /// join/start 直後の world は <see cref="FrooxWorld.WorldState.Initializing"/> 段階で、
    /// SessionId / 名前 / focus がまだ確定していない。<see cref="FrooxWorld.WorldState.Running"/>
    /// に達するまで engine thread 上で state を polling して待つ。<c>Failed</c> は join 拒否 /
    /// エラーとして例外、timeout も例外にする (呼び出し側で FailedPrecondition にマップ)。
    /// </summary>
    private async Task WaitUntilWorldReadyAsync(FrooxWorld world, CancellationToken ct)
    {
        var timeout = TimeSpan.FromSeconds(60);
        var pollInterval = TimeSpan.FromMilliseconds(250);
        var deadline = DateTime.UtcNow + timeout;
        while (true)
        {
            ct.ThrowIfCancellationRequested();
            var state = await RunOnEngineAsync(() => world.State, ct).ConfigureAwait(false);
            if (state == FrooxWorld.WorldState.Running)
            {
                return;
            }
            if (state == FrooxWorld.WorldState.Failed)
            {
                throw new WorldNotReadyException(
                    "The world failed to load (the join was rejected or errored)."
                );
            }
            if (DateTime.UtcNow >= deadline)
            {
                throw new WorldNotReadyException(
                    $"The world did not reach a running state within {timeout.TotalSeconds:0}s."
                );
            }
            await Task.Delay(pollInterval, ct).ConfigureAwait(false);
        }
    }

    /// <summary>
    /// engine が状態変更を適用し終えるまで待つ汎用 polling。<c>FocusWorld</c> /
    /// <c>DestroyWorld</c> / <c>LeaveSession</c> は要求を pending に積んで後続 tick で
    /// 適用する deferred 操作のため、呼び出し直後に snapshot すると変更前の状態を返して
    /// しまう。<paramref name="condition"/> が engine thread 上で true になるまで待ち、
    /// timeout したら <see cref="WorldNotReadyException"/> を投げる。
    /// </summary>
    private async Task WaitOnEngineUntilAsync(
        Func<bool> condition,
        string description,
        CancellationToken ct
    )
    {
        var timeout = TimeSpan.FromSeconds(30);
        var pollInterval = TimeSpan.FromMilliseconds(100);
        var deadline = DateTime.UtcNow + timeout;
        while (true)
        {
            ct.ThrowIfCancellationRequested();
            if (await RunOnEngineAsync(condition, ct).ConfigureAwait(false))
            {
                return;
            }
            if (DateTime.UtcNow >= deadline)
            {
                throw new WorldNotReadyException(
                    $"Timed out waiting for {description} within {timeout.TotalSeconds:0}s."
                );
            }
            await Task.Delay(pollInterval, ct).ConfigureAwait(false);
        }
    }

    /// <summary>
    /// focus 要求が engine に適用され <c>FocusedWorld</c> が <paramref name="world"/> に
    /// なるまで待つ (<c>FocusWorld</c> は deferred なので即 snapshot すると focused=false)。
    /// </summary>
    private Task WaitUntilFocusedAsync(FrooxWorld world, CancellationToken ct) =>
        WaitOnEngineUntilAsync(
            () => ReferenceEquals(_worldManager.FocusedWorld, world),
            "the world to become focused",
            ct
        );

    /// <summary>
    /// engine update tick 上で <paramref name="fn"/> を one-shot 実行し結果を await する。
    /// userspace world に marshal する (常に存在する engine world を使う)。
    /// </summary>
    private Task<T> RunOnEngineAsync<T>(Func<T> fn, CancellationToken ct) =>
        ResolveDispatchWorld().RunOnEngineAsync(fn, ct);

    /// <summary>
    /// engine update tick 上で <paramref name="fn"/> (engine API を呼ぶ <see cref="Task"/> 起動)
    /// を実行し、その完了まで await する。<see cref="RunOnEngineAsync{T}"/> が engine thread 上で
    /// <paramref name="fn"/> を起動して得た <see cref="Task"/> を、続けて await する。
    /// </summary>
    private async Task RunOnEngineTaskAsync(Func<Task> fn, CancellationToken ct)
    {
        var inner = await RunOnEngineAsync(fn, ct).ConfigureAwait(false);
        await inner.ConfigureAwait(false);
    }

    /// <summary>engine thread への marshal 先 world を解決する。userspace world を優先する。</summary>
    private FrooxWorld ResolveDispatchWorld()
    {
        var world = Userspace.UserspaceWorld ?? _worldManager.FocusedWorld;
        if (world is null || world.IsDisposed)
        {
            throw NotReady("no engine world is available to dispatch onto");
        }
        return world;
    }

    private static WorldNotReadyException NotReady(string detail) =>
        new($"World cloud/engine is not ready: {detail}.");

    private static WorldSessionSnapshot ToSessionSnapshot(SessionInfo info)
    {
        return new WorldSessionSnapshot
        {
            SessionId = info.SessionId ?? "",
            Name = info.Name ?? "",
            Description = info.Description ?? "",
            HostUserId = info.HostUserId ?? "",
            HostUsername = info.HostUsername ?? "",
            SessionUrls = info.SessionURLs is null
                ? Array.Empty<string>()
                : info.SessionURLs.ToArray(),
            ThumbnailUrl = info.ThumbnailUrl ?? "",
            JoinedUsers = info.JoinedUsers,
            ActiveUsers = info.ActiveUsers,
            MaximumUsers = info.MaximumUsers,
            Tags = info.Tags is null ? Array.Empty<string>() : info.Tags.ToArray(),
            AccessLevel = info.AccessLevel.ToString(),
            HeadlessHost = info.HeadlessHost,
            MobileFriendly = info.MobileFriendly,
            CorrespondingWorldId = info.CorrespondingWorldId?.ToString() ?? "",
            UniverseId = info.UniverseId ?? "",
            SessionBeginUnixNanos = ToUnixNanos(info.SessionBeginTime),
            LastUpdateUnixNanos = ToUnixNanos(info.LastUpdate),
        };
    }

    private WorldRecordSnapshot ToRecordSnapshot(Record record)
    {
        var recordUrl = "";
        if (!string.IsNullOrEmpty(record.OwnerId) && !string.IsNullOrEmpty(record.RecordId))
        {
            try
            {
                recordUrl = _engine
                    .Cloud.Platform.GetRecordUri(record.OwnerId, record.RecordId)
                    .ToString();
            }
            catch (Exception ex)
            {
                _log.LogDebug($"WorldBridge: failed to build record URI: {ex.Message}");
            }
        }

        return new WorldRecordSnapshot
        {
            RecordId = record.RecordId ?? "",
            OwnerId = record.OwnerId ?? "",
            Name = record.Name ?? "",
            Description = record.Description ?? "",
            ThumbnailUrl = record.ThumbnailURI ?? "",
            Tags = record.Tags is null ? Array.Empty<string>() : record.Tags.ToArray(),
            RecordUrl = recordUrl,
            LastModificationUnixNanos = ToUnixNanos(record.LastModificationTime),
        };
    }

    /// <summary>open world の snapshot を構築する。前提: engine thread 上で呼ぶ。</summary>
    private OpenWorldSnapshot ToOpenWorldSnapshot(FrooxWorld world)
    {
        var accessLevel = "";
        try
        {
            accessLevel = world.AccessLevel.ToString();
        }
        catch (Exception ex)
        {
            _log.LogDebug($"WorldBridge: failed to read AccessLevel: {ex.Message}");
        }

        return new OpenWorldSnapshot
        {
            Handle = world.LocalWorldHandle,
            SessionId = world.SessionId ?? "",
            Name = world.Name ?? "",
            Focused = ReferenceEquals(_worldManager.FocusedWorld, world),
            UserCount = world.UserCount,
            AccessLevel = accessLevel,
        };
    }

    private static SearchSortParameter MapSort(RecordSort sort) =>
        sort switch
        {
            RecordSort.LastUpdate => SearchSortParameter.LastUpdateDate,
            RecordSort.FirstPublish => SearchSortParameter.FirstPublishTime,
            RecordSort.TotalVisits => SearchSortParameter.TotalVisits,
            RecordSort.Name => SearchSortParameter.Name,
            RecordSort.Random => SearchSortParameter.Random,
            RecordSort.CreationDate => SearchSortParameter.CreationDate,
            _ => SearchSortParameter.CreationDate,
        };

    private static SearchSortDirection MapSortDirection(RecordSortDirection direction) =>
        direction switch
        {
            RecordSortDirection.Ascending => SearchSortDirection.Ascending,
            RecordSortDirection.Descending => SearchSortDirection.Descending,
            _ => SearchSortDirection.Descending,
        };

    private static long ToUnixNanos(DateTime time)
    {
        var utcTicks = time.Kind == DateTimeKind.Utc ? time.Ticks : time.ToUniversalTime().Ticks;
        return (utcTicks - DateTime.UnixEpoch.Ticks) * 100L;
    }
}
