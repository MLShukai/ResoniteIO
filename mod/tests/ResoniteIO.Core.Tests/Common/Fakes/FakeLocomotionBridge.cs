using ResoniteIO.Core.Locomotion;

namespace ResoniteIO.Core.Tests.Common.Fakes;

/// <summary>
/// テスト用 <see cref="ILocomotionBridge"/>。<see cref="SetState"/> /
/// <see cref="Reset"/> / <see cref="NotifyDisconnect"/> の履歴をそれぞれ
/// <c>lock</c> 付き append-only list に記録する no-op 実装。
/// </summary>
/// <remarks>
/// 派生 "LatestState" のような Bridge 挙動シミュレーションは行わない
/// (テスト側で SetStates[^1] / Resets / Disconnects を直接 assert する規約)。
/// </remarks>
internal sealed class FakeLocomotionBridge : ILocomotionBridge
{
    private readonly List<LocomotionInput> _setStates = new();
    private readonly List<LocomotionResetFlags> _resets = new();
    private readonly List<LocomotionDisconnectReason> _disconnects = new();
    private readonly object _gate = new();

    /// <summary>
    /// 非 null のとき <see cref="Reset"/> 呼び出し時に与えられた例外を投げる。
    /// LocomotionService.Reset の Internal 翻訳経路 (A2) を検証する。
    /// </summary>
    public Exception? ResetThrows { get; set; }

    public IReadOnlyList<LocomotionInput> SetStates
    {
        get
        {
            lock (_gate)
            {
                return _setStates.ToArray();
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

    public void SetState(LocomotionInput command)
    {
        lock (_gate)
        {
            _setStates.Add(command);
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
