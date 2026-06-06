using ResoniteIO.Core.World;

namespace ResoniteIO.Core.Tests.Common.Fakes;

/// <summary>
/// テスト用 <see cref="IWorldBridge"/>。各 RPC で渡された Core query / target を
/// 記録し、テストが事前に仕込んだ canned snapshot を返す。
/// </summary>
/// <remarks>
/// 自前 ABC の fake (testing-strategy: 所有している抽象のみ fake 可)。
/// <para>
/// 重要な契約: <see cref="ListSessionsAsync"/> は <em>full filtered list</em> を返す。
/// page / page_size の slicing と total_count の算出は <see cref="WorldService"/> の責務
/// なので、この fake は決して slice しない。<see cref="ListRecordsAsync"/> は逆に
/// offset / count を bridge 側で honor する契約なので、<see cref="NextRecordPage"/> を
/// そのまま返す (Service は触らない)。
/// </para>
/// <para>
/// <see cref="ThrowOnNextCall"/> を設定すると次以降の全 RPC でその例外を投げ、
/// Service 層の例外翻訳 (WorldNotReady→FailedPrecondition / WorldNotFound→NotFound /
/// その他→Internal) を実 wire で検証できる。
/// </para>
/// </remarks>
internal sealed class FakeWorldBridge : IWorldBridge
{
    private readonly object _gate = new();

    // ----- 記録された呼び出し引数 (テストが map を検証するための観測点) -----

    public SessionListQuery? LastSessionQuery { get; private set; }
    public RecordListQuery? LastRecordQuery { get; private set; }
    public JoinTarget? LastJoinTarget { get; private set; }
    public StartWorldTarget? LastStartWorldTarget { get; private set; }
    public int? LastFocusHandle { get; private set; }
    public int? LastLeaveHandle { get; private set; }
    public string? LastFetchUri { get; private set; }
    public bool ListOpenWorldsCalled { get; private set; }
    public bool GetCurrentCalled { get; private set; }

    // ----- canned 戻り値 (テストごとに設定) -----

    /// <summary>ListSessions が返す full filtered list。Service が slice する。</summary>
    public IReadOnlyList<WorldSessionSnapshot> NextSessions { get; set; } =
        Array.Empty<WorldSessionSnapshot>();

    public RecordPage NextRecordPage { get; set; } =
        new() { Records = Array.Empty<WorldRecordSnapshot>() };

    public OpenWorldSnapshot NextOpenWorld { get; set; } = new();

    public IReadOnlyList<OpenWorldSnapshot> NextOpenWorlds { get; set; } =
        Array.Empty<OpenWorldSnapshot>();

    /// <summary>GetCurrent の戻り値。null なら "現在 focus 中のワールドなし" を表す。</summary>
    public OpenWorldSnapshot? NextCurrent { get; set; }

    /// <summary>FetchThumbnail が返す解決済みサムネ bytes + content-type。</summary>
    public ThumbnailBytesSnapshot NextThumbnail { get; set; } = new(Array.Empty<byte>(), "");

    /// <summary>非 null のとき全 RPC でこの例外を投げる (例外翻訳テスト用)。</summary>
    public Exception? ThrowOnNextCall { get; set; }

    public Task<IReadOnlyList<WorldSessionSnapshot>> ListSessionsAsync(
        SessionListQuery query,
        CancellationToken ct
    )
    {
        ct.ThrowIfCancellationRequested();
        lock (_gate)
        {
            LastSessionQuery = query;
        }
        ThrowIfConfigured();
        return Task.FromResult(NextSessions);
    }

    public Task<RecordPage> ListRecordsAsync(RecordListQuery query, CancellationToken ct)
    {
        ct.ThrowIfCancellationRequested();
        lock (_gate)
        {
            LastRecordQuery = query;
        }
        ThrowIfConfigured();
        return Task.FromResult(NextRecordPage);
    }

    public Task<OpenWorldSnapshot> JoinAsync(JoinTarget target, CancellationToken ct)
    {
        ct.ThrowIfCancellationRequested();
        lock (_gate)
        {
            LastJoinTarget = target;
        }
        ThrowIfConfigured();
        return Task.FromResult(NextOpenWorld);
    }

    public Task<OpenWorldSnapshot> StartWorldAsync(StartWorldTarget target, CancellationToken ct)
    {
        ct.ThrowIfCancellationRequested();
        lock (_gate)
        {
            LastStartWorldTarget = target;
        }
        ThrowIfConfigured();
        return Task.FromResult(NextOpenWorld);
    }

    public Task<IReadOnlyList<OpenWorldSnapshot>> ListOpenWorldsAsync(CancellationToken ct)
    {
        ct.ThrowIfCancellationRequested();
        lock (_gate)
        {
            ListOpenWorldsCalled = true;
        }
        ThrowIfConfigured();
        return Task.FromResult(NextOpenWorlds);
    }

    public Task<OpenWorldSnapshot> FocusAsync(int handle, CancellationToken ct)
    {
        ct.ThrowIfCancellationRequested();
        lock (_gate)
        {
            LastFocusHandle = handle;
        }
        ThrowIfConfigured();
        return Task.FromResult(NextOpenWorld);
    }

    public Task LeaveAsync(int handle, CancellationToken ct)
    {
        ct.ThrowIfCancellationRequested();
        lock (_gate)
        {
            LastLeaveHandle = handle;
        }
        ThrowIfConfigured();
        return Task.CompletedTask;
    }

    public Task<OpenWorldSnapshot?> GetCurrentAsync(CancellationToken ct)
    {
        ct.ThrowIfCancellationRequested();
        lock (_gate)
        {
            GetCurrentCalled = true;
        }
        ThrowIfConfigured();
        return Task.FromResult(NextCurrent);
    }

    public Task<ThumbnailBytesSnapshot> FetchThumbnailAsync(string uri, CancellationToken ct)
    {
        ct.ThrowIfCancellationRequested();
        lock (_gate)
        {
            LastFetchUri = uri;
        }
        ThrowIfConfigured();
        return Task.FromResult(NextThumbnail);
    }

    private void ThrowIfConfigured()
    {
        if (ThrowOnNextCall is { } ex)
        {
            throw ex;
        }
    }
}
