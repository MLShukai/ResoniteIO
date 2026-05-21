using System.Threading;
using System.Threading.Tasks;
using Elements.Core;
using FrooxEngine;
using ResoniteIO.Core.Display;
using ResoniteIO.Core.Logging;

namespace ResoniteIO.Bridge;

/// <summary>
/// FrooxEngine の <see cref="Settings"/> 経由で window resolution + max fps を
/// 制御する <see cref="IDisplayBridge"/> 実装。
/// </summary>
/// <remarks>
/// <c>MaxFps</c> は engine 公式 API の都合で <b>background</b> fps cap
/// (<see cref="DesktopRenderSettings.MaximumBackgroundFramerate"/>) にしか
/// マップしない。<c>OnDesktopRenderSettingsChanged</c> が
/// <c>maximumForegroundFramerate</c> を送出しないため foreground 直接制御は
/// reflection 経由でしか不可能 (camera-v2-constraints §9)。
/// 0 field は proto3 default = "変更しない" として skip する。Apply の Empty
/// 応答契約は <see cref="IDisplayBridge.ApplyAsync"/> を参照。
/// </remarks>
internal sealed class FrooxEngineDisplayBridge : IDisplayBridge
{
    private readonly ILogSink _log;

    public FrooxEngineDisplayBridge(ILogSink log)
    {
        _log = log;
    }

    /// <inheritdoc/>
    public Task ApplyAsync(DisplayConfigSnapshot config, CancellationToken ct)
    {
        ct.ThrowIfCancellationRequested();

        if (config.Width != 0 || config.Height != 0)
        {
            var resolution = Settings.GetActiveSetting<ResolutionSettings>();
            if (resolution is null)
            {
                throw new DisplayNotReadyException(
                    "ResolutionSettings is not yet active; engine still initializing."
                );
            }

            var current = resolution.CurrentTargetResolution;
            var newWidth = config.Width != 0 ? (int)config.Width : current.x;
            var newHeight = config.Height != 0 ? (int)config.Height : current.y;
            var target = new int2(newWidth, newHeight);

            var updated = Settings.UpdateActiveSetting<ResolutionSettings>(s =>
            {
                s.CurrentTargetResolution = target;
                // ApplyResolution() で OnChanges → OnResolutionSettingsChanged →
                // RenderSystem.SendCommand の engine 正規 path に commit する。
                s.ApplyResolution();
            });
            if (!updated)
            {
                throw new DisplayNotReadyException(
                    "ResolutionSettings.UpdateActiveSetting failed (engine not ready)."
                );
            }
            _log.LogInfo($"[ResoniteIO] Display.Apply: resolution → {newWidth}x{newHeight}");
        }

        if (config.MaxFps > 0f)
        {
            var desktop = Settings.GetActiveSetting<DesktopRenderSettings>();
            if (desktop is null)
            {
                throw new DisplayNotReadyException(
                    "DesktopRenderSettings is not yet active; engine still initializing."
                );
            }

            // OnDesktopRenderSettingsChanged は LimitFramerateWhenUnfocused=true でないと
            // renderer に送出しないため連動して true にする。
            var fps = (int)config.MaxFps;
            var updated = Settings.UpdateActiveSetting<DesktopRenderSettings>(s =>
            {
                s.MaximumBackgroundFramerate.Value = fps;
                s.LimitFramerateWhenUnfocused.Value = true;
            });
            if (!updated)
            {
                throw new DisplayNotReadyException(
                    "DesktopRenderSettings.UpdateActiveSetting failed (engine not ready)."
                );
            }
            _log.LogInfo($"[ResoniteIO] Display.Apply: max_fps (background) → {fps}");
        }

        return Task.CompletedTask;
    }

    /// <inheritdoc/>
    public Task<DisplayConfigSnapshot> GetAsync(CancellationToken ct)
    {
        ct.ThrowIfCancellationRequested();
        return Task.FromResult(ReadCurrent());
    }

    private static DisplayConfigSnapshot ReadCurrent()
    {
        var resolution = Settings.GetActiveSetting<ResolutionSettings>();
        var desktop = Settings.GetActiveSetting<DesktopRenderSettings>();
        if (resolution is null || desktop is null)
        {
            throw new DisplayNotReadyException(
                "ResolutionSettings / DesktopRenderSettings is not yet active."
            );
        }

        var res = resolution.CurrentTargetResolution;
        return new DisplayConfigSnapshot
        {
            Width = (uint)res.x,
            Height = (uint)res.y,
            MaxFps = desktop.MaximumBackgroundFramerate.Value,
        };
    }
}
