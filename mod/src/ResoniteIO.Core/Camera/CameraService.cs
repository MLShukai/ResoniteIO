using System.Diagnostics;
using Google.Protobuf;
using Grpc.Core;
using ResoniteIO.Core.Logging;
using ResoniteIO.Core.Rpc;

#pragma warning disable CA1031 // catch (Exception) は Bridge 側の任意例外を gRPC Status に翻訳するために必要

namespace ResoniteIO.Core.Camera;

/// <summary><c>resonite_io.v1.Camera</c> サービスの Core 実装。</summary>
/// <remarks>
/// <see cref="ICameraBridge"/> は optional DI。null なら <c>Status.Unavailable</c> を返す
/// (Core 単体テストや camera 非対応 engine 構成を成立させるため)。
/// </remarks>
public sealed class CameraService : V1.Camera.CameraBase
{
    private const int DefaultWidth = 640;
    private const int DefaultHeight = 480;

    private readonly ICameraBridge? _bridge;
    private readonly ILogSink _log;

    public CameraService(ILogSink log, ICameraBridge? bridge = null)
    {
        _log = log;
        _bridge = bridge;
    }

    /// <summary>
    /// Bridge から 1 フレームずつ取り出して proto に詰めて流す server-streaming RPC。
    /// </summary>
    /// <remarks>
    /// width/height が 0 以下なら 640×480、<c>fps_limit</c> が 0 以下なら pacing 無し。
    /// fps_limit は capture 開始周期の上限 (capture+write が超過した場合は skip し、次 capture
    /// へ進む。catch-up しない)。
    /// 例外翻訳: bridge 未注入 → <c>Unavailable</c>、<see cref="CameraNotReadyException"/>
    /// → <c>FailedPrecondition</c> (client は時間を置いて再 stream)、それ以外 →
    /// <c>Internal</c>。<c>frame_id</c> は service 側で 0 から振り直す monotonic counter
    /// で Bridge 側 ID とは独立。
    /// </remarks>
    public override async Task StreamFrames(
        V1.CameraStreamRequest request,
        IServerStreamWriter<V1.CameraFrame> responses,
        ServerCallContext context
    )
    {
        var bridge = BridgeGuard.Require(_bridge, _log, "Camera", "ICameraBridge", "StreamFrames");

        var width = request.Width > 0 ? request.Width : DefaultWidth;
        var height = request.Height > 0 ? request.Height : DefaultHeight;
        var frameDelay =
            request.FpsLimit > 0f ? TimeSpan.FromSeconds(1.0 / request.FpsLimit) : TimeSpan.Zero;

        _log.LogDebug(
            $"Camera.StreamFrames start: width={width} height={height} "
                + $"fps_limit={request.FpsLimit}"
        );

        var ct = context.CancellationToken;
        long protoFrameId = 0;
        var stopwatch = new Stopwatch();

        while (!ct.IsCancellationRequested)
        {
            stopwatch.Restart();

            CameraFrame coreFrame;
            try
            {
                coreFrame = await bridge.CaptureAsync(width, height, ct).ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
                break;
            }
            catch (CameraNotReadyException ex)
            {
                _log.LogInfo($"Camera.StreamFrames: bridge not ready: {ex.Message}");
                throw new RpcException(new Status(StatusCode.FailedPrecondition, ex.Message));
            }
            catch (Exception ex)
            {
                _log.LogError($"Camera.StreamFrames: bridge faulted: {ex}");
                throw new RpcException(
                    new Status(StatusCode.Internal, $"Camera bridge faulted: {ex.Message}")
                );
            }

            var protoFrame = MapToProto(coreFrame, protoFrameId);
            protoFrameId++;

            try
            {
                await responses.WriteAsync(protoFrame, ct).ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
                break;
            }
            catch (InvalidOperationException ex)
            {
                // Client が disconnect すると WriteAsync が "response stream is completed"
                // 系の InvalidOperationException で抜ける実装がある。break 扱いで終了する。
                _log.LogDebug($"Camera.StreamFrames: write aborted: {ex.Message}");
                break;
            }

            if (frameDelay > TimeSpan.Zero)
            {
                var remaining = frameDelay - stopwatch.Elapsed;
                if (remaining > TimeSpan.Zero)
                {
                    try
                    {
                        await Task.Delay(remaining, ct).ConfigureAwait(false);
                    }
                    catch (OperationCanceledException)
                    {
                        break;
                    }
                }
            }
        }

        _log.LogDebug($"Camera.StreamFrames end: emitted {protoFrameId} frame(s)");
    }

    private static V1.CameraFrame MapToProto(CameraFrame frame, long protoFrameId)
    {
        return new V1.CameraFrame
        {
            Width = frame.Width,
            Height = frame.Height,
            Format = ToProtoFormat(frame.Format),
            UnixNanos = frame.UnixNanos,
            FrameId = protoFrameId,
            // Defensive copy で proto 側保持期間を Bridge buffer 寿命と切り離す。
            // 64MB クラスのフレームで perf 問題化したら UnsafeByteOperations.UnsafeWrap へ。
            Pixels = ByteString.CopyFrom(frame.Pixels),
        };
    }

    private static V1.CameraFrameFormat ToProtoFormat(CameraFrameFormat format) =>
        format switch
        {
            CameraFrameFormat.Rgba8 => V1.CameraFrameFormat.Rgba8,
            CameraFrameFormat.Unspecified => V1.CameraFrameFormat.Unspecified,
            _ => V1.CameraFrameFormat.Unspecified,
        };
}
