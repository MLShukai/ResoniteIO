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
/// <para>
/// 毎 tick で camera の <c>pixelWidth/pixelHeight</c> と cache 済み RT サイズの
/// 一致を確認して、ズレていれば teardown → 再 attach する。<c>display.apply</c>
/// で window が resize されても cached RT への <c>Blit</c> は新サイズに resample
/// するだけで RT 自身は古いままなので、<see cref="FrameHeader"/> の WxH が古い値
/// で固定されてしまう (= e2e で frame dimensions が apply に追従しない)。
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
    /// 毎 Update tick で呼ぶ。pending な readback があれば drop-on-busy で skip。
    /// resize-on-mismatch の検出もここからの <see cref="EnsureCommandBufferAttached"/>
    /// 経由で 1 tick に 1 回走る。
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
            // attach 対象 camera が未生成 (engine 起動直後など)。次 tick で再試行。
            return;
        }

        if (_inFlight)
        {
            return;
        }

        _inFlight = true;
        // Request 後に resize → DetachAndReleaseCapture が走っても、callback は
        // 旧 RT への参照を握ったまま完走する (旧 RT は GC まで生存)。新 RT が
        // 既に attach 済みかどうかの判定は OnReadback 側に委ねる。
        AsyncGPUReadback.Request(_captureRT, 0, TextureFormat.RGBA32, OnReadback);
    }

    /// <summary>
    /// 「同じ camera に対して同じ pixel size」で attach が生きているかを判定する。
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
    /// max depth + 直描画 (<c>targetTexture == null</c>) の Camera に
    /// <see cref="CameraEvent.AfterEverything"/> で CommandBuffer を attach する。
    /// 既に attach 済みでも camera の pixel size が変わっていれば teardown して再 attach
    /// (= <c>display.apply</c> による window resize 追従)。
    /// </summary>
    private void EnsureCommandBufferAttached()
    {
        if (IsCaptureUpToDate())
        {
            return;
        }

        // 旧サイズは resize log の "old=WxH new=WxH" 用に teardown 前に拾う
        // (teardown 後は _captureRT == null になって読めない)。
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

        // 初回 attach と resize 起因 reattach は別行にする。`just log` で
        // "reattached ... due to resize: old=...x... new=...x..." を 1 行で
        // grep できるようにしておくと display.apply の追従ログを追いやすい。
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
    /// CommandBuffer / RenderTexture を camera から外して release する。resize
    /// 検出時の teardown と <see cref="Dispose"/> から呼ぶ。
    /// <see cref="_inFlight"/> はリセットせず、進行中の <see cref="AsyncGPUReadback"/>
    /// 結果は <see cref="OnReadback"/> 側で <c>_captureRT == null</c> により drop
    /// される (= 旧 RT の中身を新 header で送らない安全策)。
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
    /// teardown 中の Unity API 例外で残りの release 処理が連鎖中断しないよう、
    /// 1 呼び出しを LogWarning で握りつぶす wrapper。<paramref name="label"/> は
    /// ログ上の操作識別子 (e.g. <c>"RenderTexture.Release"</c>)。
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

            // Request と callback の間で DetachAndReleaseCapture が走った直後は
            // _captureRT == null なので drop して資源を吐かない。次 tick の
            // 再 attach 後に来る readback で送信が再開する。
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
