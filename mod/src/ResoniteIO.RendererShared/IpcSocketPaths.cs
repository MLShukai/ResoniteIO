namespace ResoniteIO.RendererShared;

/// <summary>
/// engine ↔ Renderer 間の共有メモリ queue (InterprocessLib) の接続パラメータ定数。
/// </summary>
/// <remarks>
/// <para>
/// engine 側 (authority、先に起動する) と Renderer 側 (non-authority、attach する)
/// の双方が **完全に同じ値** で <c>Messenger</c> を構築する必要がある。値の
/// drift は両プロセスが別 queue に向かう原因となり、症状としては Renderer 側
/// が send しても engine 側で frame を受け取れない (silent failure)。
/// </para>
/// <para>
/// 本クラスはその同一性を保証するため、両側 csproj が
/// <c>ResoniteIO.RendererShared</c> を ProjectReference して同じ const を参照する
/// 設計とする。
/// </para>
/// </remarks>
public static class IpcSocketPaths
{
    /// <summary>
    /// InterprocessLib <c>Messenger</c> の owner id。プロセス間で queue を共有する
    /// ための namespace に相当する。
    /// </summary>
    public const string OwnerId = "net.mlshukai.resonite-io.camera";

    /// <summary>共有メモリ queue 名 (1 つの owner id 配下で複数 queue を持てる)。</summary>
    public const string QueueName = "resonite-io-camera-frames";

    /// <summary>
    /// queue に流れる camera frame メッセージの id。
    /// engine 側 <c>ReceiveValueArray&lt;byte&gt;</c> と Renderer 側
    /// <c>SendValueArray&lt;byte&gt;</c> は同じ message id を使う。
    /// </summary>
    public const string FrameMessageId = "frame";

    /// <summary>
    /// 共有メモリ queue の容量 (bytes)。InterprocessLib default の 1 MiB では
    /// RGBA8 frame (1118×651 ≒ 2.9 MiB) が乗らないため 32 MiB に拡張する。
    /// </summary>
    public const long QueueCapacityBytes = 32L * 1024L * 1024L;
}
