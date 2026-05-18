using System;
using ResoniteIO.Bridge;
using ResoniteIO.Core.Bridge;
using ResoniteIO.RendererShared;
using Xunit;

namespace ResoniteIO.Tests.Bridge;

/// <summary>
/// <see cref="RendererFrameInterprocessReceiver.TryParseFrame"/> の純粋関数を
/// 検証する。<c>Messenger</c> (shared memory queue) は static state を持ち
/// mock し難いので、Receiver 全体ではなく parse 経路のみを unit test する
/// 戦略 (結合検証は Wave 5 / 実機)。
/// </summary>
public sealed class RendererFrameInterprocessReceiverTests
{
    private static byte[] BuildFrameBytes(uint width, uint height, byte fillByte = 0x7F)
    {
        var pixels = new byte[width * height * 4];
        for (var i = 0; i < pixels.Length; i++)
        {
            pixels[i] = fillByte;
        }
        var header = new FrameHeader(
            payloadLength: (uint)pixels.Length,
            width: width,
            height: height,
            format: FrameHeader.FormatRgba8,
            stride: width * 4u,
            unixNanos: 1_700_000_000_000_000_000UL,
            frameId: 42UL
        );

        var combined = new byte[FrameHeader.SizeInBytes + pixels.Length];
        header.Write(combined);
        Buffer.BlockCopy(pixels, 0, combined, FrameHeader.SizeInBytes, pixels.Length);
        return combined;
    }

    [Fact]
    public void TryParseFrame_returns_CameraFrame_for_valid_payload()
    {
        var data = BuildFrameBytes(width: 16, height: 8);

        var ok = RendererFrameInterprocessReceiver.TryParseFrame(
            data,
            out var frame,
            out var reason
        );

        Assert.True(ok);
        Assert.Null(reason);
        Assert.Equal(16, frame.Width);
        Assert.Equal(8, frame.Height);
        Assert.Equal(16 * 8 * 4, frame.Pixels.Length);
        Assert.Equal(CameraFrameFormat.Rgba8, frame.Format);
        Assert.Equal(1_700_000_000_000_000_000L, frame.UnixNanos);
        Assert.Equal(42L, frame.FrameId);
        Assert.All(frame.Pixels, b => Assert.Equal((byte)0x7F, b));
    }

    [Fact]
    public void TryParseFrame_rejects_null_data()
    {
        var ok = RendererFrameInterprocessReceiver.TryParseFrame(null, out var _, out var reason);
        Assert.False(ok);
        Assert.NotNull(reason);
        Assert.Contains("null", reason);
    }

    [Theory]
    [InlineData(0)]
    [InlineData(1)]
    [InlineData(39)]
    public void TryParseFrame_rejects_buffer_shorter_than_header(int length)
    {
        var data = new byte[length];
        var ok = RendererFrameInterprocessReceiver.TryParseFrame(data, out var _, out var reason);
        Assert.False(ok);
        Assert.NotNull(reason);
        Assert.Contains("too short", reason);
    }

    [Fact]
    public void TryParseFrame_rejects_invalid_magic()
    {
        var data = new byte[FrameHeader.SizeInBytes + 16];
        // すべて 0、magic は 0 のまま (RIOF と一致しない)
        var ok = RendererFrameInterprocessReceiver.TryParseFrame(data, out var _, out var reason);
        Assert.False(ok);
        Assert.NotNull(reason);
        Assert.Contains("invalid header", reason);
    }

    [Fact]
    public void TryParseFrame_rejects_payload_length_mismatch()
    {
        var data = BuildFrameBytes(width: 4, height: 4);
        // header の PayloadLength は正しいが、実 buffer 長を縮めて mismatch を作る
        var truncated = new byte[data.Length - 8];
        Buffer.BlockCopy(data, 0, truncated, 0, truncated.Length);

        var ok = RendererFrameInterprocessReceiver.TryParseFrame(
            truncated,
            out var _,
            out var reason
        );
        Assert.False(ok);
        Assert.NotNull(reason);
        Assert.Contains("payload length mismatch", reason);
    }

    [Fact]
    public void TryParseFrame_rejects_size_mismatch()
    {
        // width * height * 4 != payloadLength を意図的に作る
        var pixels = new byte[100]; // 25 RGBA pixels
        var header = new FrameHeader(
            payloadLength: 100u,
            width: 10u, // 10 * 4 * 4 = 160 ≠ 100
            height: 4u,
            format: FrameHeader.FormatRgba8,
            stride: 40u,
            unixNanos: 0UL,
            frameId: 0UL
        );
        var combined = new byte[FrameHeader.SizeInBytes + pixels.Length];
        header.Write(combined);
        Buffer.BlockCopy(pixels, 0, combined, FrameHeader.SizeInBytes, pixels.Length);

        var ok = RendererFrameInterprocessReceiver.TryParseFrame(
            combined,
            out var _,
            out var reason
        );
        Assert.False(ok);
        Assert.NotNull(reason);
        Assert.Contains("size mismatch", reason);
    }

    [Fact]
    public void TryParseFrame_rejects_unsupported_format()
    {
        // format != FormatRgba8 → reject
        var header = new FrameHeader(
            payloadLength: 16u,
            width: 2u,
            height: 2u,
            format: 99u, // unsupported
            stride: 8u,
            unixNanos: 0UL,
            frameId: 0UL
        );
        var combined = new byte[FrameHeader.SizeInBytes + 16];
        header.Write(combined);

        var ok = RendererFrameInterprocessReceiver.TryParseFrame(
            combined,
            out var _,
            out var reason
        );
        Assert.False(ok);
        Assert.NotNull(reason);
        Assert.Contains("unsupported format", reason);
    }
}
