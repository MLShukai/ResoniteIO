using Microsoft.AspNetCore.Builder;
using Microsoft.Extensions.DependencyInjection;
using ResoniteIO.Core.Display;

namespace ResoniteIO.Core.Tests.Common;

/// <summary>
/// Display 単体テスト用の最小 Kestrel + UDS gRPC host。
/// </summary>
/// <remarks>
/// <para>
/// Wave 2 では <c>GrpcHost.cs</c> に <see cref="DisplayService"/> を mount しない
/// (Plan 同期点制約)。本 helper は test 専用に <see cref="DisplayService"/> だけを
/// 載せた host を立てて round-trip 検証を可能にする。Wave 4 / C8 で
/// <c>GrpcHost</c> に mount された後は本 helper は不要になるが、
/// Display 単体の挙動を <see cref="Camera.CameraService"/> 等から隔離する利点もある
/// ので残しておく価値はある (Wave 4+ の整理判断)。
/// </para>
/// <para>
/// Kestrel 起動 / channel / dispose の共通部分は <see cref="KestrelServiceHost{TService}"/>
/// に集約済み。本クラスは <see cref="DisplayService"/> 固有の bridge DI だけを担う。
/// </para>
/// </remarks>
internal sealed class DisplayServiceHost : KestrelServiceHost<DisplayService>
{
    private DisplayServiceHost(WebApplication app, string socketPath)
        : base(app, socketPath) { }

    public static async Task<DisplayServiceHost> StartAsync(IDisplayBridge bridge)
    {
        ArgumentNullException.ThrowIfNull(bridge);

        var (app, socketPath) = await StartCoreAsync(
                "display",
                services => services.AddSingleton(bridge)
            )
            .ConfigureAwait(false);

        return new DisplayServiceHost(app, socketPath);
    }
}
