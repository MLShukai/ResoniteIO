using Grpc.Core;
using ResoniteIO.Core.Logging;
using ResoniteIO.V1;

namespace ResoniteIO.Core.Connection;

/// <summary><c>resonite_io.v1.Connection</c> サービスの Core 実装。</summary>
public sealed class ConnectionService : V1.Connection.ConnectionBase
{
    private readonly ILogSink _log;

    public ConnectionService(ILogSink log)
    {
        _log = log;
    }

    public override Task<PingResponse> Ping(PingRequest request, ServerCallContext context)
    {
        _log.LogDebug($"Connection.Ping received: \"{request.Message}\"");
        var response = new PingResponse
        {
            Message = request.Message,
            ServerUnixNanos = UnixNanosClock.Now(),
        };
        return Task.FromResult(response);
    }
}
