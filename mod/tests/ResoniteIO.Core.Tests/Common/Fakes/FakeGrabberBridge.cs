using ResoniteIO.Core.Grabber;

namespace ResoniteIO.Core.Tests.Common.Fakes;

/// <summary>
/// テスト用 <see cref="IGrabberBridge"/>。Grab / Release / GetState の各呼び出しを
/// (hand / radius まで) <c>lock</c> 付き append-only list に記録し、手ごとに簡単な
/// 保持状態をシミュレートする。Grab で <see cref="GrabbedObjectNames"/> を保持し
/// <c>IsHolding=true</c> に、Release で空にして <c>IsHolding=false</c> に遷移するため、
/// Grab→Release の観測可能な状態変化を実 wire で検証できる。
/// </summary>
/// <remarks>
/// 自前 ABC の fake (testing-strategy: 所有している抽象のみ fake 可)。
/// <see cref="GrabSucceeds"/> を <c>false</c> にすると「レイ miss / 範囲に grabbable 無し」=
/// <c>Grabbed=false</c> かつ保持状態を変えない挙動 (proto 仕様: エラーではなく結果) を
/// 再現する。<see cref="ThrowOnNextCall"/> を設定すると全 RPC でその例外を投げ、Service 層の
/// 例外翻訳 (NotReady→FailedPrecondition / その他→Internal) を検証できる。
/// カーソルレイの計算 / raycast は engine 表面なので fake には持ち込まない —
/// hit / miss の結果だけを <see cref="GrabSucceeds"/> で script する。
/// </remarks>
internal sealed class FakeGrabberBridge : IGrabberBridge
{
    /// <summary>記録された 1 回の RPC 呼び出し。<paramref name="Radius"/> は
    /// Grab のみ意味を持ち、Release / GetState では <c>0</c>。</summary>
    public sealed record Call(string Method, GrabberHandSelector Hand, float Radius);

    private readonly List<Call> _calls = new();

    // 手ごとの保持中オブジェクト名 (空 = 何も持っていない)。
    private readonly Dictionary<GrabberHandSelector, IReadOnlyList<string>> _held = new();
    private readonly object _gate = new();

    /// <summary>Grab が成功する (レイが grabbable に hit する) か。<c>false</c> なら
    /// 「レイ miss / 範囲に grabbable 無し」を再現し <c>Grabbed=false</c> を返して保持状態を変えない。</summary>
    public bool GrabSucceeds { get; set; } = true;

    /// <summary>Grab 成功時に保持するオブジェクト名。GetState / Release の round-trip 検証に使う。</summary>
    public IReadOnlyList<string> GrabbedObjectNames { get; set; } = new[] { "GrabbedSlot" };

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

    public Task<GrabOutcome> GrabAsync(GrabberHandSelector hand, float radius, CancellationToken ct)
    {
        ct.ThrowIfCancellationRequested();
        lock (_gate)
        {
            _calls.Add(new Call("Grab", hand, radius));

            if (ThrowOnNextCall is { } ex)
            {
                throw ex;
            }

            if (GrabSucceeds)
            {
                _held[hand] = GrabbedObjectNames;
            }

            var snapshot = SnapshotLocked(hand);
            return Task.FromResult(new GrabOutcome(GrabSucceeds, snapshot));
        }
    }

    public Task<GrabSnapshot> ReleaseAsync(GrabberHandSelector hand, CancellationToken ct)
    {
        ct.ThrowIfCancellationRequested();
        lock (_gate)
        {
            _calls.Add(new Call("Release", hand, Radius: 0f));

            if (ThrowOnNextCall is { } ex)
            {
                throw ex;
            }

            _held.Remove(hand);
            return Task.FromResult(SnapshotLocked(hand));
        }
    }

    public Task<GrabSnapshot> GetStateAsync(GrabberHandSelector hand, CancellationToken ct)
    {
        ct.ThrowIfCancellationRequested();
        lock (_gate)
        {
            _calls.Add(new Call("GetState", hand, Radius: 0f));

            if (ThrowOnNextCall is { } ex)
            {
                throw ex;
            }

            return Task.FromResult(SnapshotLocked(hand));
        }
    }

    /// <summary>テスト前提条件として、指定した手に保持状態を直接仕込む (GetState 検証の Arrange)。</summary>
    public void SeedHeld(GrabberHandSelector hand, IReadOnlyList<string> objectNames)
    {
        lock (_gate)
        {
            _held[hand] = objectNames;
        }
    }

    private GrabSnapshot SnapshotLocked(GrabberHandSelector hand)
    {
        var names = _held.TryGetValue(hand, out var held) ? held : Array.Empty<string>();
        return new GrabSnapshot(hand, IsHolding: names.Count > 0, ObjectNames: names);
    }
}
