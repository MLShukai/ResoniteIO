using BepInEx;

namespace ResoniteIO.Renderer;

/// <summary>
/// Renderite renderer (Wine + Unity Mono、BepInEx 5) で動く plugin entry。
/// engine 側 (BepInEx 6 = <c>BasePlugin</c>) と異なり <see cref="BaseUnityPlugin"/>
/// を継承する。
/// </summary>
[BepInPlugin(PluginGuid, PluginName, PluginVersion)]
public sealed class Plugin : BaseUnityPlugin
{
    public const string PluginGuid = "net.mlshukai.resonite-io.renderer";

    public const string PluginName = "ResoniteIO.Renderer";

    public const string PluginVersion = "0.1.0";

    private FrameSender? _sender;
    private FrameCapture? _capture;

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
