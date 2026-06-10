using Grpc.Core;
using ResoniteIO.Core.Info;
using ResoniteIO.Core.Tests.Common;
using Xunit;

namespace ResoniteIO.Core.Tests.Info;

/// <summary>
/// <see cref="Core.Info.InfoService"/> の <c>GetServerInfo</c> RPC を実 Kestrel + UDS gRPC
/// で end-to-end に流す integration-real テスト。(1) Bridge snapshot の 4 field が
/// proto <c>ServerInfo</c> に round-trip すること、(2) Core enum → proto enum の
/// platform mapping、(3) bridge 未注入時の <c>Unavailable</c> を検証する。
/// </summary>
/// <remarks>
/// <see cref="GrpcHostHarness"/> は <c>RESONITE_IO_SOCKET</c> env var を読み書きするため
/// <c>"GrpcHostEnv"</c> collection で直列化する (harness の契約)。
/// </remarks>
[Collection("GrpcHostEnv")]
public sealed class InfoRoundTripTests
{
    /// <summary>自前 ABC <see cref="IInfoBridge"/> の inline fake (testing-strategy 準拠)。</summary>
    private sealed class FakeInfoBridge : IInfoBridge
    {
        public ServerInfoSnapshot Snapshot { get; init; } =
            new(
                ModVersion: "1.2.3-test",
                EngineVersion: "2025.1.1.1",
                Platform: ServerPlatform.Linux,
                IsWine: true
            );

        public ServerInfoSnapshot ReadServerInfo() => Snapshot;
    }

    [Fact]
    public async Task GetServerInfo_RoundTripsAllFourFieldsFromBridgeSnapshot()
    {
        var bridge = new FakeInfoBridge();
        await using var harness = await GrpcHostHarness.StartAsync(infoBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Info.InfoClient(channel);

        var info = await client.GetServerInfoAsync(new V1.GetServerInfoRequest());

        Assert.Equal("1.2.3-test", info.ModVersion);
        Assert.Equal("2025.1.1.1", info.EngineVersion);
        Assert.Equal(V1.ServerPlatform.Linux, info.Platform);
        Assert.True(info.IsWine);
    }

    [Theory]
    [InlineData(ServerPlatform.Unspecified, V1.ServerPlatform.Unspecified)]
    [InlineData(ServerPlatform.Windows, V1.ServerPlatform.Windows)]
    [InlineData(ServerPlatform.Osx, V1.ServerPlatform.Osx)]
    [InlineData(ServerPlatform.Linux, V1.ServerPlatform.Linux)]
    [InlineData(ServerPlatform.Android, V1.ServerPlatform.Android)]
    [InlineData(ServerPlatform.Other, V1.ServerPlatform.Other)]
    public async Task GetServerInfo_MapsEachCorePlatformToMatchingProtoValue(
        ServerPlatform corePlatform,
        V1.ServerPlatform expectedWirePlatform
    )
    {
        var bridge = new FakeInfoBridge
        {
            Snapshot = new ServerInfoSnapshot(
                ModVersion: "1.2.3-test",
                EngineVersion: "2025.1.1.1",
                Platform: corePlatform,
                IsWine: false
            ),
        };
        await using var harness = await GrpcHostHarness.StartAsync(infoBridge: bridge);
        using var channel = harness.CreateChannel();
        var client = new V1.Info.InfoClient(channel);

        var info = await client.GetServerInfoAsync(new V1.GetServerInfoRequest());

        Assert.Equal(expectedWirePlatform, info.Platform);
    }

    [Fact]
    public async Task GetServerInfo_WithoutBridge_ReturnsUnavailable()
    {
        await using var harness = await GrpcHostHarness.StartAsync(infoBridge: null);
        using var channel = harness.CreateChannel();
        var client = new V1.Info.InfoClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.GetServerInfoAsync(new V1.GetServerInfoRequest())
        );
        Assert.Equal(StatusCode.Unavailable, ex.StatusCode);
    }
}
