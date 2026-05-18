using System;
using InterprocessLib;
using Renderite.Shared;
using ResoniteIO.Core.Bridge;
using ResoniteIO.Core.Logging;
using ResoniteIO.RendererShared;

namespace ResoniteIO.Bridge;

/// <summary>
/// Renderer plugin から共有メモリ queue 経由で push された camera frame を受け取り、
/// engine 側 <see cref="PushedFrameCameraBridge"/> に流す Receiver。
/// </summary>
/// <remarks>
/// engine 側は <c>isAuthority: true</c> で queue を作成する (engine が renderer
/// より先に起動するため、camera-v2-constraints §3.3)。<see cref="Messenger.OnFailure"/>
/// / <c>OnWarning</c> は static event のため <see cref="Dispose"/> で <c>-=</c>
/// しないと Messenger インスタンスが GC されず leak する。
/// </remarks>
public sealed class RendererFrameInterprocessReceiver : IDisposable
{
    private const int BytesPerPixelRgba8 = 4;

    private readonly PushedFrameCameraBridge _bridge;
    private readonly ILogSink _log;

    private Messenger? _messenger;
    private bool _started;
    private bool _disposed;

    public long ReceivedCount { get; private set; }

    public long RejectedCount { get; private set; }

    public RendererFrameInterprocessReceiver(PushedFrameCameraBridge bridge, ILogSink log)
    {
        _bridge = bridge ?? throw new ArgumentNullException(nameof(bridge));
        _log = log ?? throw new ArgumentNullException(nameof(log));
    }

    /// <summary>queue を bind し callback を登録する。idempotent。</summary>
    /// <exception cref="ObjectDisposedException">既に <see cref="Dispose"/> 済み。</exception>
    public void Start()
    {
        if (_disposed)
        {
            throw new ObjectDisposedException(nameof(RendererFrameInterprocessReceiver));
        }
        if (_started)
        {
            return;
        }
        _started = true;

        Messenger.OnFailure += OnMessengerFailure;
        Messenger.OnWarning += OnMessengerWarning;

        _messenger = new Messenger(
            ownerId: IpcSocketPaths.OwnerId,
            isAuthority: true,
            queueName: IpcSocketPaths.QueueName,
            pool: (IMemoryPackerEntityPool?)null,
            queueCapacity: IpcSocketPaths.QueueCapacityBytes
        );
        _messenger.ReceiveValueArray<byte>(IpcSocketPaths.FrameMessageId, OnFrameReceived);

        _log.LogInfo(
            $"[ResoniteIO] RendererFrameInterprocessReceiver listening: owner={IpcSocketPaths.OwnerId} "
                + $"queue={IpcSocketPaths.QueueName} capacity={IpcSocketPaths.QueueCapacityBytes}"
        );
    }

    public void Dispose()
    {
        if (_disposed)
        {
            return;
        }
        _disposed = true;

        // static event の参照を確実に外す (knowledge §7 落とし穴 #8)。
        Messenger.OnFailure -= OnMessengerFailure;
        Messenger.OnWarning -= OnMessengerWarning;

        try
        {
            _messenger?.Dispose();
        }
        catch (Exception ex)
        {
            _log.LogWarning(
                $"[ResoniteIO] RendererFrameInterprocessReceiver: Messenger.Dispose threw: {ex.Message}"
            );
        }
        _messenger = null;
    }

    private void OnFrameReceived(byte[]? data)
    {
        ReceivedCount++;

        if (TryParseFrame(data, out var frame, out var rejectReason))
        {
            _bridge.Push(frame);
            return;
        }

        RejectedCount++;
        // reject は queue / renderer 側の不整合で engine 側で対処不能なので warning 止まり。
        _log.LogWarning(
            $"[ResoniteIO] RendererFrameInterprocessReceiver: dropped frame ({rejectReason})"
        );
    }

    /// <summary>
    /// <paramref name="data"/> を header + payload に分解して <see cref="CameraFrame"/>
    /// を組み立てる。検証 NG なら理由を <paramref name="rejectReason"/> に詰める。
    /// </summary>
    internal static bool TryParseFrame(
        byte[]? data,
        out CameraFrame frame,
        out string? rejectReason
    )
    {
        frame = default;
        rejectReason = null;

        if (data == null)
        {
            rejectReason = "null data";
            return false;
        }
        if (data.Length < FrameHeader.SizeInBytes)
        {
            rejectReason = $"too short ({data.Length} < {FrameHeader.SizeInBytes} bytes)";
            return false;
        }

        FrameHeader header;
        try
        {
            header = FrameHeader.Read(new ReadOnlySpan<byte>(data, 0, FrameHeader.SizeInBytes));
        }
        catch (ArgumentException ex)
        {
            rejectReason = $"invalid header: {ex.Message}";
            return false;
        }

        if (header.Format != FrameHeader.FormatRgba8)
        {
            rejectReason = $"unsupported format {header.Format}";
            return false;
        }

        var payloadOffset = FrameHeader.SizeInBytes;
        var payloadCount = data.Length - payloadOffset;
        if ((int)header.PayloadLength != payloadCount)
        {
            rejectReason =
                $"payload length mismatch: header={header.PayloadLength} actual={payloadCount}";
            return false;
        }

        // RGBA8 sanity: width * height * 4 == payload
        var expected = (long)header.Width * header.Height * BytesPerPixelRgba8;
        if (expected != header.PayloadLength)
        {
            rejectReason =
                $"size mismatch: {header.Width}x{header.Height}*4={expected} != {header.PayloadLength}";
            return false;
        }

        var pixels = new byte[payloadCount];
        Buffer.BlockCopy(data, payloadOffset, pixels, 0, payloadCount);

        frame = new CameraFrame(
            Pixels: pixels,
            Width: (int)header.Width,
            Height: (int)header.Height,
            UnixNanos: (long)header.UnixNanos,
            FrameId: (long)header.FrameId,
            Format: CameraFrameFormat.Rgba8
        );
        return true;
    }

    private void OnMessengerFailure(Exception ex)
    {
        _log.LogError($"[ResoniteIO] RendererFrameInterprocessReceiver: Messenger.OnFailure: {ex}");
    }

    private void OnMessengerWarning(string message)
    {
        _log.LogWarning(
            $"[ResoniteIO] RendererFrameInterprocessReceiver: Messenger.OnWarning: {message}"
        );
    }
}
