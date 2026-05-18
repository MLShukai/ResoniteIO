using System;
using BepInEx.Logging;
using ResoniteIO.RendererShared;
using UnityEngine;
using UnityEngine.Rendering;

namespace ResoniteIO.Renderer;

/// <summary>
/// Renderite renderer の screen 出力 camera (Overlay) に CommandBuffer を attach し、
/// 毎フレーム framebuffer を <see cref="AsyncGPUReadback"/> で取り出して
/// <see cref="FrameSender"/> に push する。
/// </summary>
/// <remarks>
/// <para>
/// 知見 (knowledge §3.4): Renderer プロセスには ScreenCamera (depth=0) と
/// OverlayCamera (depth=50) の 2 つが screen 直描画している。CommandBuffer は
/// **max depth (= overlay)** に <see cref="CameraEvent.AfterEverything"/> で attach
/// し、<see cref="BuiltinRenderTextureType.CurrentActive"/> を中間 RenderTexture に
/// Blit して読み出す。
/// </para>
/// <para>
/// <see cref="AsyncGPUReadback"/> は drop-on-busy 方式 (<see cref="_inFlight"/> flag)
/// で readback queue が膨れるのを防ぐ。1 フレームで取り切れなかった capture は
/// 黙って捨てる (latest-wins の renderer 側変種; engine 側 PushedFrameCameraBridge
/// と組み合わせて 2 段の latest-wins)。
/// </para>
/// </remarks>
internal sealed class FrameCapture : IDisposable
{
    private readonly FrameSender _sender;
    private readonly ManualLogSource _log;

    private CommandBuffer? _commandBuffer;
    private RenderTexture? _captureRT;
    private Camera? _hookedCamera;
    private bool _inFlight;
    private ulong _frameId;
    private bool _disposed;

    public FrameCapture(FrameSender sender, ManualLogSource log)
    {
        _sender = sender ?? throw new ArgumentNullException(nameof(sender));
        _log = log ?? throw new ArgumentNullException(nameof(log));
    }

    /// <summary>
    /// 毎 Update tick で呼ぶ。CommandBuffer 未 attach なら attach 試行、
    /// 前回 readback が pending なら skip (drop-on-busy)。
    /// </summary>
    public void TryCapture()
    {
        if (_disposed)
        {
            return;
        }

        EnsureCommandBufferAttached();

        if (_captureRT == null)
        {
            // attach 対象の screen camera が見つからない (engine 起動直後など)。次 tick で再試行。
            return;
        }

        if (_inFlight)
        {
            return;
        }

        _inFlight = true;
        AsyncGPUReadback.Request(_captureRT, 0, TextureFormat.RGBA32, OnReadback);
    }

    /// <summary>
    /// max depth + screen 直描画 (<c>targetTexture == null</c>) の Camera に
    /// <see cref="CameraEvent.AfterEverything"/> で <see cref="CommandBuffer"/> を attach する。
    /// </summary>
    /// <remarks>
    /// hooked 済 / attach 失敗時は no-op。target が見つからない (camera がまだ無い) 状態
    /// では次 tick で再試行されることを期待する (毎 Update から呼ばれる前提)。
    /// </remarks>
    private void EnsureCommandBufferAttached()
    {
        if (_hookedCamera != null && _captureRT != null)
        {
            return;
        }

        Camera? target = null;
        var maxDepth = float.NegativeInfinity;
        foreach (var cam in Camera.allCameras)
        {
            if (!cam.enabled)
            {
                continue;
            }
            if (cam.targetTexture != null)
            {
                continue;
            }
            if (cam.depth > maxDepth)
            {
                maxDepth = cam.depth;
                target = cam;
            }
        }

        if (target == null)
        {
            return;
        }

        var rt = new RenderTexture(
            target.pixelWidth,
            target.pixelHeight,
            depth: 0,
            format: RenderTextureFormat.ARGB32
        );
        if (!rt.Create())
        {
            _log.LogWarning(
                $"[ResoniteIO.Renderer] failed to create capture RenderTexture "
                    + $"({target.pixelWidth}x{target.pixelHeight})"
            );
            return;
        }

        var cb = new CommandBuffer { name = "ResoniteIO.Capture" };
        cb.Blit(BuiltinRenderTextureType.CurrentActive, rt);
        target.AddCommandBuffer(CameraEvent.AfterEverything, cb);

        _captureRT = rt;
        _commandBuffer = cb;
        _hookedCamera = target;

        _log.LogInfo(
            $"[ResoniteIO.Renderer] attached CommandBuffer to camera "
                + $"name={target.name} depth={target.depth} size={target.pixelWidth}x{target.pixelHeight}"
        );
    }

    private void OnReadback(AsyncGPUReadbackRequest req)
    {
        try
        {
            if (req.hasError)
            {
                _log.LogWarning("[ResoniteIO.Renderer] AsyncGPUReadback returned error");
                return;
            }

            if (_disposed)
            {
                return;
            }

            var rt = _captureRT;
            if (rt == null)
            {
                return;
            }

            var bytes = req.GetData<byte>().ToArray();
            var width = (uint)rt.width;
            var height = (uint)rt.height;
            var stride = width * 4u;
            var frameId = unchecked(++_frameId);
            // net472 には DateTime.UnixEpoch が無いので即値を使う。
            // 1970-01-01T00:00:00Z の DateTime.Ticks (= 100ns 単位) は 621355968000000000。
            const long unixEpochTicks = 621_355_968_000_000_000L;
            var unixNanos = (ulong)((DateTimeOffset.UtcNow.UtcTicks - unixEpochTicks) * 100L);

            var header = new FrameHeader(
                payloadLength: (uint)bytes.Length,
                width: width,
                height: height,
                format: FrameHeader.FormatRgba8,
                stride: stride,
                unixNanos: unixNanos,
                frameId: frameId
            );

            _sender.Send(header, bytes);
        }
        finally
        {
            _inFlight = false;
        }
    }

    public void Dispose()
    {
        if (_disposed)
        {
            return;
        }
        _disposed = true;

        if (_hookedCamera != null && _commandBuffer != null)
        {
            try
            {
                _hookedCamera.RemoveCommandBuffer(CameraEvent.AfterEverything, _commandBuffer);
            }
            catch (Exception ex)
            {
                _log.LogWarning($"[ResoniteIO.Renderer] RemoveCommandBuffer threw: {ex.Message}");
            }
        }

        if (_commandBuffer != null)
        {
            _commandBuffer.Release();
            _commandBuffer = null;
        }

        if (_captureRT != null)
        {
            _captureRT.Release();
            _captureRT = null;
        }

        _hookedCamera = null;
    }
}
