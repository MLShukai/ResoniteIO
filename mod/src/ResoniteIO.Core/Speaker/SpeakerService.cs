using Google.Protobuf;
using Grpc.Core;
using ResoniteIO.Core.Logging;

#pragma warning disable CA1031 // catch (Exception) は Bridge 側の任意例外を gRPC Status に翻訳するために必要

namespace ResoniteIO.Core.Speaker;

/// <summary><c>resonite_io.v1.Speaker</c> サービスの Core 実装。</summary>
/// <remarks>
/// <see cref="ISpeakerBridge"/> は optional DI。null なら <c>Status.Unavailable</c> を返す
/// (Core 単体テストや speaker 非対応 engine 構成を成立させるため)。
/// Bridge 側で <c>FrameId</c> / <c>UnixNanos</c> が stamp 済みのため、Service は
/// proto frame の再採番をしない (Camera と異なる)。
/// </remarks>
public sealed class SpeakerService : V1.Speaker.SpeakerBase
{
    private readonly ISpeakerBridge? _bridge;
    private readonly ILogSink _log;

    public SpeakerService(ILogSink log, ISpeakerBridge? bridge = null)
    {
        _log = log;
        _bridge = bridge;
    }

    /// <summary>
    /// Bridge が yield する <see cref="AudioFrame"/> を proto に詰めて流す server-streaming RPC。
    /// </summary>
    /// <remarks>
    /// 例外翻訳: bridge 未注入 → <c>Unavailable</c>、<see cref="SpeakerNotReadyException"/>
    /// → <c>FailedPrecondition</c> (client は時間を置いて再 stream)、それ以外 → <c>Internal</c>。
    /// </remarks>
    public override async Task StreamAudio(
        V1.SpeakerStreamRequest request,
        IServerStreamWriter<V1.AudioFrame> responseStream,
        ServerCallContext context
    )
    {
        if (_bridge is null)
        {
            _log.LogWarning(
                "Speaker.StreamAudio called but no ISpeakerBridge is registered; "
                    + "returning Unavailable."
            );
            throw new RpcException(
                new Status(StatusCode.Unavailable, "Speaker bridge is not configured.")
            );
        }

        _log.LogDebug("Speaker.StreamAudio start");

        var ct = context.CancellationToken;
        long emitted = 0;

        try
        {
            await foreach (var frame in _bridge.StreamFramesAsync(ct).ConfigureAwait(false))
            {
                var proto = MapToProto(frame);
                try
                {
                    await responseStream.WriteAsync(proto, ct).ConfigureAwait(false);
                    emitted++;
                }
                catch (InvalidOperationException ex)
                {
                    // Client が disconnect すると WriteAsync が "response stream is completed"
                    // 系の InvalidOperationException で抜ける実装がある (Camera と同様)。
                    _log.LogDebug($"Speaker.StreamAudio: write aborted: {ex.Message}");
                    break;
                }
            }
        }
        catch (OperationCanceledException)
        {
            // ct cancel は正常な stream 終了として伝播する (Grpc.AspNetCore が
            // client cancel を Cancelled status に変換する)。
            throw;
        }
        catch (SpeakerNotReadyException ex)
        {
            _log.LogInfo($"Speaker.StreamAudio: bridge not ready: {ex.Message}");
            throw new RpcException(new Status(StatusCode.FailedPrecondition, ex.Message));
        }
        catch (Exception ex)
        {
            _log.LogError($"Speaker.StreamAudio: bridge faulted: {ex}");
            throw new RpcException(
                new Status(StatusCode.Internal, $"Speaker bridge faulted: {ex.Message}")
            );
        }

        _log.LogDebug($"Speaker.StreamAudio end: emitted {emitted} frame(s)");
    }

    private static V1.AudioFrame MapToProto(AudioFrame frame) =>
        new()
        {
            FrameId = (ulong)frame.FrameId,
            UnixNanos = frame.UnixNanos,
            SampleCount = (uint)frame.SampleCount,
            Samples = ByteString.CopyFrom(frame.Samples),
        };
}
