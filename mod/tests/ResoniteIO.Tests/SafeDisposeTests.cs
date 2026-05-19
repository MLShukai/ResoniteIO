using System;
using Xunit;

namespace ResoniteIO.Tests;

/// <summary>
/// <see cref="ResoniteIOPlugin.SafeDispose"/> の挙動 (例外握りつぶし / null 許容) を
/// 検証する単体テスト。BasePlugin はインスタンス化に BepInEx の context が必要で
/// 困難なため、helper を <c>internal static</c> に露出してここから直接呼ぶ。
/// </summary>
public sealed class SafeDisposeTests
{
    private sealed class ThrowingDisposable : IDisposable
    {
        public bool DisposeCalled { get; private set; }

        public void Dispose()
        {
            DisposeCalled = true;
            throw new InvalidOperationException("boom");
        }
    }

    private sealed class CountingDisposable : IDisposable
    {
        public int DisposeCount { get; private set; }

        public void Dispose() => DisposeCount++;
    }

    [Fact]
    public void SafeDispose_Null_DoesNotThrow()
    {
        // null 入力は no-op (ProcessExit 経路で「先に SafeShutdown が走り field が null
        // 化された後の二重呼び出し」を許容する保証)。
        var ex = Record.Exception(() => ResoniteIOPlugin.SafeDispose(null, "field"));
        Assert.Null(ex);
    }

    [Fact]
    public void SafeDispose_ThrowingDispose_SwallowsException()
    {
        // ProcessExit 経路では Log sink が信頼できないため、Dispose 内で例外が出ても
        // 上位に伝播させない (後続 field の cleanup を継続させる)。
        var target = new ThrowingDisposable();
        var ex = Record.Exception(() => ResoniteIOPlugin.SafeDispose(target, nameof(target)));
        Assert.Null(ex);
        Assert.True(target.DisposeCalled);
    }

    [Fact]
    public void SafeDispose_NormalDispose_InvokesDisposeOnce()
    {
        var target = new CountingDisposable();
        ResoniteIOPlugin.SafeDispose(target, nameof(target));
        Assert.Equal(1, target.DisposeCount);
    }
}
