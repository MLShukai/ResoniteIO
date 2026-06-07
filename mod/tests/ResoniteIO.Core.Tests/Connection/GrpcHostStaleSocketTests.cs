using System.Diagnostics;
using ResoniteIO.Core.Tests.Common;
using Xunit;

namespace ResoniteIO.Core.Tests.Connection;

[Collection("GrpcHostEnv")]
public sealed class GrpcHostStaleSocketTests : IDisposable
{
    private readonly string _tmpDir = Path.Combine(
        Path.GetTempPath(),
        $"rio-stale-{Guid.NewGuid():N}"
    );

    public GrpcHostStaleSocketTests()
    {
        Directory.CreateDirectory(_tmpDir);
    }

    public void Dispose()
    {
        try
        {
            Directory.Delete(_tmpDir, recursive: true);
        }
        catch { }
    }

    [Fact]
    public async Task DeadPidSocket_IsRemovedOnStart()
    {
        var stalePid = SpawnAndExitChild();
        var stalePath = Path.Combine(_tmpDir, $"resonite-{stalePid}.sock");
        File.WriteAllText(stalePath, "");

        await using var harness = await GrpcHostHarness.StartAsync(SocketPathInTmp());

        Assert.False(File.Exists(stalePath), $"stale socket should be purged: {stalePath}");
    }

    [Fact]
    public async Task LiveOtherPidSocket_IsKept()
    {
        using var live = Process.Start("/bin/sleep", "30");
        try
        {
            var livePath = Path.Combine(_tmpDir, $"resonite-{live.Id}.sock");
            File.WriteAllText(livePath, "");

            await using var harness = await GrpcHostHarness.StartAsync(SocketPathInTmp());

            Assert.True(File.Exists(livePath), $"live PID socket must be kept: {livePath}");
        }
        finally
        {
            live.Kill();
            live.WaitForExit(5000);
        }
    }

    [Fact]
    public async Task UnrelatedFiles_AreNotTouched()
    {
        var nonSocket = Path.Combine(_tmpDir, "foo.sock");
        var nonNumeric = Path.Combine(_tmpDir, "resonite-abc.sock");
        File.WriteAllText(nonSocket, "");
        File.WriteAllText(nonNumeric, "");

        await using var harness = await GrpcHostHarness.StartAsync(SocketPathInTmp());

        Assert.True(File.Exists(nonSocket), "non-matching filename must be kept");
        Assert.True(File.Exists(nonNumeric), "non-numeric PID filename must be kept");
    }

    [Fact]
    public async Task MissingDirectory_IsRecreatedAndStartSucceeds()
    {
        Directory.Delete(_tmpDir, recursive: true);

        await using var harness = await GrpcHostHarness.StartAsync(SocketPathInTmp());

        Assert.True(File.Exists(harness.SocketPath));
    }

    private string SocketPathInTmp() =>
        Path.Combine(_tmpDir, $"resonite-{Process.GetCurrentProcess().Id}.sock");

    // PID をすぐ消化する子プロセス。WaitForExit 後の PID は OS が再利用するまでは
    // 死亡判定される。直後にテストするため再利用の race は許容範囲。
    private static int SpawnAndExitChild()
    {
        using var proc = Process.Start("/bin/true") ?? throw new InvalidOperationException();
        proc.WaitForExit(5000);
        return proc.Id;
    }
}
