using ResoniteIO.Core.Camera;

namespace ResoniteIO.Core.Tests.Helpers;

/// <summary>
/// テスト用 <see cref="ICameraBridge"/>。Bridge 側 FrameId は内部カウンタで monotonic
/// に振り、CameraService が proto <c>frame_id</c> を独立に振り直す挙動を検証可能にする。
/// </summary>
internal sealed class FakeCameraBridge : ICameraBridge
{
    private long _bridgeFrameId;

    public bool ThrowNotReady { get; set; }

    /// <summary>各 capture 前に挟む遅延 (fps_limit pacing テスト等で利用)。</summary>
    public int? DelayMs { get; set; }

    public async Task<CameraFrame> CaptureAsync(int width, int height, CancellationToken ct)
    {
        if (ThrowNotReady)
        {
            throw new CameraNotReadyException("FakeCameraBridge: simulated not-ready state.");
        }

        if (DelayMs is { } d && d > 0)
        {
            await Task.Delay(d, ct).ConfigureAwait(false);
        }

        ct.ThrowIfCancellationRequested();

        var pixels = CreateCheckerboard(width, height);
        var unixNanos = (DateTimeOffset.UtcNow.UtcTicks - DateTime.UnixEpoch.Ticks) * 100L;
        var id = Interlocked.Increment(ref _bridgeFrameId);

        return new CameraFrame(
            Pixels: pixels,
            Width: width,
            Height: height,
            UnixNanos: unixNanos,
            FrameId: id,
            Format: CameraFrameFormat.Rgba8
        );
    }

    private static byte[] CreateCheckerboard(int width, int height)
    {
        const int tile = 8;
        var buffer = new byte[width * height * 4];
        for (var y = 0; y < height; y++)
        {
            for (var x = 0; x < width; x++)
            {
                var isWhite = ((x / tile) + (y / tile)) % 2 == 0;
                var i = ((y * width) + x) * 4;
                var v = (byte)(isWhite ? 0xFF : 0x00);
                buffer[i + 0] = v; // R
                buffer[i + 1] = v; // G
                buffer[i + 2] = v; // B
                buffer[i + 3] = 0xFF; // A
            }
        }
        return buffer;
    }
}
