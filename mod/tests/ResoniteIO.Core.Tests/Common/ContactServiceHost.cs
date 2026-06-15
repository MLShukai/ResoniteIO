using Microsoft.AspNetCore.Builder;
using Microsoft.Extensions.DependencyInjection;
using ResoniteIO.Core.Contact;

namespace ResoniteIO.Core.Tests.Common;

/// <summary>
/// Contact 単体テスト用の最小 Kestrel + UDS gRPC host。
/// </summary>
/// <remarks>
/// <see cref="ContactService"/> だけを載せた host を立てて round-trip 検証を可能にする
/// (<see cref="SessionServiceHost"/> と同 pattern)。<paramref name="bridge"/> を null で渡すと
/// bridge 未登録の <c>Unavailable</c> 経路も検証できる (Service ctor の default null を使う)。
/// Kestrel 起動 / channel / dispose の共通部分は <see cref="KestrelServiceHost{TService}"/> に集約済み。
/// </remarks>
internal sealed class ContactServiceHost : KestrelServiceHost<ContactService>
{
    private ContactServiceHost(WebApplication app, string socketPath)
        : base(app, socketPath) { }

    public static async Task<ContactServiceHost> StartAsync(IContactBridge? bridge = null)
    {
        var (app, socketPath) = await StartCoreAsync(
                "contact",
                services =>
                {
                    if (bridge is not null)
                    {
                        services.AddSingleton(bridge);
                    }
                }
            )
            .ConfigureAwait(false);

        return new ContactServiceHost(app, socketPath);
    }
}
