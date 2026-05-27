using ResoniteIO.Core;
using ResoniteIO.Core.Tests.Common;
using ResoniteIO.V1;
using Xunit;

namespace ResoniteIO.Core.Tests.Session;

// SessionHostHarness が RESONITE_IO_SOCKET env var を書き換えるため、これを使う全テストは
// 同じ collection で直列化する。
[Collection("SessionHostEnv")]
public sealed class SessionRoundTripTests
{
    [Fact]
    public async Task Ping_EchoesMessage_AndStampsServerTimestamp()
    {
        await using var harness = await SessionHostHarness.StartAsync();
        using var channel = harness.CreateChannel();
        var client = new V1.Session.SessionClient(channel);

        var beforeNanos = UnixNanosClock.Now();
        var response = await client.PingAsync(new PingRequest { Message = "hello" });
        var afterNanos = UnixNanosClock.Now();

        Assert.Equal("hello", response.Message);
        Assert.InRange(response.ServerUnixNanos, beforeNanos, afterNanos);
    }
}
