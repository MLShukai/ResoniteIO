using ResoniteIO.Core.Cursor;

namespace ResoniteIO.Core.Tests.Common.Fakes;

/// <summary>
/// テスト用 <see cref="ICursorBridge"/>。各 RPC 呼び出しを <see cref="Calls"/> に
/// 記録し (どのメソッド / どの x,y)、<see cref="NextState"/> を返す。
/// </summary>
/// <remarks>
/// 自前 ABC の fake (testing-strategy: 所有している抽象のみ fake 可)。
/// <see cref="ThrowOnNextCall"/> を設定すると全 RPC でその例外を投げ、Service 層の
/// 例外翻訳 (NotReady→FailedPrecondition / その他→Internal) を実 wire で検証できる。
/// 正規化座標の範囲チェックは Service 層で行われ bridge には到達しない契約のため、
/// fake 側では検証しない。<paramref name="X"/> / <paramref name="Y"/> は SetPosition のみ
/// 意味を持ち、GetPosition では <c>null</c>。
/// </remarks>
internal sealed class CursorBridgeFake : ICursorBridge
{
    public sealed record Call(string Method, float? X, float? Y);

    private readonly List<Call> _calls = new();
    private readonly object _gate = new();

    /// <summary>各 RPC が返す snapshot。テストごとに任意の値を設定する。</summary>
    public CursorStateSnapshot NextState { get; set; } =
        new(X: 0f, Y: 0f, WindowWidth: 0, WindowHeight: 0);

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

    public Task<CursorStateSnapshot> SetPositionAsync(float x, float y, CancellationToken ct) =>
        Record("SetPosition", x, y, ct);

    public Task<CursorStateSnapshot> GetPositionAsync(CancellationToken ct) =>
        Record("GetPosition", x: null, y: null, ct);

    private Task<CursorStateSnapshot> Record(
        string method,
        float? x,
        float? y,
        CancellationToken ct
    )
    {
        ct.ThrowIfCancellationRequested();
        lock (_gate)
        {
            _calls.Add(new Call(method, x, y));
        }

        if (ThrowOnNextCall is { } ex)
        {
            throw ex;
        }

        return Task.FromResult(NextState);
    }
}
