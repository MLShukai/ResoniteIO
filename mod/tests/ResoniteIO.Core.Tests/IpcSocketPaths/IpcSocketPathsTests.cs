using System;
using ResoniteIO.RendererShared;
using Xunit;

namespace ResoniteIO.Core.Tests.IpcSocketPaths;

/// <summary>
/// <see cref="ResoniteIO.RendererShared.IpcSocketPaths.QueueName"/> の env-override 解決を
/// 検証する。多重起動時に engine が token を env へ流し、renderer が継承して同名を読む経路の
/// 単体保証。env は process-global なので単一テスト内で set/clear を直列化し、元値を復元する。
/// </summary>
public sealed class IpcSocketPathsTests
{
    /// <summary>env 未設定なら従来固定名、設定すればその値を返す。</summary>
    [Fact]
    public void QueueName_honours_env_override_and_falls_back_to_default()
    {
        var original = Environment.GetEnvironmentVariable(
            RendererShared.IpcSocketPaths.QueueNameEnvVar
        );
        try
        {
            Environment.SetEnvironmentVariable(RendererShared.IpcSocketPaths.QueueNameEnvVar, null);
            Assert.Equal("resonite-io-camera-frames", RendererShared.IpcSocketPaths.QueueName);

            Environment.SetEnvironmentVariable(
                RendererShared.IpcSocketPaths.QueueNameEnvVar,
                "resonite-io-camera-instance-a"
            );
            Assert.Equal("resonite-io-camera-instance-a", RendererShared.IpcSocketPaths.QueueName);

            // 空文字は「未設定」と同じ扱いで fallback する。
            Environment.SetEnvironmentVariable(RendererShared.IpcSocketPaths.QueueNameEnvVar, "");
            Assert.Equal("resonite-io-camera-frames", RendererShared.IpcSocketPaths.QueueName);
        }
        finally
        {
            Environment.SetEnvironmentVariable(
                RendererShared.IpcSocketPaths.QueueNameEnvVar,
                original
            );
        }
    }
}
