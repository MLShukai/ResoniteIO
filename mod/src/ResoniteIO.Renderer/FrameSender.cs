using System;
using BepInEx.Logging;
using InterprocessLib;
using Renderite.Shared;
using ResoniteIO.RendererShared;

namespace ResoniteIO.Renderer;

/// <summary>
/// <see cref="FrameHeader"/> + RGBA payload を結合して engine 側に push する送信路。
/// </summary>
/// <remarks>
/// renderer は engine より後起動なので non-authority として attach する。
/// <see cref="Messenger.OnFailure"/> / <see cref="Messenger.OnWarning"/> は static
/// event なので <see cref="Dispose"/> で必ず <c>-=</c> しないと Messenger が GC されず leak する。
/// </remarks>
internal sealed class FrameSender : IDisposable
{
    private readonly ManualLogSource _log;
    private readonly Messenger _messenger;
    private readonly object _bufferLock = new object();
    private byte[] _buffer = Array.Empty<byte>();
    private bool _disposed;

    public FrameSender(ManualLogSource log)
    {
        _log = log ?? throw new ArgumentNullException(nameof(log));

        Messenger.OnFailure += OnMessengerFailure;
        Messenger.OnWarning += OnMessengerWarning;

        _messenger = new Messenger(
            ownerId: IpcSocketPaths.OwnerId,
            isAuthority: false,
            queueName: IpcSocketPaths.QueueName,
            pool: (IMemoryPackerEntityPool?)null,
            queueCapacity: IpcSocketPaths.QueueCapacityBytes
        );

        _log.LogInfo(
            $"[ResoniteIO.Renderer] FrameSender attached: owner={IpcSocketPaths.OwnerId} "
                + $"queue={IpcSocketPaths.QueueName} capacity={IpcSocketPaths.QueueCapacityBytes}"
        );
    }

    /// <summary>
    /// <paramref name="header"/> + <paramref name="payload"/> の先頭 <paramref name="payloadLength"/>
    /// bytes を 1 buffer に連結して送信する。
    /// </summary>
    /// <remarks>
    /// <see cref="Messenger.SendValueArray{T}(string, T[])"/> は array length 全体を wire に
    /// 載せる仕様で slice / length 引数を取れないため、bin に渡す配列は必要長と一致する必要
    /// がある。毎フレーム alloc を避けるため <see cref="_buffer"/> を必要長と一致するまで
    /// grow し (= 解像度安定中は alloc 0)、不一致のときだけ再割り当てする。
    /// FrameCapture 側は単一 in-flight で gate しているので race は起きないが、
    /// 念のため <see cref="_bufferLock"/> で囲んで multi-threaded send を防ぐ。
    /// </remarks>
    public void Send(FrameHeader header, byte[] payload, int payloadLength)
    {
        if (payload == null)
        {
            throw new ArgumentNullException(nameof(payload));
        }
        if (payloadLength < 0 || payloadLength > payload.Length)
        {
            throw new ArgumentOutOfRangeException(
                nameof(payloadLength),
                $"payloadLength {payloadLength} must be in [0, {payload.Length}]."
            );
        }
        if (_disposed)
        {
            return;
        }

        lock (_bufferLock)
        {
            var needed = FrameHeader.SizeInBytes + payloadLength;
            if (_buffer.Length != needed)
            {
                _buffer = new byte[needed];
            }

            header.Write(_buffer.AsSpan(0, FrameHeader.SizeInBytes));
            Buffer.BlockCopy(payload, 0, _buffer, FrameHeader.SizeInBytes, payloadLength);

            try
            {
                _messenger.SendValueArray<byte>(IpcSocketPaths.FrameMessageId, _buffer);
            }
            catch (Exception ex)
            {
                // engine 未 attach / queue full 等。capture loop が次フレームで再試行する。
                _log.LogWarning($"[ResoniteIO.Renderer] SendValueArray failed: {ex.Message}");
            }
        }
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
            _messenger.Dispose();
        }
        catch (Exception ex)
        {
            _log.LogWarning($"[ResoniteIO.Renderer] Messenger.Dispose threw: {ex.Message}");
        }
    }

    private void OnMessengerFailure(Exception ex)
    {
        _log.LogError($"[ResoniteIO.Renderer] Messenger.OnFailure: {ex}");
    }

    private void OnMessengerWarning(string message)
    {
        _log.LogWarning($"[ResoniteIO.Renderer] Messenger.OnWarning: {message}");
    }
}
