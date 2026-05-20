using ResoniteIO.Core.Microphone;

namespace ResoniteIO.Core.Tests.Helpers;

/// <summary>
/// テスト用 <see cref="IMicrophoneBridge"/>。<see cref="SubmitFrame"/> /
/// <see cref="NotifyDisconnect"/> の履歴をそれぞれ <c>lock</c> 付き append-only
/// list に記録する no-op 実装。
/// </summary>
/// <remarks>
/// <list type="bullet">
/// <item><see cref="ThrowNotReady"/> = <c>true</c> なら <see cref="SubmitFrame"/>
/// が <see cref="MicrophoneNotReadyException"/> を投げる
/// (Service が <c>FailedPrecondition</c> に翻訳する経路の検証用)。</item>
/// <item><see cref="ThrowGeneric"/> = <c>true</c> なら <see cref="SubmitFrame"/>
/// が一般例外を投げる (Service が <c>Internal</c> に翻訳する経路の検証用)。</item>
/// </list>
/// </remarks>
internal sealed class FakeMicrophoneBridge : IMicrophoneBridge
{
    private readonly List<MicrophoneFrame> _frames = new();
    private readonly List<MicrophoneDisconnectReason> _disconnects = new();
    private readonly object _gate = new();

    /// <summary>
    /// <c>true</c> のとき <see cref="SubmitFrame"/> が
    /// <see cref="MicrophoneNotReadyException"/> を投げる。
    /// </summary>
    public bool ThrowNotReady { get; set; }

    /// <summary>
    /// <c>true</c> のとき <see cref="SubmitFrame"/> が一般例外
    /// (<see cref="InvalidOperationException"/>) を投げる。
    /// </summary>
    public bool ThrowGeneric { get; set; }

    public IReadOnlyList<MicrophoneFrame> Frames
    {
        get
        {
            lock (_gate)
            {
                return _frames.ToArray();
            }
        }
    }

    public IReadOnlyList<MicrophoneDisconnectReason> Disconnects
    {
        get
        {
            lock (_gate)
            {
                return _disconnects.ToArray();
            }
        }
    }

    public void SubmitFrame(MicrophoneFrame frame)
    {
        if (ThrowNotReady)
        {
            throw new MicrophoneNotReadyException(
                "FakeMicrophoneBridge: simulated not-ready state."
            );
        }
        if (ThrowGeneric)
        {
            throw new InvalidOperationException("FakeMicrophoneBridge: simulated faulted state.");
        }
        lock (_gate)
        {
            _frames.Add(frame);
        }
    }

    public void NotifyDisconnect(MicrophoneDisconnectReason reason)
    {
        lock (_gate)
        {
            _disconnects.Add(reason);
        }
    }
}
