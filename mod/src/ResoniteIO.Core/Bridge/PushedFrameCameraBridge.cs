using System.Threading.Channels;

namespace ResoniteIO.Core.Bridge;

/// <summary>
/// External-push 型の <see cref="ICameraBridge"/> 実装。
/// </summary>
/// <remarks>
/// <para>
/// Camera v2 で renderer plugin (Wine + Unity) が共有メモリ queue (InterprocessLib)
/// 経由で engine 側に送ったフレームを engine 側 receiver (Wave 3 で追加) が本
/// bridge の <see cref="Push"/> で enqueue し、<see cref="CameraService"/> が
/// <see cref="CaptureAsync"/> で latest を 1 つ取り出す。
/// </para>
/// <para>
/// 内部 channel は cap=1 + <see cref="BoundedChannelFullMode.DropOldest"/>。
/// renderer の capture fps が consumer の pull fps を上回ったとき、古い frame を
/// 黙って捨てて最新だけを保持する (latest-wins)。本 drop は意図的挙動なので
/// log を出さない (毎フレーム log を出すと量が多すぎる)。
/// </para>
/// <para>
/// <see cref="CaptureAsync"/> の <c>width</c> / <c>height</c> 引数は無視する:
/// frame の解像度は renderer 側 (実際の framebuffer サイズ) が決定するため、
/// Service 層が渡す request 値はあくまでヒントでしかない。Bridge は受け取った
/// frame をそのまま返す。Service 側の MapToProto は <c>frame.Width</c> /
/// <c>frame.Height</c> を採用するので不整合は起きない。
/// </para>
/// </remarks>
public sealed class PushedFrameCameraBridge : ICameraBridge, IDisposable
{
    private readonly Channel<CameraFrame> _channel;
    private int _disposed;

    /// <summary>cap=1 + DropOldest の bounded channel で bridge を初期化する。</summary>
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

    /// <summary>
    /// renderer plugin から push されたフレームを enqueue する。
    /// </summary>
    /// <remarks>
    /// cap=1 / DropOldest により、未消費 frame があれば silent に上書きする
    /// (latest-wins)。本 bridge が dispose 済みなら何もせず返る (false)。
    /// </remarks>
    /// <returns>enqueue 成功なら <c>true</c>、dispose 済みで丸ごと無視されたなら <c>false</c>。</returns>
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
    /// <para>
    /// channel に frame が溜まっていれば即返り、無ければ <see cref="Push"/> が呼ばれる
    /// まで非同期に待つ。<paramref name="ct"/> でキャンセルされたら
    /// <see cref="OperationCanceledException"/>、bridge が dispose 済みで channel が
    /// 完了状態なら <see cref="CameraNotReadyException"/> を投げる。
    /// </para>
    /// <para>
    /// <paramref name="width"/> / <paramref name="height"/> は無視する (renderer
    /// 駆動)。詳細は class docstring 参照。
    /// </para>
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

    /// <summary>channel writer を完了させ、以降の <see cref="CaptureAsync"/> を打ち切る。</summary>
    public void Dispose()
    {
        if (Interlocked.Exchange(ref _disposed, 1) != 0)
        {
            return;
        }
        _channel.Writer.TryComplete();
    }
}
