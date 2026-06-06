using ResoniteIO.Core.Dash;

namespace ResoniteIO.Core.Tests.Common.Fakes;

/// <summary>
/// テスト用 <see cref="IDashBridge"/>。各 RPC 呼び出しを <see cref="Calls"/> に記録し
/// (どのメソッド / どの ref_id / どの GetTree フィルタ / どの scroll delta)、
/// 種別に応じて <see cref="NextState"/> / <see cref="NextTree"/> / <see cref="NextResult"/>
/// を返す。
/// </summary>
/// <remarks>
/// 自前 ABC の fake (testing-strategy: 所有している抽象のみ fake 可)。
/// <see cref="ThrowOnNextCall"/> を設定すると全 RPC でその例外を投げ、Service 層の
/// 例外翻訳 (NotReady→FailedPrecondition / ArgumentException→InvalidArgument /
/// その他→Internal) を実 wire で検証できる。ref_id 解決や interactable 判定等の
/// engine 側ロジックは再現せず、テスト側が返値 / 例外を明示的に注入する規約。
/// </remarks>
internal sealed class DashBridgeFake : IDashBridge
{
    /// <summary>fake が記録した 1 回の RPC 呼び出し。引数は呼び出した RPC によって
    /// 意味を持つものだけ非 <c>null</c> になる (例: <paramref name="RefId"/> は
    /// Invoke / Highlight / Scroll、<paramref name="InteractableOnly"/> /
    /// <paramref name="RootRefId"/> は GetTree、<paramref name="DeltaX"/> /
    /// <paramref name="DeltaY"/> は Scroll のみ)。</summary>
    public sealed record Call(
        string Method,
        string? RefId,
        bool? InteractableOnly,
        string? RootRefId,
        float? DeltaX,
        float? DeltaY
    );

    private readonly List<Call> _calls = new();
    private readonly object _gate = new();

    /// <summary>Open / Close / GetState が返す snapshot。</summary>
    public DashStateSnapshot NextState { get; set; } = new(IsOpen: false, OpenLerp: 0.0f);

    /// <summary>GetTree が返す snapshot。</summary>
    public DashTreeSnapshot NextTree { get; set; } =
        new(Elements: Array.Empty<DashElementSnapshot>(), ScreenWidth: 0, ScreenHeight: 0);

    /// <summary>Invoke / Highlight / Scroll が返す snapshot。</summary>
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

    public Task<DashTreeSnapshot> GetTreeAsync(
        bool interactableOnly,
        string rootRefId,
        CancellationToken ct
    )
    {
        Record(
            new Call(
                Method: "GetTree",
                RefId: null,
                InteractableOnly: interactableOnly,
                RootRefId: rootRefId,
                DeltaX: null,
                DeltaY: null
            ),
            ct
        );
        return Task.FromResult(NextTree);
    }

    public Task<DashActionResultSnapshot> InvokeAsync(string refId, CancellationToken ct) =>
        RecordResult("Invoke", refId, deltaX: null, deltaY: null, ct);

    public Task<DashActionResultSnapshot> HighlightAsync(string refId, CancellationToken ct) =>
        RecordResult("Highlight", refId, deltaX: null, deltaY: null, ct);

    public Task<DashActionResultSnapshot> ScrollAsync(
        string refId,
        float deltaX,
        float deltaY,
        CancellationToken ct
    ) => RecordResult("Scroll", refId, deltaX, deltaY, ct);

    private Task<DashStateSnapshot> RecordState(string method, CancellationToken ct)
    {
        Record(
            new Call(
                Method: method,
                RefId: null,
                InteractableOnly: null,
                RootRefId: null,
                DeltaX: null,
                DeltaY: null
            ),
            ct
        );
        return Task.FromResult(NextState);
    }

    private Task<DashActionResultSnapshot> RecordResult(
        string method,
        string refId,
        float? deltaX,
        float? deltaY,
        CancellationToken ct
    )
    {
        Record(
            new Call(
                Method: method,
                RefId: refId,
                InteractableOnly: null,
                RootRefId: null,
                DeltaX: deltaX,
                DeltaY: deltaY
            ),
            ct
        );
        return Task.FromResult(NextResult);
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
