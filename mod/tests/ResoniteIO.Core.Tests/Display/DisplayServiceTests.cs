using Grpc.Core;
using ResoniteIO.Core.Tests.Helpers;
using ResoniteIO.V1;
using Xunit;

namespace ResoniteIO.Core.Tests.Display;

/// <summary>
/// <see cref="Core.Display.DisplayService"/> の Apply / Get round-trip と
/// 例外翻訳を検証する。
/// </summary>
public sealed class DisplayServiceTests
{
    [Fact]
    public async Task Apply_returns_applied_state()
    {
        var bridge = new FakeDisplayBridge
        {
            CurrentState = new()
            {
                Width = 800,
                Height = 600,
                MaxFps = 30f,
            },
        };
        await using var host = await DisplayServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Display.DisplayClient(channel);

        var request = new DisplayConfig
        {
            Width = 1920,
            Height = 1080,
            MaxFps = 120f,
        };
        var state = await client.ApplyAsync(request);

        Assert.Equal(1920u, state.Width);
        Assert.Equal(1080u, state.Height);
        Assert.Equal(120f, state.MaxFps);

        // Bridge には request snapshot がそのまま渡る (0 / 空の解釈は Bridge 側)。
        Assert.NotNull(bridge.LastApplied);
        Assert.Equal(1920u, bridge.LastApplied!.Width);
        Assert.Equal(1080u, bridge.LastApplied!.Height);
        Assert.Equal(120f, bridge.LastApplied!.MaxFps);
    }

    [Fact]
    public async Task Get_returns_current_state()
    {
        var bridge = new FakeDisplayBridge
        {
            CurrentState = new()
            {
                Width = 2560,
                Height = 1440,
                MaxFps = 144f,
            },
        };
        await using var host = await DisplayServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Display.DisplayClient(channel);

        var state = await client.GetAsync(new DisplayGetRequest());

        Assert.Equal(2560u, state.Width);
        Assert.Equal(1440u, state.Height);
        Assert.Equal(144f, state.MaxFps);
    }

    [Fact]
    public async Task Apply_with_zero_fields_passes_zeros_to_bridge()
    {
        // proto level: 0 / 空は "変更しない" を意味する。Service は変換せず
        // そのまま Bridge に渡し、Bridge 側で 0 でない field だけを engine に書く。
        var bridge = new FakeDisplayBridge
        {
            CurrentState = new()
            {
                Width = 1280,
                Height = 720,
                MaxFps = 60f,
            },
        };
        await using var host = await DisplayServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Display.DisplayClient(channel);

        // max_fps のみ更新、他は 0 (= 変更しない)。
        var request = new DisplayConfig { MaxFps = 120f };
        var state = await client.ApplyAsync(request);

        // Bridge は 0 をそのまま受け取り、0 でない field だけ上書きする。
        Assert.NotNull(bridge.LastApplied);
        Assert.Equal(0u, bridge.LastApplied!.Width);
        Assert.Equal(0u, bridge.LastApplied!.Height);
        Assert.Equal(120f, bridge.LastApplied!.MaxFps);

        // Service の返値は Bridge が返した "現値" snapshot をそのまま転送する。
        Assert.Equal(1280u, state.Width);
        Assert.Equal(720u, state.Height);
        Assert.Equal(120f, state.MaxFps);
    }

    [Fact]
    public async Task Apply_translates_DisplayNotReadyException_to_FailedPrecondition()
    {
        var bridge = new FakeDisplayBridge { ThrowNotReady = true };
        await using var host = await DisplayServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Display.DisplayClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.ApplyAsync(new DisplayConfig())
        );
        Assert.Equal(StatusCode.FailedPrecondition, ex.StatusCode);
    }

    [Fact]
    public async Task Get_translates_DisplayNotReadyException_to_FailedPrecondition()
    {
        var bridge = new FakeDisplayBridge { ThrowNotReady = true };
        await using var host = await DisplayServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Display.DisplayClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.GetAsync(new DisplayGetRequest())
        );
        Assert.Equal(StatusCode.FailedPrecondition, ex.StatusCode);
    }
}
