using ResoniteIO.Core.Microphone;

namespace ResoniteIO.Core.Tests.Helpers;

/// <summary>
/// テスト用 <see cref="IMicrophoneBridge"/>。受信 frame / disconnect 履歴を
/// それぞれ <c>lock</c> 付き append-only list に記録する。
/// <see cref="ThrowNotReady"/> / <see cref="ThrowGeneric"/> で Service の例外翻訳
/// (FailedPrecondition / Internal) 経路を検証する。
/// </summary>
internal sealed class FakeMicrophoneBridge : IMicrophoneBridge
{
    private readonly List<MicrophoneFrame> _frames = new();
    private readonly List<MicrophoneDisconnectReason> _disconnects = new();
    private readonly object _gate = new();

    public bool ThrowNotReady { get; set; }

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
