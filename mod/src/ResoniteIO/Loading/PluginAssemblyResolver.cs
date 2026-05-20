using System;
using System.IO;
using System.Reflection;
using System.Runtime.Loader;
using BepInEx.Logging;

namespace ResoniteIO.Loading;

/// <summary>
/// Default ALC が解決できなかった type/assembly 要求を plugin folder 同梱 DLL で
/// fallback 解決する <see cref="AssemblyLoadContext"/>.Resolving subscriber。
/// </summary>
/// <remarks>
/// BepInEx は plugin folder を Default ALC の probe path に登録しないため、これが無いと
/// runtime が <see cref="FileNotFoundException"/> を投げる。
/// 寿命は plugin と一致させる: dispose 後の lazy ロードは同じ理由で fail する。
/// <para>
/// 「Resonite 同梱 Google.Protobuf より plugin folder 版を優先する」効果は、本 class
/// 単体ではなく <see cref="ResoniteIOPlugin.Load"/> の協調動作で成立する:
/// (a) plugin folder の Google.Protobuf がまだロードされていない状態で本 resolver を
/// attach し、(b) Core 型 (<c>BepInExLogSink</c> 等) への参照を
/// <c>OnEngineReady</c> まで遅延することで、Resonite 側 protobuf が早期ロードされる
/// 前に plugin folder 版を ALC に食わせる。
/// </para>
/// <para>
/// <c>ILogSink</c> ではなく BepInEx <see cref="ManualLogSource"/> を直接受ける理由は
/// 上記 (b) の帰結: ここで <c>ILogSink</c> を経由すると <c>ResoniteIO.Core.dll</c> が
/// 早期ロードされ、同 dll が依存する Google.Protobuf を Resonite 側 (旧版) から
/// 引いてしまう。
/// </para>
/// </remarks>
internal sealed class PluginAssemblyResolver : IDisposable
{
    private readonly string _pluginDirectory;
    private readonly ManualLogSource _log;
    private bool _disposed;

    public PluginAssemblyResolver(string pluginDirectory, ManualLogSource log)
    {
        ArgumentException.ThrowIfNullOrEmpty(pluginDirectory);
        ArgumentNullException.ThrowIfNull(log);

        _pluginDirectory = pluginDirectory;
        _log = log;
        AssemblyLoadContext.Default.Resolving += Resolve;
    }

    private Assembly? Resolve(AssemblyLoadContext context, AssemblyName assemblyName)
    {
        if (assemblyName.Name is null)
        {
            return null;
        }

        var candidate = Path.Combine(_pluginDirectory, $"{assemblyName.Name}.dll");
        if (!File.Exists(candidate))
        {
            return null;
        }

        try
        {
            return context.LoadFromAssemblyPath(candidate);
        }
        catch (Exception ex)
        {
            _log.LogWarning(
                $"Failed to resolve '{assemblyName.Name}' from plugin folder: {ex.Message}"
            );
            return null;
        }
    }

    public void Dispose()
    {
        if (_disposed)
        {
            return;
        }
        _disposed = true;
        AssemblyLoadContext.Default.Resolving -= Resolve;
    }
}
