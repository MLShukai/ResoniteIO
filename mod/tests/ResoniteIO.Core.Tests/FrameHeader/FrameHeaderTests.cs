using System;
using ResoniteIO.RendererShared;
using Xunit;

namespace ResoniteIO.Core.Tests.FrameHeader;

/// <summary>
/// <see cref="ResoniteIO.RendererShared.FrameHeader"/> の binary round-trip と
/// validation を検証する。
/// </summary>
public sealed class FrameHeaderTests
{
    /// <summary>SizeInBytes は 40 で固定。レイアウト変更検知用 sanity。</summary>
    [Fact]
    public void SizeInBytes_is_40()
    {
        Assert.Equal(40, RendererShared.FrameHeader.SizeInBytes);
    }

    /// <summary>
    /// 様々な値で <c>ToBytes → Read</c> しても全フィールドが一致する。
    /// </summary>
    [Theory]
    [InlineData(0u, 0u, 0u, 0u, 0u, 0ul, 0ul)]
    [InlineData(2911272u, 1118u, 651u, 0u, 4472u, 1_700_000_000_000_000_000ul, 1ul)]
    [InlineData(
        uint.MaxValue,
        uint.MaxValue,
        uint.MaxValue,
        uint.MaxValue,
        uint.MaxValue,
        ulong.MaxValue,
        ulong.MaxValue
    )]
    public void Read_then_Write_round_trip(
        uint payloadLength,
        uint width,
        uint height,
        uint format,
        uint stride,
        ulong unixNanos,
        ulong frameId
    )
    {
        var original = new RendererShared.FrameHeader(
            payloadLength,
            width,
            height,
            format,
            stride,
            unixNanos,
            frameId
        );

        var bytes = original.ToBytes();
        Assert.Equal(RendererShared.FrameHeader.SizeInBytes, bytes.Length);

        var decoded = RendererShared.FrameHeader.Read(bytes);

        Assert.Equal(original, decoded);
        Assert.Equal(payloadLength, decoded.PayloadLength);
        Assert.Equal(width, decoded.Width);
        Assert.Equal(height, decoded.Height);
        Assert.Equal(format, decoded.Format);
        Assert.Equal(stride, decoded.Stride);
        Assert.Equal(unixNanos, decoded.UnixNanos);
        Assert.Equal(frameId, decoded.FrameId);
    }

    /// <summary>magic は先頭 4 bytes に LE で書き込まれる ('RIOF')。</summary>
    [Fact]
    public void Write_emits_RIOF_magic_in_little_endian()
    {
        var header = new RendererShared.FrameHeader(0u, 0u, 0u, 0u, 0u, 0ul, 0ul);
        var bytes = header.ToBytes();

        // 'R' (0x52), 'I' (0x49), 'O' (0x4F), 'F' (0x46) を LE で読むと
        // 先頭 byte が 'F' = 0x46 になる (LE は LSB first)。
        Assert.Equal((byte)0x46, bytes[0]); // 'F'
        Assert.Equal((byte)0x4F, bytes[1]); // 'O'
        Assert.Equal((byte)0x49, bytes[2]); // 'I'
        Assert.Equal((byte)0x52, bytes[3]); // 'R'
    }

    /// <summary>magic が違うと Read は ArgumentException を投げる。</summary>
    [Fact]
    public void Read_rejects_invalid_magic()
    {
        var bytes = new byte[RendererShared.FrameHeader.SizeInBytes];
        // すべて 0 のまま (magic も 0)
        Assert.Throws<ArgumentException>(() => RendererShared.FrameHeader.Read(bytes));
    }

    /// <summary>buffer が 40 bytes 未満なら Read は ArgumentException。</summary>
    [Theory]
    [InlineData(0)]
    [InlineData(1)]
    [InlineData(39)]
    public void Read_rejects_short_buffer(int length)
    {
        var bytes = new byte[length];
        Assert.Throws<ArgumentException>(() => RendererShared.FrameHeader.Read(bytes));
    }

    /// <summary>buffer が 40 bytes 未満なら Write は ArgumentException。</summary>
    [Theory]
    [InlineData(0)]
    [InlineData(1)]
    [InlineData(39)]
    public void Write_rejects_short_buffer(int length)
    {
        var header = new RendererShared.FrameHeader(0u, 0u, 0u, 0u, 0u, 0ul, 0ul);
        var bytes = new byte[length];
        Assert.Throws<ArgumentException>(() => header.Write(bytes));
    }

    /// <summary>
    /// 40 bytes 以上の buffer に Write した場合、ちょうど 40 bytes だけが書かれる
    /// (それ以降はテスト側 sentinel が保たれる)。
    /// </summary>
    [Fact]
    public void Write_only_touches_first_40_bytes()
    {
        var header = new RendererShared.FrameHeader(1u, 2u, 3u, 4u, 5u, 6ul, 7ul);
        var buffer = new byte[64];
        for (var i = 0; i < buffer.Length; i++)
        {
            buffer[i] = 0xAB;
        }

        header.Write(buffer);

        for (var i = RendererShared.FrameHeader.SizeInBytes; i < buffer.Length; i++)
        {
            Assert.Equal((byte)0xAB, buffer[i]);
        }
    }

    /// <summary>同値判定は全フィールドベース (struct の equality 契約を docs どおりに維持)。</summary>
    [Fact]
    public void Equality_compares_all_fields()
    {
        var a = new RendererShared.FrameHeader(1u, 2u, 3u, 4u, 5u, 6ul, 7ul);
        var b = new RendererShared.FrameHeader(1u, 2u, 3u, 4u, 5u, 6ul, 7ul);
        var c = new RendererShared.FrameHeader(1u, 2u, 3u, 4u, 5u, 6ul, 999ul);

        Assert.True(a == b);
        Assert.False(a == c);
        Assert.Equal(a.GetHashCode(), b.GetHashCode());
    }
}
