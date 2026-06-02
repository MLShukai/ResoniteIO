using ResoniteIO.Core.ContextMenu;

namespace ResoniteIO.Core.Tests.Common.Fakes;

/// <summary>
/// テスト用 <see cref="IContextMenuBridge"/>。各 RPC 呼び出しを <see cref="Calls"/> に
/// 記録し (どのメソッド / どの hand / どの index)、<see cref="NextState"/> を返す。
/// </summary>
/// <remarks>
/// 自前 ABC の fake (testing-strategy: 所有している抽象のみ fake 可)。
/// <see cref="ThrowOnNextCall"/> を設定すると次以降の全 RPC でその例外を投げ、
/// Service 層の例外翻訳 (NotReady→FailedPrecondition / ArgumentOutOfRange→InvalidArgument /
/// その他→Internal) を実 wire で検証できる。Highlight / Invoke の index 範囲チェック等の
/// engine 側ロジックは再現せず、テスト側が <see cref="ThrowOnNextCall"/> で明示的に
/// 例外を注入する規約。
/// </remarks>
internal sealed class ContextMenuBridgeFake : IContextMenuBridge
{
    /// <summary>fake が記録した 1 回の RPC 呼び出し。<paramref name="Index"/> は
    /// Highlight / Invoke のみ意味を持ち、Open / Close / GetState では <c>null</c>。</summary>
    public sealed record Call(string Method, ContextMenuHandSelector Hand, int? Index);

    private readonly List<Call> _calls = new();
    private readonly object _gate = new();

    /// <summary>各 RPC が返す snapshot。テストごとに任意の値を設定する。</summary>
    public ContextMenuStateSnapshot NextState { get; set; } =
        new(IsOpen: false, Items: Array.Empty<ContextMenuItemSnapshot>(), HighlightedIndex: -1);

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

    public Task<ContextMenuStateSnapshot> OpenAsync(
        ContextMenuHandSelector hand,
        CancellationToken ct
    ) => Record("Open", hand, index: null, ct);

    public Task<ContextMenuStateSnapshot> CloseAsync(
        ContextMenuHandSelector hand,
        CancellationToken ct
    ) => Record("Close", hand, index: null, ct);

    public Task<ContextMenuStateSnapshot> GetStateAsync(
        ContextMenuHandSelector hand,
        CancellationToken ct
    ) => Record("GetState", hand, index: null, ct);

    public Task<ContextMenuStateSnapshot> HighlightAsync(
        ContextMenuHandSelector hand,
        int index,
        CancellationToken ct
    ) => Record("Highlight", hand, index, ct);

    public Task<ContextMenuStateSnapshot> InvokeAsync(
        ContextMenuHandSelector hand,
        int index,
        CancellationToken ct
    ) => Record("Invoke", hand, index, ct);

    private Task<ContextMenuStateSnapshot> Record(
        string method,
        ContextMenuHandSelector hand,
        int? index,
        CancellationToken ct
    )
    {
        ct.ThrowIfCancellationRequested();
        lock (_gate)
        {
            _calls.Add(new Call(method, hand, index));
        }

        if (ThrowOnNextCall is { } ex)
        {
            throw ex;
        }

        return Task.FromResult(NextState);
    }
}
