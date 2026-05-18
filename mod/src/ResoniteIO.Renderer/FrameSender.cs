using System;
using BepInEx.Logging;
using InterprocessLib;
using Renderite.Shared;
using ResoniteIO.RendererShared;

namespace ResoniteIO.Renderer;

/// <summary>
/// 1 frame 分の <see cref="FrameHeader"/> + RGBA payload を結合して
/// InterprocessLib の <see cref="Messenger"/> 経由で engine 側に push する送信路。
/// </summary>
/// <remarks>
/// <para>
/// renderer process は engine より後に起動するため non-authority として attach する
/// (<c>isAuthority: false</c>)。queue capacity は <see cref="IpcSocketPaths.QueueCapacityBytes"/>
/// (= 32 MiB) で default の 1 MiB を上書きする (1118×651 RGBA8 ≒ 2.9 MiB で
/// default は乗らない)。
/// </para>
/// <para>
/// <see cref="Messenger.OnFailure"/> / <see cref="Messenger.OnWarning"/> は static
/// event なので <see cref="Dispose"/> で必ず <c>-=</c> する (GC されない / memory leak
/// 防止)。
/// </para>
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

    /// <summary>
    /// <paramref name="header"/> (40 bytes) と <paramref name="payload"/> (RGBA bytes)
    /// を 1 つの <c>byte[]</c> に連結し <c>SendValueArray&lt;byte&gt;</c> で push する。
    /// </summary>
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
            // engine 側がまだ attach していない / queue 一杯 / 等の状況。
            // capture loop は次フレームで自動再試行するので個別の error は warning 止まり。
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
