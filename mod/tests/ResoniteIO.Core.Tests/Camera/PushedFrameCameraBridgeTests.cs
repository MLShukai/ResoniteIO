using ResoniteIO.Core.Camera;
using Xunit;

namespace ResoniteIO.Core.Tests.Camera;

/// <summary>
/// <see cref="PushedFrameCameraBridge"/> の latest-wins / 待機 / キャンセル /
/// dispose 後の挙動を検証する。
/// </summary>
public sealed class PushedFrameCameraBridgeTests
{
    private static CameraFrame MakeFrame(long frameId, int width = 4, int height = 4) =>
        new(
            Pixels: new byte[width * height * 4],
            Width: width,
            Height: height,
            UnixNanos: 1_700_000_000_000_000_000L + frameId,
            FrameId: frameId,
            Format: CameraFrameFormat.Rgba8
        );

    [Fact]
    public async Task Capture_returns_frame_that_was_pushed()
    {
        using var bridge = new PushedFrameCameraBridge();
        var expected = MakeFrame(frameId: 1);

        Assert.True(bridge.Push(expected));

        var actual = await bridge.CaptureAsync(0, 0, CancellationToken.None);

        Assert.Equal(expected.FrameId, actual.FrameId);
        Assert.Equal(expected.Width, actual.Width);
        Assert.Equal(expected.Height, actual.Height);
        Assert.Equal(expected.UnixNanos, actual.UnixNanos);
        Assert.Equal(expected.Format, actual.Format);
    }

    [Fact]
    public async Task Push_twice_then_capture_returns_latest_frame_only()
    {
        using var bridge = new PushedFrameCameraBridge();
        var first = MakeFrame(frameId: 1);
        var second = MakeFrame(frameId: 2);

        Assert.True(bridge.Push(first));
        Assert.True(bridge.Push(second));

        var captured = await bridge.CaptureAsync(0, 0, CancellationToken.None);
        Assert.Equal(2L, captured.FrameId);

        // 続けて読もうとすると frame が無いのでブロックする。
        // 短いタイムアウトでキャンセルし、空であることを確認する。
        using var cts = new CancellationTokenSource(TimeSpan.FromMilliseconds(100));
        await Assert.ThrowsAsync<OperationCanceledException>(async () =>
            await bridge.CaptureAsync(0, 0, cts.Token)
        );
    }

    [Fact]
    public async Task Capture_blocks_until_push_arrives()
    {
        using var bridge = new PushedFrameCameraBridge();
        using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(5));

        var captureTask = bridge.CaptureAsync(0, 0, cts.Token);
        Assert.False(captureTask.IsCompleted);

        // 50ms 待ってから push する。
        await Task.Delay(50, cts.Token);
        Assert.True(bridge.Push(MakeFrame(frameId: 42)));

        var captured = await captureTask;
        Assert.Equal(42L, captured.FrameId);
    }

    [Fact]
    public async Task Capture_propagates_cancellation()
    {
        using var bridge = new PushedFrameCameraBridge();
        using var cts = new CancellationTokenSource();

        var captureTask = bridge.CaptureAsync(0, 0, cts.Token);
        cts.Cancel();

        await Assert.ThrowsAsync<OperationCanceledException>(async () => await captureTask);
    }

    [Fact]
    public async Task Capture_after_dispose_throws_CameraNotReady()
    {
        var bridge = new PushedFrameCameraBridge();
        bridge.Dispose();

        await Assert.ThrowsAsync<CameraNotReadyException>(async () =>
            await bridge.CaptureAsync(0, 0, CancellationToken.None)
        );
    }

    [Fact]
    public void Push_after_dispose_returns_false_and_does_not_throw()
    {
        var bridge = new PushedFrameCameraBridge();
        bridge.Dispose();

        Assert.False(bridge.Push(MakeFrame(frameId: 1)));
    }

    [Fact]
    public void Dispose_is_idempotent()
    {
        var bridge = new PushedFrameCameraBridge();
        bridge.Dispose();
        // 2 回 Dispose を呼んでも例外が出ない。
        bridge.Dispose();
    }

    [Fact]
    public async Task Pending_capture_throws_CameraNotReady_when_disposed_concurrently()
    {
        var bridge = new PushedFrameCameraBridge();
        using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(5));

        var captureTask = bridge.CaptureAsync(0, 0, cts.Token);
        Assert.False(captureTask.IsCompleted);

        bridge.Dispose();

        await Assert.ThrowsAsync<CameraNotReadyException>(async () => await captureTask);
    }
}
