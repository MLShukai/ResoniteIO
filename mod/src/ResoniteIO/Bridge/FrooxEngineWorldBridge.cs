using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net.Http;
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

    /// <summary>
    /// thumbnail バイト取得用の共有 <see cref="HttpClient"/>。per-call で生成すると socket
    /// 枯渇を招くため、プロセス全体で 1 つを使い回す。
    /// </summary>
    private static readonly HttpClient _httpClient = new();

    private readonly Engine _engine;
    private readonly FrooxWorldManager _worldManager;
    private readonly SessionsManager _sessions;
    private readonly RecordsManager _records;
    private readonly ContactManager _contacts;
    private readonly RecordManager _recordManager;
    private readonly ILogSink _log;

    public FrooxEngineWorldBridge(Engine engine, ILogSink log)
    {
        ArgumentNullException.ThrowIfNull(engine);
        ArgumentNullException.ThrowIfNull(log);

        _engine = engine;
        _worldManager = engine.WorldManager;
        _sessions = engine.Cloud.Sessions;
        _records = engine.Cloud.Records;
        _contacts = engine.Cloud.Contacts;
        _recordManager = engine.RecordManager;
        _log = log;
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

        await RunOnEngineAsync(
                () =>
                {
                    _worldManager.FocusWorld(world);
                    return true;
                },
                ct
            )
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
        ct.ThrowIfCancellationRequested();

        if (string.IsNullOrEmpty(uri))
        {
            throw new WorldNotFoundException("Thumbnail uri is empty.");
        }

        var httpUri = await ResolveThumbnailUriAsync(uri, ct).ConfigureAwait(false);

        try
        {
            using var response = await _httpClient.GetAsync(httpUri, ct).ConfigureAwait(false);
            response.EnsureSuccessStatusCode();

            var bytes = await response.Content.ReadAsByteArrayAsync(ct).ConfigureAwait(false);
            var contentType =
                response.Content.Headers.ContentType?.MediaType ?? InferContentType(httpUri);

            return new ThumbnailBytesSnapshot(bytes, contentType);
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (HttpRequestException ex)
        {
            _log.LogWarning(
                $"WorldBridge: thumbnail download failed for '{httpUri}': {ex.Message}"
            );
            throw new WorldNotFoundException($"Thumbnail '{uri}' could not be downloaded.", ex);
        }
    }

    /// <summary>
    /// thumbnail uri を fetch 可能な http(s) URL に解決する。<c>resdb</c> scheme は engine の
    /// asset interface (<c>Engine.Cloud.Assets.DBToHttp</c>) で CDN URL に変換する。既に
    /// http/https ならそのまま使う。解決できなければ <see cref="WorldNotFoundException"/>。
    /// </summary>
    /// <remarks>
    /// private / 認証付きアセットには <c>Engine.AssetManager.GatherAssetFile</c> 経由の
    /// fallback もあり得るが、public CDN で足りるため現時点では実装しない。
    /// </remarks>
    private async Task<Uri> ResolveThumbnailUriAsync(string uri, CancellationToken ct)
    {
        if (!Uri.TryCreate(uri, UriKind.Absolute, out var parsed))
        {
            _log.LogWarning($"WorldBridge: thumbnail uri '{uri}' is not a valid absolute URI.");
            throw new WorldNotFoundException($"Thumbnail uri '{uri}' is not a valid absolute URI.");
        }

        if (
            parsed.Scheme.Equals("http", StringComparison.OrdinalIgnoreCase)
            || parsed.Scheme.Equals("https", StringComparison.OrdinalIgnoreCase)
        )
        {
            return parsed;
        }

        if (parsed.Scheme.Equals("resdb", StringComparison.OrdinalIgnoreCase))
        {
            // DBToHttp は cache 済み endpoint への純粋な文字列変換だが、engine cloud state を
            // 参照するため既存の dispatch helper に合わせて engine thread 上で解決する。
            var resolved = await RunOnEngineAsync(
                    () => _engine.Cloud.Assets.DBToHttp(parsed, DB_Endpoint.Default),
                    ct
                )
                .ConfigureAwait(false);
            if (resolved is null)
            {
                _log.LogWarning($"WorldBridge: resdb uri '{uri}' resolved to no http URL.");
                throw new WorldNotFoundException(
                    $"Thumbnail uri '{uri}' could not be resolved to a fetchable URL."
                );
            }
            return resolved;
        }

        _log.LogWarning($"WorldBridge: unsupported thumbnail uri scheme '{parsed.Scheme}'.");
        throw new WorldNotFoundException(
            $"Thumbnail uri '{uri}' has unsupported scheme '{parsed.Scheme}'."
        );
    }

    /// <summary>
    /// Content-Type ヘッダが無い場合に uri 拡張子から MIME を推測する。未知の拡張子は
    /// 空文字を返す (Client 側で扱う)。
    /// </summary>
    private static string InferContentType(Uri uri) =>
        Path.GetExtension(uri.AbsolutePath).ToLowerInvariant() switch
        {
            ".webp" => "image/webp",
            ".png" => "image/png",
            ".jpg" or ".jpeg" => "image/jpeg",
            _ => "",
        };

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
    private async Task<T> RunOnEngineAsync<T>(Func<T> fn, CancellationToken ct)
    {
        var world = ResolveDispatchWorld();
        var tcs = new TaskCompletionSource<T>(TaskCreationOptions.RunContinuationsAsynchronously);
        world.RunSynchronously(() =>
        {
            try
            {
                tcs.TrySetResult(fn());
            }
            catch (Exception ex)
            {
                tcs.TrySetException(ex);
            }
        });
        using (ct.Register(() => tcs.TrySetCanceled(ct)))
        {
            return await tcs.Task.ConfigureAwait(false);
        }
    }

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
