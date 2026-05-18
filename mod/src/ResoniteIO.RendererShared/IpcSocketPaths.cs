namespace ResoniteIO.RendererShared;

/// <summary>
/// engine ↔ Renderer 間の共有メモリ queue (InterprocessLib) の接続パラメータ定数。
/// </summary>
/// <remarks>
/// engine 側 (authority) と Renderer 側 (non-authority) の双方が完全に同じ値で
/// <c>Messenger</c> を構築する必要がある。値の drift は別 queue に向かう silent
/// failure (送ったのに受信できない) を生むため、両側 csproj が本 class を
/// ProjectReference する。
/// </remarks>
public static class IpcSocketPaths
{
    public const string OwnerId = "net.mlshukai.resonite-io.camera";

    public const string QueueName = "resonite-io-camera-frames";

    public const string FrameMessageId = "frame";

    /// <summary>
    /// 共有メモリ queue の容量 (bytes)。InterprocessLib default の 1 MiB では
    /// RGBA8 frame (1118×651 ≒ 2.9 MiB) が乗らないため 32 MiB に拡張する。
    /// </summary>
    public const long QueueCapacityBytes = 32L * 1024L * 1024L;
}
