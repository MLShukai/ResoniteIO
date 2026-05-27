using Xunit;

namespace ResoniteIO.Core.Tests.Common;

/// <summary>
/// <see cref="UnixNanosClock"/> の振る舞いの単体テスト。
/// </summary>
public sealed class UnixNanosClockTests
{
    [Fact]
    public void Now_AgreesWithDateTimeOffsetUtcNow_WithinSmallTolerance()
    {
        // OS の system tick 解像度 (Windows / Wine では ~1ms) を踏まえ、数十ms の許容差で
        // DateTimeOffset.UtcNow からの ns 換算と一致することを確認する。
        var clockNanos = UnixNanosClock.Now();
        var referenceNanos = (DateTimeOffset.UtcNow.UtcTicks - DateTime.UnixEpoch.Ticks) * 100L;

        var diff = Math.Abs(referenceNanos - clockNanos);
        Assert.True(
            diff < 50_000_000L,
            $"UnixNanosClock.Now() diverged from DateTimeOffset.UtcNow by {diff} ns"
        );
    }

    [Fact]
    public void Now_IsMonotonicNonDecreasing_AcrossConsecutiveCalls()
    {
        var samples = new long[16];
        for (var i = 0; i < samples.Length; i++)
        {
            samples[i] = UnixNanosClock.Now();
        }

        for (var i = 1; i < samples.Length; i++)
        {
            Assert.True(
                samples[i] >= samples[i - 1],
                $"Sample {i} ({samples[i]}) < sample {i - 1} ({samples[i - 1]})"
            );
        }
    }
}
