using ResoniteIO.Core.Locomotion;

namespace ResoniteIO.Core.Tests.Common.Fakes;

/// <summary>
/// テスト用 <see cref="ILocomotionBridge"/>。<see cref="SetState"/> /
/// <see cref="Reset"/> / <see cref="NotifyDisconnect"/> の履歴をそれぞれ
/// <c>lock</c> 付き append-only list に記録する no-op 実装。
/// </summary>
/// <remarks>
/// 実 Bridge と同じく stateful repeater 規約を最小限再現する: 受信した各
/// <see cref="LocomotionPartialInput"/> delta を <see cref="Deltas"/> に
/// append しつつ、<see cref="LocomotionInput.Neutral"/> を起点に
/// <see cref="LocomotionPartialInput.MergeInto"/> で畳み込んだ held-state を
/// <see cref="MergedState"/> として公開する。delta の生 sequence を見たい
/// テストは <see cref="Deltas"/>、保持 state の累積を見たいテストは
/// <see cref="MergedState"/> を直接 assert する。
/// </remarks>
internal sealed class FakeLocomotionBridge : ILocomotionBridge
{
    private readonly List<LocomotionPartialInput> _deltas = new();
    private readonly List<LocomotionResetFlags> _resets = new();
    private readonly List<LocomotionDisconnectReason> _disconnects = new();
    private readonly object _gate = new();
    private LocomotionInput _merged = LocomotionInput.Neutral;

    /// <summary>
    /// 非 null のとき <see cref="Reset"/> 呼び出し時に与えられた例外を投げる。
    /// LocomotionService.Reset の Internal 翻訳経路 (A2) を検証する。
    /// </summary>
    public Exception? ResetThrows { get; set; }

    /// <summary>SetState で受信した差分 delta の append-only 履歴。</summary>
    public IReadOnlyList<LocomotionPartialInput> Deltas
    {
        get
        {
            lock (_gate)
            {
                return _deltas.ToArray();
            }
        }
    }

    /// <summary>
    /// Neutral を起点に受信 delta を順次 <see cref="LocomotionPartialInput.MergeInto"/>
    /// で畳み込んだ現在の held-state。未送信 field が前回値を保持することの検証用。
    /// </summary>
    public LocomotionInput MergedState
    {
        get
        {
            lock (_gate)
            {
                return _merged;
            }
        }
    }

    public IReadOnlyList<LocomotionResetFlags> Resets
    {
        get
        {
            lock (_gate)
            {
                return _resets.ToArray();
            }
        }
    }

    public IReadOnlyList<LocomotionDisconnectReason> Disconnects
    {
        get
        {
            lock (_gate)
            {
                return _disconnects.ToArray();
            }
        }
    }

    public void SetState(LocomotionPartialInput delta)
    {
        lock (_gate)
        {
            _deltas.Add(delta);
            _merged = delta.MergeInto(_merged);
        }
    }

    public void Reset(LocomotionResetFlags flags)
    {
        if (ResetThrows is { } ex)
        {
            throw ex;
        }
        lock (_gate)
        {
            _resets.Add(flags);
        }
    }

    public void NotifyDisconnect(LocomotionDisconnectReason reason)
    {
        lock (_gate)
        {
            _disconnects.Add(reason);
        }
    }
}
