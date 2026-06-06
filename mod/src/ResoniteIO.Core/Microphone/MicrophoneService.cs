using System.Runtime.InteropServices;
using Grpc.Core;
using ResoniteIO.Core.Logging;
using ResoniteIO.Core.Rpc;

#pragma warning disable CA1031 // catch (Exception) は Bridge 例外を NotifyDisconnect / RpcException に翻訳するため必要

namespace ResoniteIO.Core.Microphone;

/// <summary><c>resonite_io.v1.Microphone</c> サービスの Core 実装。</summary>
/// <remarks>
/// <para>
/// <see cref="IMicrophoneBridge"/> は optional DI: null なら <c>Unavailable</c>
/// を返す (Core 単体テスト + microphone 非対応 engine 構成を成立させる)。
/// </para>
/// <para>
/// 例外翻訳: bridge 未注入 → <c>Unavailable</c>、
/// <see cref="MicrophoneNotReadyException"/> → <c>FailedPrecondition</c>、
/// client cancel / UDS 切断 → <c>NotifyDisconnect(Cancelled)</c> + 再 throw
/// (Grpc.AspNetCore が <c>Cancelled</c> に変換)、その他 →
/// <c>NotifyDisconnect(Errored)</c> + <c>Internal</c>。
/// </para>
/// <para>
/// proto <c>bytes samples</c> → <c>float[]</c> は defensive copy。
/// proto の <c>sample_count</c> は信用せず実 bytes 長から再計算する
/// (client 側 stamp のミスを Bridge に伝播させない)。
/// </para>
/// </remarks>
public sealed class MicrophoneService : V1.Microphone.MicrophoneBase
{
    private readonly IMicrophoneBridge? _bridge;
    private readonly ILogSink _log;

    public MicrophoneService(ILogSink log, IMicrophoneBridge? bridge = null)
    {
        _log = log;
        _bridge = bridge;
    }

    public override async Task<V1.MicrophoneStreamSummary> StreamAudio(
        IAsyncStreamReader<V1.MicrophoneAudioFrame> requestStream,
        ServerCallContext context
    )
    {
        var bridge = BridgeGuard.Require(
            _bridge,
            _log,
            "Microphone",
            "IMicrophoneBridge",
            "StreamAudio"
        );

        var ct = context.CancellationToken;
        long receivedFrames = 0;
        long receivedSamples = 0;

        // Cancel 経路は Grpc.AspNetCore + Kestrel UDS で OperationCanceledException
        // / IOException / 別系例外+ct のどれで表面化するか実装依存なため、
        // when 句で 1 つの Cancelled bucket に集約する (詳細:
        // feedback_grpc_client_cancel_exception_surface.md)。
        try
        {
            while (await requestStream.MoveNext(ct).ConfigureAwait(false))
            {
                var frame = MapFromProto(requestStream.Current);
                bridge.SubmitFrame(frame);
                receivedFrames++;
                receivedSamples += frame.SampleCount;
            }
        }
        catch (Exception ex)
            when (ex is OperationCanceledException
                || ex is IOException
                || ct.IsCancellationRequested
            )
        {
            _log.LogDebug(
                $"Microphone.StreamAudio cancelled after {receivedFrames} frame(s) "
                    + $"({ex.GetType().Name}): {ex.Message}"
            );
            bridge.NotifyDisconnect(MicrophoneDisconnectReason.Cancelled);
            throw;
        }
        catch (MicrophoneNotReadyException ex)
        {
            _log.LogInfo($"Microphone.StreamAudio: bridge not ready: {ex.Message}");
            bridge.NotifyDisconnect(MicrophoneDisconnectReason.Errored);
            throw new RpcException(new Status(StatusCode.FailedPrecondition, ex.Message));
        }
        catch (Exception ex)
        {
            _log.LogError($"Microphone.StreamAudio faulted after {receivedFrames} frame(s): {ex}");
            bridge.NotifyDisconnect(MicrophoneDisconnectReason.Errored);
            throw new RpcException(
                new Status(StatusCode.Internal, $"Microphone stream faulted: {ex.Message}")
            );
        }

        // MoveNext returned false = client が CompleteAsync で graceful close。
        bridge.NotifyDisconnect(MicrophoneDisconnectReason.Graceful);

        var unixNanos = UnixNanosClock.Now();
        _log.LogDebug(
            $"Microphone.StreamAudio end: received {receivedFrames} frame(s), "
                + $"{receivedSamples} sample(s)"
        );

        return new V1.MicrophoneStreamSummary
        {
            ReceivedFrames = receivedFrames,
            ReceivedSamples = receivedSamples,
            // 本層では drop は発生しない (Bridge 側 ring buffer overflow が drop の発生源)。
            DroppedFrames = 0L,
            UnixNanos = unixNanos,
        };
    }

    private static MicrophoneFrame MapFromProto(V1.MicrophoneAudioFrame proto)
    {
        var bytes = proto.Samples.Span;
        var floatCount = bytes.Length / sizeof(float);
        var samples = new float[floatCount];
        if (floatCount > 0)
        {
            MemoryMarshal.Cast<byte, float>(bytes).CopyTo(samples);
        }

        return new MicrophoneFrame(
            Samples: samples,
            SampleCount: floatCount,
            UnixNanos: proto.UnixNanos,
            FrameId: (long)proto.FrameId
        );
    }
}
