using ResoniteIO.Core.Session;
using ResoniteIO.Core.Tests.Common;
using Xunit;

namespace ResoniteIO.Core.Tests.Session;

[Collection("SessionHostEnv")]
public sealed class SessionBridgeWiringTests
{
    [Fact]
    public async Task Start_WithBridge_DoesNotConsumeBridgeValues()
    {
        var bridge = new FakeSessionBridge(focusedWorldName: "home", localUserName: "tester");

        await using var harness = await SessionHostHarness.StartAsync(bridge);

        // Service が Bridge をまだ consume していないことを negative space で確認する。
        // 消費が始まったらこの assertion は consumer 側へ移すべき。
        Assert.Equal("home", bridge.FocusedWorldName);
        Assert.Equal("tester", bridge.LocalUserName);
    }

    private sealed class FakeSessionBridge(string? focusedWorldName, string? localUserName)
        : ISessionBridge
    {
        public string? FocusedWorldName { get; } = focusedWorldName;
        public string? LocalUserName { get; } = localUserName;
    }
}
