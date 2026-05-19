using ResoniteIO.Core.Bridge;

namespace ResoniteIO.Core.Tests.Helpers;

/// <summary>
/// テスト用 <see cref="ILocomotionBridge"/>。各 <see cref="LocomotionCommand"/> を
/// <see cref="Received"/> に記録するだけの no-op 実装 (engine API には触らない)。
/// </summary>
/// <remarks>
/// <see cref="ThrowNotReady"/> = true なら全 <see cref="ApplyAsync"/> で
/// <see cref="LocomotionNotReadyException"/> を投げる (FailedPrecondition 翻訳テスト用)。
/// 受信記録は <c>lock</c> でガードしているので、gRPC server が複数の concurrent
/// stream を回しても safe に読める。
/// </remarks>
internal sealed class FakeLocomotionBridge : ILocomotionBridge
{
    private readonly List<LocomotionCommand> _received = new();
    private readonly object _gate = new();

    public bool ThrowNotReady { get; set; }

    /// <summary>受信した command のスナップショット (呼び出し元はこれを後で assert する)。</summary>
    public IReadOnlyList<LocomotionCommand> Received
    {
        get
        {
            lock (_gate)
            {
                return _received.ToArray();
            }
        }
    }

    public Task ApplyAsync(LocomotionCommand command, CancellationToken ct)
    {
        if (ThrowNotReady)
        {
            throw new LocomotionNotReadyException(
                "FakeLocomotionBridge: simulated not-ready state."
            );
        }

        ct.ThrowIfCancellationRequested();

        lock (_gate)
        {
            _received.Add(command);
        }

        return Task.CompletedTask;
    }
}
