using System;
using System.Buffers.Binary;

namespace ResoniteIO.RendererShared;

/// <summary>
/// engine ↔ Renderer 間で共有メモリ queue (InterprocessLib) を流れる camera frame
/// payload の先頭 40 bytes に乗る little-endian binary header。
/// </summary>
/// <remarks>
/// <para>
/// payload は <c>FrameHeader (40 bytes) + RGBA8 pixel data (PayloadLength bytes)</c>
/// という連結形式。各 frame の bit-exact な解釈を engine / renderer 両側で揃える
/// ため、本 struct を <see cref="ResoniteIO.RendererShared"/> に置き
/// netstandard2.0 で共有する。
/// </para>
/// <para>
/// byte layout (すべて little-endian):
/// </para>
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
    /// <summary>Header 先頭 4 bytes の magic number 'RIOF' (LE)。</summary>
    public const uint Magic = 0x52494F46u;

    /// <summary>Header 自体の固定 byte サイズ。</summary>
    public const int SizeInBytes = 40;

    /// <summary><see cref="Format"/> に格納される RGBA8 のエンコーディング値。</summary>
    public const uint FormatRgba8 = 0u;

    /// <summary>payload に続く pixel data の byte 数 (<c>Stride * Height</c>)。</summary>
    public uint PayloadLength { get; }

    /// <summary>frame の幅 (pixel)。</summary>
    public uint Width { get; }

    /// <summary>frame の高さ (pixel)。</summary>
    public uint Height { get; }

    /// <summary>pixel エンコーディング (0 = RGBA8)。</summary>
    public uint Format { get; }

    /// <summary>1 行あたりの byte 数。RGBA8 + padding 無しなら <c>Width * 4</c>。</summary>
    public uint Stride { get; }

    /// <summary>capture 時の Unix epoch ナノ秒 (engine / Python と clock を揃える)。</summary>
    public ulong UnixNanos { get; }

    /// <summary>renderer 側で monotonic に振る frame シーケンス番号。</summary>
    public ulong FrameId { get; }

    /// <summary>全フィールドを指定して header を構築する。</summary>
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
    /// <paramref name="buffer"/> の先頭から 40 bytes を解釈して header を組み立てる。
    /// </summary>
    /// <param name="buffer">少なくとも <see cref="SizeInBytes"/> bytes の入力。</param>
    /// <returns>解釈された <see cref="FrameHeader"/>。</returns>
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

    /// <summary>
    /// 本 header を <paramref name="buffer"/> の先頭 40 bytes に LE で書き込む。
    /// </summary>
    /// <param name="buffer">少なくとも <see cref="SizeInBytes"/> bytes の出力先。</param>
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

    /// <summary>本 header を 40 bytes の新しい <c>byte[]</c> として返す。</summary>
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
        // netstandard2.0 では System.HashCode が無いので unchecked で手組みする。
        // 衝突耐性は実用十分 (本 struct を hash key にする想定は無く、
        // 主用途は集合操作の正当性確認)。
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

    /// <summary>2 つの header が同値か。</summary>
    public static bool operator ==(FrameHeader left, FrameHeader right) => left.Equals(right);

    /// <summary>2 つの header が異なるか。</summary>
    public static bool operator !=(FrameHeader left, FrameHeader right) => !left.Equals(right);
}
