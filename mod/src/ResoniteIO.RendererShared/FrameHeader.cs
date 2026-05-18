using System;
using System.Buffers.Binary;

namespace ResoniteIO.RendererShared;

/// <summary>
/// engine ↔ Renderer 間で共有メモリ queue を流れる camera frame payload の
/// 先頭 40 bytes に乗る little-endian binary header。
/// </summary>
/// <remarks>
/// byte layout (LE、本表は engine / renderer 両側の bit-exact 契約):
/// <code>
/// Offset  Size  Field
/// 0       4     Magic        ('RIOF' = 0x52494F46 LE)
/// 4       4     PayloadLength (uint32, pixel bytes 数 = Stride * Height)
/// 8       4     Width        (uint32)
/// 12      4     Height       (uint32)
/// 16      4     Format       (uint32, 0=RGBA8)
/// 20      4     Stride       (uint32, 1 行あたりの bytes)
/// 24      8     UnixNanos    (uint64, capture 時の Unix epoch ナノ秒)
/// 32      8     FrameId      (uint64, renderer 側で monotonic に増える)
/// 40      total
/// </code>
/// </remarks>
public readonly struct FrameHeader : IEquatable<FrameHeader>
{
    public const uint Magic = 0x52494F46u;

    public const int SizeInBytes = 40;

    public const uint FormatRgba8 = 0u;

    public uint PayloadLength { get; }

    public uint Width { get; }

    public uint Height { get; }

    public uint Format { get; }

    public uint Stride { get; }

    public ulong UnixNanos { get; }

    public ulong FrameId { get; }

    public FrameHeader(
        uint payloadLength,
        uint width,
        uint height,
        uint format,
        uint stride,
        ulong unixNanos,
        ulong frameId
    )
    {
        PayloadLength = payloadLength;
        Width = width;
        Height = height;
        Format = format;
        Stride = stride;
        UnixNanos = unixNanos;
        FrameId = frameId;
    }

    /// <summary>
    /// <paramref name="buffer"/> の先頭 40 bytes を解釈して header を組み立てる。
    /// </summary>
    /// <exception cref="ArgumentException">
    /// buffer が短い、または magic が <see cref="Magic"/> と一致しない場合。
    /// </exception>
    public static FrameHeader Read(ReadOnlySpan<byte> buffer)
    {
        if (buffer.Length < SizeInBytes)
        {
            throw new ArgumentException(
                $"buffer must be at least {SizeInBytes} bytes (got {buffer.Length}).",
                nameof(buffer)
            );
        }

        var magic = BinaryPrimitives.ReadUInt32LittleEndian(buffer);
        if (magic != Magic)
        {
            throw new ArgumentException(
                $"invalid magic 0x{magic:X8} (expected 0x{Magic:X8}).",
                nameof(buffer)
            );
        }

        return new FrameHeader(
            payloadLength: BinaryPrimitives.ReadUInt32LittleEndian(buffer.Slice(4, 4)),
            width: BinaryPrimitives.ReadUInt32LittleEndian(buffer.Slice(8, 4)),
            height: BinaryPrimitives.ReadUInt32LittleEndian(buffer.Slice(12, 4)),
            format: BinaryPrimitives.ReadUInt32LittleEndian(buffer.Slice(16, 4)),
            stride: BinaryPrimitives.ReadUInt32LittleEndian(buffer.Slice(20, 4)),
            unixNanos: BinaryPrimitives.ReadUInt64LittleEndian(buffer.Slice(24, 8)),
            frameId: BinaryPrimitives.ReadUInt64LittleEndian(buffer.Slice(32, 8))
        );
    }

    /// <summary>本 header を <paramref name="buffer"/> の先頭 40 bytes に LE で書き込む。</summary>
    /// <exception cref="ArgumentException">buffer が短い場合。</exception>
    public void Write(Span<byte> buffer)
    {
        if (buffer.Length < SizeInBytes)
        {
            throw new ArgumentException(
                $"buffer must be at least {SizeInBytes} bytes (got {buffer.Length}).",
                nameof(buffer)
            );
        }

        BinaryPrimitives.WriteUInt32LittleEndian(buffer, Magic);
        BinaryPrimitives.WriteUInt32LittleEndian(buffer.Slice(4, 4), PayloadLength);
        BinaryPrimitives.WriteUInt32LittleEndian(buffer.Slice(8, 4), Width);
        BinaryPrimitives.WriteUInt32LittleEndian(buffer.Slice(12, 4), Height);
        BinaryPrimitives.WriteUInt32LittleEndian(buffer.Slice(16, 4), Format);
        BinaryPrimitives.WriteUInt32LittleEndian(buffer.Slice(20, 4), Stride);
        BinaryPrimitives.WriteUInt64LittleEndian(buffer.Slice(24, 8), UnixNanos);
        BinaryPrimitives.WriteUInt64LittleEndian(buffer.Slice(32, 8), FrameId);
    }

    public byte[] ToBytes()
    {
        var bytes = new byte[SizeInBytes];
        Write(bytes);
        return bytes;
    }

    /// <inheritdoc/>
    public bool Equals(FrameHeader other) =>
        PayloadLength == other.PayloadLength
        && Width == other.Width
        && Height == other.Height
        && Format == other.Format
        && Stride == other.Stride
        && UnixNanos == other.UnixNanos
        && FrameId == other.FrameId;

    /// <inheritdoc/>
    public override bool Equals(object? obj) => obj is FrameHeader other && Equals(other);

    /// <inheritdoc/>
    public override int GetHashCode()
    {
        // netstandard2.0 には System.HashCode が無いので手組み。
        unchecked
        {
            var hash = 17;
            hash = (hash * 31) ^ (int)PayloadLength;
            hash = (hash * 31) ^ (int)Width;
            hash = (hash * 31) ^ (int)Height;
            hash = (hash * 31) ^ (int)Format;
            hash = (hash * 31) ^ (int)Stride;
            hash = (hash * 31) ^ UnixNanos.GetHashCode();
            hash = (hash * 31) ^ FrameId.GetHashCode();
            return hash;
        }
    }

    public static bool operator ==(FrameHeader left, FrameHeader right) => left.Equals(right);

    public static bool operator !=(FrameHeader left, FrameHeader right) => !left.Equals(right);
}
