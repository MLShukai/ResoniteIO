using Xunit;

namespace ResoniteIO.Core.Tests.Common;

internal static class TestPolling
{
    public static async Task WaitUntilAsync(
        Func<bool> predicate,
        TimeSpan timeout,
        string failureMessage
    )
    {
        var deadline = DateTime.UtcNow + timeout;
        while (DateTime.UtcNow < deadline)
        {
            if (predicate())
            {
                return;
            }
            await Task.Delay(50);
        }
        Assert.Fail(failureMessage);
    }
}
