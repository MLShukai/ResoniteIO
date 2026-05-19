using System;
using BepInEx.Logging;
using ResoniteIO.RendererShared;
using UnityEngine;
using UnityEngine.Rendering;

namespace ResoniteIO.Renderer;

/// <summary>
/// Renderite renderer の screen 出力 camera (max depth = Overlay) に CommandBuffer
/// を attach し、毎フレーム framebuffer を <see cref="AsyncGPUReadback"/> で取り出して
/// <see cref="FrameSender"/> に push する。
/// </summary>
/// <remarks>
/// Renderer プロセスには ScreenCamera (depth=0) と OverlayCamera (depth=50) の 2 つ
/// が screen 直描画しているので max depth を選ぶ (camera-v2-constraints §3.4)。
/// <see cref="AsyncGPUReadback"/> は drop-on-busy (<see cref="_inFlight"/>) で
/// readback queue が膨れるのを防ぎ、取り切れない capture は黙って捨てる。
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

    /// <summary>毎 Update tick で呼ぶ。pending な readback があれば drop-on-busy で skip。</summary>
    public void TryCapture()
    {
        if (_disposed)
        {
            return;
        }

        EnsureCommandBufferAttached();

        if (_captureRT == null)
        {
            return;
        }

        if (_inFlight)
        {
            return;
        }

        _inFlight = true;
        // Request 後に resize → DetachAndReleaseCapture が走っても callback は旧 RT
        // 参照を握ったまま完走する。新 RT 判定は OnReadback 側に委ねる。
        AsyncGPUReadback.Request(_captureRT, 0, TextureFormat.RGBA32, OnReadback);
    }

    /// <summary>
    /// Unity の <c>UnityEngine.Object == null</c> overload は destroy 済み object にも
    /// true を返すので、camera destroy 経路もここで自然に false へ落ちて再 attach に流れる。
    /// </summary>
    private bool IsCaptureUpToDate()
    {
        return _hookedCamera != null
            && _captureRT != null
            && _hookedCamera.pixelWidth == _captureRT.width
            && _hookedCamera.pixelHeight == _captureRT.height;
    }

    /// <summary>
    /// pixel size mismatch があれば teardown して再 attach することで
    /// <c>display.apply</c> による window resize に追従する。
    /// <c>_hookedCamera</c> 自体の入れ替え検出は今回 scope 外
    /// (max-depth camera は engine の lifetime に紐づくため通常起こらない)。
    /// </summary>
    private void EnsureCommandBufferAttached()
    {
        if (IsCaptureUpToDate())
        {
            return;
        }

        int? oldWidth = null;
        int? oldHeight = null;
        if (_captureRT != null)
        {
            oldWidth = _captureRT.width;
            oldHeight = _captureRT.height;
            DetachAndReleaseCapture();
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

        // `just log` で "reattached ... due to resize" を 1 行 grep できるよう
        // 初回 attach と resize 起因 reattach のログを分ける。
        if (oldWidth is int ow && oldHeight is int oh)
        {
            _log.LogInfo(
                $"[ResoniteIO.Renderer] reattached CommandBuffer due to resize: "
                    + $"old={ow}x{oh} new={target.pixelWidth}x{target.pixelHeight} "
                    + $"camera name={target.name} depth={target.depth}"
            );
        }
        else
        {
            _log.LogInfo(
                $"[ResoniteIO.Renderer] attached CommandBuffer to camera "
                    + $"name={target.name} depth={target.depth} size={target.pixelWidth}x{target.pixelHeight}"
            );
        }
    }

    /// <summary>
    /// <see cref="_inFlight"/> をリセットしないことで、進行中の readback は
    /// <see cref="OnReadback"/> 側で <c>_captureRT == null</c> により drop される
    /// (= 旧 RT 内容を新 header で送らない安全策)。
    /// </summary>
    private void DetachAndReleaseCapture()
    {
        if (_hookedCamera != null && _commandBuffer != null)
        {
            var cb = _commandBuffer;
            SafeInvoke(
                "RemoveCommandBuffer",
                () => _hookedCamera.RemoveCommandBuffer(CameraEvent.AfterEverything, cb)
            );
        }

        if (_commandBuffer != null)
        {
            SafeInvoke("CommandBuffer.Release", _commandBuffer.Release);
            _commandBuffer = null;
        }

        if (_captureRT != null)
        {
            SafeInvoke("RenderTexture.Release", _captureRT.Release);
            _captureRT = null;
        }

        _hookedCamera = null;
    }

    /// <summary>
    /// teardown 中の Unity API 例外で残りの release 処理が連鎖中断しないよう
    /// 1 呼び出しを握りつぶす wrapper。
    /// </summary>
    private void SafeInvoke(string label, Action action)
    {
        try
        {
            action();
        }
        catch (Exception ex)
        {
            _log.LogWarning($"[ResoniteIO.Renderer] {label} threw: {ex.Message}");
        }
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

            // Request と callback の間で DetachAndReleaseCapture が走った場合は
            // 旧 RT 内容を新 header で送らないために drop する。
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

        DetachAndReleaseCapture();
    }
}
