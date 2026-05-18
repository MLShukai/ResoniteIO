using System;
using InterprocessLib;
using Renderite.Shared;
using ResoniteIO.Core.Bridge;
using ResoniteIO.Core.Logging;
using ResoniteIO.RendererShared;

namespace ResoniteIO.Bridge;

/// <summary>
/// Renderer plugin (Wine + Unity Mono、別プロセス) から InterprocessLib (Cloudtoid
/// 共有メモリ queue) 経由で push された camera frame を受け取り、
/// engine 側 <see cref="PushedFrameCameraBridge"/> に流す Receiver。
/// </summary>
/// <remarks>
/// <para>
/// engine 側は <c>isAuthority: true</c> で先に queue を作成する (Resonite engine
/// は renderer process より先に起動する保証あり、knowledge §3.3)。
/// </para>
/// <para>
/// Receiver の lifecycle: <see cref="Start"/> で <see cref="Messenger"/> を構築 +
/// callback 登録、<see cref="Dispose"/> で static event を確実に外して queue を
/// 破棄する (<see cref="Messenger.OnFailure"/> / <c>OnWarning</c> は static event
/// なので Dispose で -= しないと memory leak、knowledge §7)。
/// </para>
/// <para>
/// Plugin (C8 で実装) からの利用: <c>new RendererFrameInterprocessReceiver(bridge, log)</c>
/// → <c>Start()</c> → 必要なくなったら <c>Dispose()</c>。
/// </para>
/// </remarks>
public sealed class RendererFrameInterprocessReceiver : IDisposable
{
    /// <summary>frame の RGBA8 1 pixel あたりの byte 数 (validation で使用)。</summary>
    private const int BytesPerPixelRgba8 = 4;

    private readonly PushedFrameCameraBridge _bridge;
    private readonly ILogSink _log;

    private Messenger? _messenger;
    private bool _started;
    private bool _disposed;

    /// <summary>受け取った frame の総数 (debug 用)。</summary>
    public long ReceivedCount { get; private set; }

    /// <summary>validation で reject した frame の総数 (debug 用)。</summary>
    public long RejectedCount { get; private set; }

    public RendererFrameInterprocessReceiver(PushedFrameCameraBridge bridge, ILogSink log)
    {
        _bridge = bridge ?? throw new ArgumentNullException(nameof(bridge));
        _log = log ?? throw new ArgumentNullException(nameof(log));
    }

    /// <summary>queue を bind し callback を登録する。idempotent (2 度目以降は no-op)。</summary>
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
        // log は warning レベル (毎フレーム reject は queue/renderer 側の問題で
        // engine 側で対処不能のため verbose にしない)。
        _log.LogWarning(
            $"[ResoniteIO] RendererFrameInterprocessReceiver: dropped frame ({rejectReason})"
        );
    }

    /// <summary>
    /// 受信した <paramref name="data"/> を header + payload に分解し
    /// <see cref="CameraFrame"/> を組み立てる純粋関数。
    /// </summary>
    /// <remarks>
    /// header 不正 / payload 長 mismatch / size 整合性 NG をすべて検出して
    /// <paramref name="rejectReason"/> を返す。本 method は internal で
    /// <c>ResoniteIO.Tests</c> から unit test 可能。
    /// </remarks>
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
