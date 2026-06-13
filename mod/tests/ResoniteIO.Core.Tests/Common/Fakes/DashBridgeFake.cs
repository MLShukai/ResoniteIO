using ResoniteIO.Core.Dash;

namespace ResoniteIO.Core.Tests.Common.Fakes;

/// <summary>
/// テスト用 <see cref="IDashBridge"/>。各 RPC 呼び出しを <see cref="Calls"/> に記録し
/// (どのメソッド / どの ref_id / SetTab の locale_key / ListControls の include_disabled /
/// Scroll の delta)、種別に応じて <see cref="NextState"/> / <see cref="NextTabList"/> /
/// <see cref="NextControlList"/> / <see cref="NextResult"/> を返す。
/// </summary>
/// <remarks>
/// 自前 ABC の fake (testing-strategy: 所有している抽象のみ fake 可)。
/// <see cref="ThrowOnNextCall"/> を設定すると全 RPC でその例外を投げ、Service 層の
/// 例外翻訳 (NotReady→FailedPrecondition / ArgumentException→InvalidArgument /
/// その他→Internal) を実 wire で検証できる。ref_id 解決 / control 列挙 / label 解決等の
/// engine 側ロジックは再現せず、テスト側が返値 / 例外を明示的に注入する規約。
/// </remarks>
internal sealed class DashBridgeFake : IDashBridge
{
    /// <summary>fake が記録した 1 回の RPC 呼び出し。引数は呼び出した RPC によって
    /// 意味を持つものだけ非 <c>null</c> になる (例: <see cref="RefId"/> は
    /// Invoke / Highlight / Scroll / SetTab、<see cref="LocaleKey"/> は SetTab、
    /// <see cref="IncludeDisabled"/> は ListControls、<see cref="DeltaX"/> /
    /// <see cref="DeltaY"/> は Scroll のみ)。</summary>
    public sealed record Call(
        string Method,
        string? RefId = null,
        string? LocaleKey = null,
        bool? IncludeDisabled = null,
        float? DeltaX = null,
        float? DeltaY = null
    );

    private readonly List<Call> _calls = new();
    private readonly object _gate = new();

    /// <summary>Open / Close / GetState が返す snapshot。</summary>
    public DashStateSnapshot NextState { get; set; } = new(IsOpen: false, OpenLerp: 0.0f);

    /// <summary>ListTabs が返す snapshot。</summary>
    public DashTabListSnapshot NextTabList { get; set; } =
        new(Tabs: Array.Empty<DashTabSnapshot>());

    /// <summary>ListControls が返す snapshot。</summary>
    public DashControlListSnapshot NextControlList { get; set; } =
        new(Controls: Array.Empty<DashControlSnapshot>());

    /// <summary>SetTab / Invoke / Scroll / Highlight が返す snapshot。</summary>
    public DashActionResultSnapshot NextResult { get; set; } =
        new(Ok: false, Found: false, RefId: "", Detail: "");

    /// <summary>非 null のとき全 RPC でこの例外を投げる (例外翻訳テスト用)。</summary>
    public Exception? ThrowOnNextCall { get; set; }

    public IReadOnlyList<Call> Calls
    {
        get
        {
            lock (_gate)
            {
                return _calls.ToArray();
            }
        }
    }

    public Task<DashStateSnapshot> OpenAsync(CancellationToken ct) => RecordState("Open", ct);

    public Task<DashStateSnapshot> CloseAsync(CancellationToken ct) => RecordState("Close", ct);

    public Task<DashStateSnapshot> GetStateAsync(CancellationToken ct) =>
        RecordState("GetState", ct);

    public Task<DashTabListSnapshot> ListTabsAsync(CancellationToken ct)
    {
        Record(new Call(Method: "ListTabs"), ct);
        return Task.FromResult(NextTabList);
    }

    public Task<DashActionResultSnapshot> SetTabAsync(
        string refId,
        string localeKey,
        CancellationToken ct
    )
    {
        Record(new Call(Method: "SetTab", RefId: refId, LocaleKey: localeKey), ct);
        return Task.FromResult(NextResult);
    }

    public Task<DashControlListSnapshot> ListControlsAsync(
        bool includeDisabled,
        CancellationToken ct
    )
    {
        Record(new Call(Method: "ListControls", IncludeDisabled: includeDisabled), ct);
        return Task.FromResult(NextControlList);
    }

    public Task<DashActionResultSnapshot> InvokeAsync(string refId, CancellationToken ct)
    {
        Record(new Call(Method: "Invoke", RefId: refId), ct);
        return Task.FromResult(NextResult);
    }

    public Task<DashActionResultSnapshot> ScrollAsync(
        string refId,
        float deltaX,
        float deltaY,
        CancellationToken ct
    )
    {
        Record(new Call(Method: "Scroll", RefId: refId, DeltaX: deltaX, DeltaY: deltaY), ct);
        return Task.FromResult(NextResult);
    }

    public Task<DashActionResultSnapshot> HighlightAsync(string refId, CancellationToken ct)
    {
        Record(new Call(Method: "Highlight", RefId: refId), ct);
        return Task.FromResult(NextResult);
    }

    private Task<DashStateSnapshot> RecordState(string method, CancellationToken ct)
    {
        Record(new Call(Method: method), ct);
        return Task.FromResult(NextState);
    }

    private void Record(Call call, CancellationToken ct)
    {
        ct.ThrowIfCancellationRequested();
        lock (_gate)
        {
            _calls.Add(call);
        }

        if (ThrowOnNextCall is { } ex)
        {
            throw ex;
        }
    }
}
