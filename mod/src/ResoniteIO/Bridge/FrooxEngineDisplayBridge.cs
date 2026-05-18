using System.Threading;
using System.Threading.Tasks;
using Elements.Core;
using FrooxEngine;
using ResoniteIO.Core.Display;
using ResoniteIO.Core.Logging;

namespace ResoniteIO.Bridge;

/// <summary>
/// FrooxEngine の <see cref="Settings"/> 経由で window resolution + max fps を制御する
/// <see cref="IDisplayBridge"/> 実装。
/// </summary>
/// <remarks>
/// <para>
/// マッピング:
/// </para>
/// <list type="bullet">
///   <item>
///     <description>
///       <c>Width</c> / <c>Height</c> → <see cref="ResolutionSettings"/> の
///       <c>CurrentTargetResolution</c> + <c>CommitedWindowResolution</c> /
///       <c>CommitedFullscreenResolution</c>。engine の <c>OnResolutionSettingsChanged</c>
///       hook が renderer に <c>ResolutionConfig</c> を送る。
///     </description>
///   </item>
///   <item>
///     <description>
///       <c>MaxFps</c> → <see cref="DesktopRenderSettings.MaximumBackgroundFramerate"/>。
///       <para>
///       注意: これは **背景時** の fps cap。<c>RenderSystem.OnDesktopRenderSettingsChanged</c>
///       は <c>maximumForegroundFramerate</c> を送出しないため、現状の engine API
///       経由では foreground fps を直接設定できない (knowledge §3.4 で
///       <c>max_fps_foreground=120</c> 実現に使った経路は engine の private
///       <c>_messagingHost</c> への直接アクセスを要する。public API には乗っていない)。
///       本 Bridge は engine 公式 plumbing に乗る範囲で最も妥当なフィールドにマップ
///       しているが、Wave 5 の実機検証で foreground fps 制御が必要と判明したら、
///       reflection 経由の <c>DesktopConfig</c> 直接送信に切り替える前提。
///       </para>
///     </description>
///   </item>
/// </list>
/// <para>
/// <c>Width=0</c> / <c>Height=0</c> / <c>MaxFps=0</c> は proto3 default = "変更しない"
/// セマンティクス (C5 仕様)。Bridge は 0 を skip して engine に書き込まない。
/// </para>
/// <para>
/// engine thread dispatch: <see cref="Settings.UpdateActiveSetting{T}"/> は内部で
/// <c>setting.RunSynchronously(...)</c> を使うため engine update tick 上で適用される。
/// 本 Bridge は同期 path で <c>Task.FromResult</c> を返し、await は不要 (engine
/// thread への dispatch は Settings が隠蔽)。
/// </para>
/// </remarks>
internal sealed class FrooxEngineDisplayBridge : IDisplayBridge
{
    private readonly ILogSink _log;

    public FrooxEngineDisplayBridge(ILogSink log)
    {
        _log = log;
    }

    /// <inheritdoc/>
    public Task<DisplayConfigSnapshot> ApplyAsync(
        DisplayConfigSnapshot config,
        CancellationToken ct
    )
    {
        ct.ThrowIfCancellationRequested();

        // Resolution の書き込み (Width または Height のどちらかが 0 でないとき)。
        // Settings.UpdateActiveSetting は engine thread 上で適用 (RunSynchronously)。
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
                // commit してすぐ反映させる (engine の OnResolutionSettingsChanged が
                // ResolutionConfig を renderer に送る)。
                s.CurrentCommitedResolution = target;
            });
            if (!updated)
            {
                throw new DisplayNotReadyException(
                    "ResolutionSettings.UpdateActiveSetting failed (engine not ready)."
                );
            }
            _log.LogInfo($"[ResoniteIO] Display.Apply: resolution → {newWidth}x{newHeight}");
        }

        // Max FPS 書き込み (現状は MaximumBackgroundFramerate にマップする;
        // foreground fps は engine public API に乗らないため Wave 5 で再評価)。
        if (config.MaxFps > 0f)
        {
            var desktop = Settings.GetActiveSetting<DesktopRenderSettings>();
            if (desktop is null)
            {
                throw new DisplayNotReadyException(
                    "DesktopRenderSettings is not yet active; engine still initializing."
                );
            }

            // engine 側 OnDesktopRenderSettingsChanged は BackgroundFramerateEnabled
            // が true でないと renderer に送出しないので、ここで連動して true にする。
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

        return Task.FromResult(ReadCurrent());
    }

    /// <inheritdoc/>
    public Task<DisplayConfigSnapshot> GetAsync(CancellationToken ct)
    {
        ct.ThrowIfCancellationRequested();
        return Task.FromResult(ReadCurrent());
    }

    /// <summary>engine 内の現在値を <see cref="DisplayConfigSnapshot"/> として読み返す。</summary>
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
