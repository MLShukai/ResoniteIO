using Grpc.Core;
using ResoniteIO.Core.Logging;
using ResoniteIO.Core.Rpc;

namespace ResoniteIO.Core.Info;

/// <summary><c>resonite_io.v1.Info</c> サービスの Core 実装。</summary>
/// <remarks>
/// <see cref="IInfoBridge"/> は optional DI: null なら <c>Unavailable</c> を返し、
/// Core 単体テストや bridge 未注入構成も成立させる (他モダリティと同 pattern)。
/// snapshot は不変値の同期読みなので engine-dispatch 機構は不要。
/// </remarks>
public sealed class InfoService : V1.Info.InfoBase
{
    private readonly IInfoBridge? _bridge;
    private readonly ILogSink _log;

    public InfoService(ILogSink log, IInfoBridge? bridge = null)
    {
        _log = log;
        _bridge = bridge;
    }

    public override Task<V1.ServerInfo> GetServerInfo(
        V1.GetServerInfoRequest request,
        ServerCallContext context
    )
    {
        var bridge = BridgeGuard.Require(_bridge, _log, "Info", "IInfoBridge", "GetServerInfo");
        return Task.FromResult(ToProto(bridge.ReadServerInfo()));
    }

    private static V1.ServerInfo ToProto(ServerInfoSnapshot snapshot) =>
        new()
        {
            ModVersion = snapshot.ModVersion,
            EngineVersion = snapshot.EngineVersion,
            Platform = ToProtoPlatform(snapshot.Platform),
            IsWine = snapshot.IsWine,
            ResonitePid = snapshot.ResonitePid,
            RendererPid = snapshot.RendererPid,
        };

    /// <summary>Core enum → proto enum の明示変換。未知値は <c>Unspecified</c> に落とす。</summary>
    private static V1.ServerPlatform ToProtoPlatform(ServerPlatform platform) =>
        platform switch
        {
            ServerPlatform.Windows => V1.ServerPlatform.Windows,
            ServerPlatform.Osx => V1.ServerPlatform.Osx,
            ServerPlatform.Linux => V1.ServerPlatform.Linux,
            ServerPlatform.Android => V1.ServerPlatform.Android,
            ServerPlatform.Other => V1.ServerPlatform.Other,
            _ => V1.ServerPlatform.Unspecified,
        };
}
