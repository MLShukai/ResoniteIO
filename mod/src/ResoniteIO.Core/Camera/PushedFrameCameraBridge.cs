using System.Threading.Channels;

namespace ResoniteIO.Core.Camera;

/// <summary>External-push 型の <see cref="ICameraBridge"/>。renderer が push、Service が pull。</summary>
/// <remarks>
/// 内部 channel は cap=1 + DropOldest = latest-wins。drop は意図的なので毎フレーム
/// log は出さない。<see cref="CaptureAsync"/> の <c>width</c>/<c>height</c> 引数は
/// 無視: 解像度は renderer 側 framebuffer が決定し、Service の MapToProto は
/// frame 側の Width/Height を採用する。
/// </remarks>
public sealed class PushedFrameCameraBridge : ICameraBridge, IDisposable
{
    private readonly Channel<CameraFrame> _channel;
    private int _disposed;

    public PushedFrameCameraBridge()
    {
        _channel = Channel.CreateBounded<CameraFrame>(
            new BoundedChannelOptions(1)
            {
                FullMode = BoundedChannelFullMode.DropOldest,
                SingleReader = false,
                SingleWriter = false,
            }
        );
    }

    /// <summary>renderer から push されたフレームを latest-wins で enqueue する。</summary>
    /// <returns>enqueue 成功なら <c>true</c>、dispose 済みなら <c>false</c>。</returns>
    public bool Push(CameraFrame frame)
    {
        if (Volatile.Read(ref _disposed) != 0)
        {
            return false;
        }
        return _channel.Writer.TryWrite(frame);
    }

    /// <inheritdoc/>
    /// <remarks>
    /// <paramref name="width"/> / <paramref name="height"/> は無視 (renderer 駆動)。
    /// dispose 済みなら <see cref="CameraNotReadyException"/>。
    /// </remarks>
    public async Task<CameraFrame> CaptureAsync(int width, int height, CancellationToken ct)
    {
        try
        {
            return await _channel.Reader.ReadAsync(ct).ConfigureAwait(false);
        }
        catch (ChannelClosedException ex)
        {
            throw new CameraNotReadyException("PushedFrameCameraBridge has been disposed.", ex);
        }
    }

    public void Dispose()
    {
        if (Interlocked.Exchange(ref _disposed, 1) != 0)
        {
            return;
        }
        _channel.Writer.TryComplete();
    }
}
