using Grpc.Core;
using ResoniteIO.Core.Logging;
using ResoniteIO.V1;

namespace ResoniteIO.Core.Session;

/// <summary><c>resonite_io.v1.Session</c> サービスの Core 実装。</summary>
public sealed class SessionService : V1.Session.SessionBase
{
    private readonly ILogSink _log;

    public SessionService(ILogSink log)
    {
        _log = log;
    }

    public override Task<PingResponse> Ping(PingRequest request, ServerCallContext context)
    {
        _log.LogDebug($"Session.Ping received: \"{request.Message}\"");
        var response = new PingResponse
        {
            Message = request.Message,
            ServerUnixNanos = UnixNanosClock.Now(),
        };
        return Task.FromResult(response);
    }
}
