using ResoniteIO.Core;
using ResoniteIO.Core.Tests.Common;
using ResoniteIO.V1;
using Xunit;

namespace ResoniteIO.Core.Tests.Connection;

// GrpcHostHarness が RESONITE_IO_SOCKET env var を書き換えるため、これを使う全テストは
// 同じ collection で直列化する。
[Collection("GrpcHostEnv")]
public sealed class ConnectionRoundTripTests
{
    [Fact]
    public async Task Ping_EchoesMessage_AndStampsServerTimestamp()
    {
        await using var harness = await GrpcHostHarness.StartAsync();
        using var channel = harness.CreateChannel();
        var client = new V1.Connection.ConnectionClient(channel);

        var beforeNanos = UnixNanosClock.Now();
        var response = await client.PingAsync(new PingRequest { Message = "hello" });
        var afterNanos = UnixNanosClock.Now();

        Assert.Equal("hello", response.Message);
        Assert.InRange(response.ServerUnixNanos, beforeNanos, afterNanos);
    }

    [Fact]
    public async Task GetModVersion_ReturnsInjectedModVersion()
    {
        await using var harness = await GrpcHostHarness.StartAsync(modVersion: "1.2.3-test");
        using var channel = harness.CreateChannel();
        var client = new V1.Connection.ConnectionClient(channel);

        var response = await client.GetModVersionAsync(new GetModVersionRequest());

        Assert.Equal("1.2.3-test", response.Version);
    }
}
