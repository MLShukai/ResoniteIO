using BepInEx;

namespace ResoniteIO.Renderer;

/// <summary>
/// Renderite renderer (Wine + Unity Mono、BepInEx 5) で動く plugin entry。
/// </summary>
/// <remarks>
/// engine 側 (BepInEx 6 = <c>BasePlugin</c>) とは異なり、renderer 側は
/// **BepInEx 5 系 = <see cref="BaseUnityPlugin"/>** を継承する (knowledge §1)。
/// </remarks>
[BepInPlugin(PluginGuid, PluginName, PluginVersion)]
public sealed class Plugin : BaseUnityPlugin
{
    /// <summary>Thunderstore manifest と整合する plugin GUID。</summary>
    public const string PluginGuid = "net.mlshukai.resonite-io.renderer";

    /// <summary>BepInEx 5 が log に出す plugin 表示名。</summary>
    public const string PluginName = "ResoniteIO.Renderer";

    /// <summary>plugin の semver。engine 側 mod と独立して bump できる。</summary>
    public const string PluginVersion = "0.1.0";

    private FrameSender? _sender;
    private FrameCapture? _capture;

    // BepInEx 5 BaseUnityPlugin は Unity の Awake / Update / OnDestroy を
    // reflection で呼び出すため、private でも問題ない。
    private void Awake()
    {
        Logger.LogInfo($"[{PluginName}] Awake (version {PluginVersion})");
        try
        {
            _sender = new FrameSender(Logger);
            _capture = new FrameCapture(_sender, Logger);
        }
        catch (System.Exception ex)
        {
            Logger.LogError($"[{PluginName}] initialization failed: {ex}");
            _capture?.Dispose();
            _sender?.Dispose();
            _capture = null;
            _sender = null;
        }
    }

    private void Update()
    {
        _capture?.TryCapture();
    }

    private void OnDestroy()
    {
        Logger.LogInfo($"[{PluginName}] OnDestroy");
        _capture?.Dispose();
        _sender?.Dispose();
        _capture = null;
        _sender = null;
    }
}
