using ResoniteIO.Core.Display;

namespace ResoniteIO.Core.Tests.Helpers;

/// <summary>テスト用 <see cref="IDisplayBridge"/>。Apply は request を <see cref="LastApplied"/>
/// に保存しつつ proto "0 = 変更しない" を <see cref="CurrentState"/> に反映する。</summary>
/// <remarks>
/// <see cref="ThrowNotReady"/> = true なら全 RPC で <see cref="DisplayNotReadyException"/>
/// を投げる (FailedPrecondition 翻訳テスト用)。
/// </remarks>
internal sealed class FakeDisplayBridge : IDisplayBridge
{
    public DisplayConfigSnapshot CurrentState { get; set; } =
        new()
        {
            Width = 1280,
            Height = 720,
            MaxFps = 60.0f,
        };

    public DisplayConfigSnapshot? LastApplied { get; private set; }

    public bool ThrowNotReady { get; set; }

    public Task ApplyAsync(DisplayConfigSnapshot config, CancellationToken ct)
    {
        if (ThrowNotReady)
        {
            throw new DisplayNotReadyException("FakeDisplayBridge: simulated not-ready state.");
        }
        ct.ThrowIfCancellationRequested();

        LastApplied = config;

        // 0 でない field だけ上書きする (proto セマンティクスの再現)。
        CurrentState = new DisplayConfigSnapshot
        {
            Width = config.Width != 0 ? config.Width : CurrentState.Width,
            Height = config.Height != 0 ? config.Height : CurrentState.Height,
            MaxFps = config.MaxFps != 0f ? config.MaxFps : CurrentState.MaxFps,
        };

        return Task.CompletedTask;
    }

    public Task<DisplayConfigSnapshot> GetAsync(CancellationToken ct)
    {
        if (ThrowNotReady)
        {
            throw new DisplayNotReadyException("FakeDisplayBridge: simulated not-ready state.");
        }
        ct.ThrowIfCancellationRequested();
        return Task.FromResult(CurrentState);
    }
}
