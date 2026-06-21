using ResoniteIO.Core.Grabber;

namespace ResoniteIO.Core.Tests.Common.Fakes;

/// <summary>
/// テスト用 <see cref="IGrabberBridge"/>。Grab / Release / GetState / Use / Unuse /
/// Equip / Dequip の各呼び出しを (hand / radius / button まで) <c>lock</c> 付き
/// append-only list に記録し、手ごとに簡単な保持 / 装備 / hold 状態をシミュレートする。
/// Grab で <see cref="GrabbedObjectNames"/> を保持し <c>IsHolding=true</c> に、Release で
/// 空にして <c>IsHolding=false</c> に遷移する。Use で (手, ボタン) を hold 集合へ入れ Unuse で
/// 外す。Equip で <see cref="EquippedToolName"/> を装備し Dequip で外すため、これら操作の
/// 観測可能な状態変化を実 wire で検証できる。
/// </summary>
/// <remarks>
/// 自前 ABC の fake (testing-strategy: 所有している抽象のみ fake 可)。
/// <see cref="GrabSucceeds"/> を <c>false</c> にすると「レイ miss / 範囲に grabbable 無し」=
/// <c>Grabbed=false</c> かつ保持状態を変えない挙動 (proto 仕様: エラーではなく結果) を
/// 再現する。<see cref="ThrowOnNextCall"/> を設定すると全 RPC でその例外を投げ、Service 層の
/// 例外翻訳 (NotReady→FailedPrecondition / その他→Internal) を検証できる。
/// カーソルレイの計算 / raycast / 入力注入 (ExternalInput) / 整列は engine 表面なので fake には
/// 持ち込まない — hit / miss / 保持 / 装備 / hold の結果状態だけを script する。
/// </remarks>
internal sealed class FakeGrabberBridge : IGrabberBridge
{
    /// <summary>記録された 1 回の RPC 呼び出し。<paramref name="Radius"/> は Grab のみ、
    /// <paramref name="Button"/> は Use / Unuse のみ意味を持ち、それ以外では既定値。</summary>
    public sealed record Call(
        string Method,
        GrabberHandSelector Hand,
        float Radius = 0f,
        GrabberButtonSelector? Button = null
    );

    private readonly List<Call> _calls = new();

    // 手ごとの保持中オブジェクト名 (空 = 何も持っていない)。
    private readonly Dictionary<GrabberHandSelector, IReadOnlyList<string>> _held = new();

    // 手ごとの hold 中ボタン (Use 済み Unuse 前)。
    private readonly Dictionary<GrabberHandSelector, HashSet<GrabberButtonSelector>> _heldButtons =
        new();

    // 手ごとの装備中 tool 名 (null = 未装備)。
    private readonly Dictionary<GrabberHandSelector, string> _equipped = new();

    private readonly object _gate = new();

    /// <summary>Grab が成功する (レイが grabbable に hit する) か。<c>false</c> なら
    /// 「レイ miss / 範囲に grabbable 無し」を再現し <c>Grabbed=false</c> を返して保持状態を変えない。</summary>
    public bool GrabSucceeds { get; set; } = true;

    /// <summary>Grab 成功時に保持するオブジェクト名。GetState / Release の round-trip 検証に使う。</summary>
    public IReadOnlyList<string> GrabbedObjectNames { get; set; } = new[] { "GrabbedSlot" };

    /// <summary>Equip が成功する (grab 中に装備可能な tool がある) か。<c>false</c> なら no-op。</summary>
    public bool EquipSucceeds { get; set; } = true;

    /// <summary>Equip 成功時に装備する tool の slot 名。Equip / Dequip の round-trip 検証に使う。</summary>
    public string EquippedToolName { get; set; } = "Pen";

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
            _calls.Add(new Call("Release", hand));

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
            _calls.Add(new Call("GetState", hand));

            if (ThrowOnNextCall is { } ex)
            {
                throw ex;
            }

            return Task.FromResult(SnapshotLocked(hand));
        }
    }

    public Task<GrabSnapshot> UseAsync(
        GrabberHandSelector hand,
        GrabberButtonSelector button,
        CancellationToken ct
    )
    {
        ct.ThrowIfCancellationRequested();
        lock (_gate)
        {
            _calls.Add(new Call("Use", hand, Button: button));

            if (ThrowOnNextCall is { } ex)
            {
                throw ex;
            }

            HeldButtonsLocked(hand).Add(button);
            return Task.FromResult(SnapshotLocked(hand));
        }
    }

    public Task<GrabSnapshot> UnuseAsync(
        GrabberHandSelector hand,
        GrabberButtonSelector button,
        CancellationToken ct
    )
    {
        ct.ThrowIfCancellationRequested();
        lock (_gate)
        {
            _calls.Add(new Call("Unuse", hand, Button: button));

            if (ThrowOnNextCall is { } ex)
            {
                throw ex;
            }

            HeldButtonsLocked(hand).Remove(button);
            return Task.FromResult(SnapshotLocked(hand));
        }
    }

    public Task<GrabSnapshot> EquipAsync(GrabberHandSelector hand, CancellationToken ct)
    {
        ct.ThrowIfCancellationRequested();
        lock (_gate)
        {
            _calls.Add(new Call("Equip", hand));

            if (ThrowOnNextCall is { } ex)
            {
                throw ex;
            }

            if (EquipSucceeds)
            {
                _equipped[hand] = EquippedToolName;
            }
            return Task.FromResult(SnapshotLocked(hand));
        }
    }

    public Task<GrabSnapshot> DequipAsync(GrabberHandSelector hand, CancellationToken ct)
    {
        ct.ThrowIfCancellationRequested();
        lock (_gate)
        {
            _calls.Add(new Call("Dequip", hand));

            if (ThrowOnNextCall is { } ex)
            {
                throw ex;
            }

            _equipped.Remove(hand);
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

    /// <summary>テスト前提条件として、指定した手に装備中 tool を直接仕込む (Dequip 検証の Arrange)。</summary>
    public void SeedEquipped(GrabberHandSelector hand, string toolName)
    {
        lock (_gate)
        {
            _equipped[hand] = toolName;
        }
    }

    private HashSet<GrabberButtonSelector> HeldButtonsLocked(GrabberHandSelector hand)
    {
        if (!_heldButtons.TryGetValue(hand, out var set))
        {
            set = new HashSet<GrabberButtonSelector>();
            _heldButtons[hand] = set;
        }
        return set;
    }

    private GrabSnapshot SnapshotLocked(GrabberHandSelector hand)
    {
        var names = _held.TryGetValue(hand, out var held) ? held : Array.Empty<string>();
        var equippedName = _equipped.TryGetValue(hand, out var tool) ? tool : string.Empty;
        var heldButtons = _heldButtons.TryGetValue(hand, out var buttons)
            ? buttons.ToArray()
            : Array.Empty<GrabberButtonSelector>();
        return new GrabSnapshot(
            hand,
            IsHolding: names.Count > 0,
            ObjectNames: names,
            IsToolEquipped: equippedName.Length > 0,
            EquippedToolName: equippedName,
            HeldButtons: heldButtons
        );
    }
}
