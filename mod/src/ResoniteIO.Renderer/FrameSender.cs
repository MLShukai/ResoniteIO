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

    /// <summary><paramref name="header"/> + <paramref name="payload"/> を 1 buffer に連結して送信。</summary>
    public void Send(FrameHeader header, byte[] payload)
    {
        if (payload == null)
        {
            throw new ArgumentNullException(nameof(payload));
        }
        if (_disposed)
        {
            return;
        }

        var combined = new byte[FrameHeader.SizeInBytes + payload.Length];
        header.Write(combined);
        Buffer.BlockCopy(payload, 0, combined, FrameHeader.SizeInBytes, payload.Length);

        try
        {
            _messenger.SendValueArray<byte>(IpcSocketPaths.FrameMessageId, combined);
        }
        catch (Exception ex)
        {
            // engine 未 attach / queue full 等。capture loop が次フレームで再試行する。
            _log.LogWarning($"[ResoniteIO.Renderer] SendValueArray failed: {ex.Message}");
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
