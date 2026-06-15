using Microsoft.AspNetCore.Builder;
using Microsoft.Extensions.DependencyInjection;
using ResoniteIO.Core.Session;

namespace ResoniteIO.Core.Tests.Common;

/// <summary>
/// Session 単体テスト用の最小 Kestrel + UDS gRPC host。
/// </summary>
/// <remarks>
/// <see cref="SessionService"/> だけを載せた host を立てて round-trip 検証を可能にする
/// (<see cref="InventoryServiceHost"/> と同 pattern)。<paramref name="bridge"/> を null で渡すと
/// bridge 未登録の <c>Unavailable</c> 経路も検証できる (Service ctor の default null を使う)。
/// Kestrel 起動 / channel / dispose の共通部分は <see cref="KestrelServiceHost{TService}"/> に集約済み。
/// GrpcHost 統合経路 (複数 Service mount + env var socket 解決) は <see cref="GrpcHostHarness"/> 側。
/// </remarks>
internal sealed class SessionServiceHost : KestrelServiceHost<SessionService>
{
    private SessionServiceHost(WebApplication app, string socketPath)
        : base(app, socketPath) { }

    public static async Task<SessionServiceHost> StartAsync(ISessionBridge? bridge = null)
    {
        var (app, socketPath) = await StartCoreAsync(
                "session",
                services =>
                {
                    if (bridge is not null)
                    {
                        services.AddSingleton(bridge);
                    }
                }
            )
            .ConfigureAwait(false);

        return new SessionServiceHost(app, socketPath);
    }
}
