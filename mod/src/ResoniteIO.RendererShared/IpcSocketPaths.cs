using System;

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

    /// <summary><see cref="QueueName"/> を上書きする環境変数名。</summary>
    /// <remarks>
    /// 多重起動時に各インスタンスの queue を分離するための逃げ道。token は exec 前に
    /// env へ載せる必要がある: engine が runtime に <c>Environment.SetEnvironmentVariable</c>
    /// で set しても、その値は別プロセスとして起動する renderer に届かず、engine/renderer
    /// が別 queue を掴んで client が frame 待ちでハングする。
    /// <list type="bullet">
    ///   <item><c>resoio launch</c> 経由: Python launcher が起動前に instance 固有 token を
    ///   注入し、engine と renderer (Wine 子プロセス) が同じ env を継承して queue を分離する。</item>
    ///   <item>Gale / Steam 直接起動: 何も set されず、engine/renderer 双方が固定名
    ///   (<see cref="_defaultQueueName"/>) に fallback して一致する (単一インスタンス)。</item>
    /// </list>
    /// <c>GrpcHost.ResolveSocketPath</c> と同じ「env override → 既定値」パターン。
    /// </remarks>
    public const string QueueNameEnvVar = "RESONITE_IO_CAMERA_QUEUE";

    private const string _defaultQueueName = "resonite-io-camera-frames";

    /// <summary>共有メモリ queue の名前。<see cref="QueueNameEnvVar"/> で上書き可能。</summary>
    public static string QueueName =>
        Environment.GetEnvironmentVariable(QueueNameEnvVar) is { Length: > 0 } overridden
            ? overridden
            : _defaultQueueName;

    public const string FrameMessageId = "frame";

    /// <summary>
    /// 共有メモリ queue の容量 (bytes)。InterprocessLib default の 1 MiB では
    /// RGBA8 frame (1118×651 ≒ 2.9 MiB) が乗らないため 32 MiB に拡張する。
    /// </summary>
    public const long QueueCapacityBytes = 32L * 1024L * 1024L;
}
