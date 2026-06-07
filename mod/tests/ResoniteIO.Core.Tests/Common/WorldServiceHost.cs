using Microsoft.AspNetCore.Builder;
using Microsoft.Extensions.DependencyInjection;
using ResoniteIO.Core.World;

namespace ResoniteIO.Core.Tests.Common;

/// <summary>
/// World 単体テスト用の最小 Kestrel + UDS gRPC host。
/// </summary>
/// <remarks>
/// <para>
/// Step 6 の並行作業時点で <c>GrpcHost.cs</c> への World mount は別エージェントが
/// 進めている。本 helper は test 専用に <see cref="WorldService"/> だけを載せた host を
/// 立て、GrpcHost 統合と独立に round-trip を検証する (<see cref="DisplayServiceHost"/>
/// と同じ隔離戦略)。
/// </para>
/// <para>
/// bridge を渡さない (null) 場合も <see cref="WorldService"/> は mount するが
/// bridge 未注入になるため、各 RPC は Service 契約に従い <c>Unavailable</c> を返す。
/// Kestrel 起動 / channel / dispose の共通部分は
/// <see cref="KestrelServiceHost{TService}"/> に集約済み。
/// </para>
/// </remarks>
internal sealed class WorldServiceHost : KestrelServiceHost<WorldService>
{
    private WorldServiceHost(WebApplication app, string socketPath)
        : base(app, socketPath) { }

    public static async Task<WorldServiceHost> StartAsync(IWorldBridge? bridge = null)
    {
        var (app, socketPath) = await StartCoreAsync(
                "world",
                services =>
                {
                    if (bridge is not null)
                    {
                        services.AddSingleton(bridge);
                    }
                }
            )
            .ConfigureAwait(false);

        return new WorldServiceHost(app, socketPath);
    }
}
