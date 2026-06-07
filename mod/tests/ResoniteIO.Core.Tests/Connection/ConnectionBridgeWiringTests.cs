using ResoniteIO.Core.Connection;
using ResoniteIO.Core.Tests.Common;
using Xunit;

namespace ResoniteIO.Core.Tests.Connection;

[Collection("GrpcHostEnv")]
public sealed class ConnectionBridgeWiringTests
{
    [Fact]
    public async Task Start_WithBridge_DoesNotConsumeBridgeValues()
    {
        var bridge = new FakeConnectionBridge(focusedWorldName: "home", localUserName: "tester");

        await using var harness = await GrpcHostHarness.StartAsync(bridge);

        // Service が Bridge をまだ consume していないことを negative space で確認する。
        // 消費が始まったらこの assertion は consumer 側へ移すべき。
        Assert.Equal("home", bridge.FocusedWorldName);
        Assert.Equal("tester", bridge.LocalUserName);
    }

    private sealed class FakeConnectionBridge(string? focusedWorldName, string? localUserName)
        : IConnectionBridge
    {
        public string? FocusedWorldName { get; } = focusedWorldName;
        public string? LocalUserName { get; } = localUserName;
    }
}
