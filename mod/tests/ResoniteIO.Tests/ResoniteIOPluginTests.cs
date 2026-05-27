using System.Reflection;
using BepInExResoniteShim;
using Xunit;

namespace ResoniteIO.Tests;

/// <summary>
/// プラグインアセンブリのメタデータが想定通りであることを検証する smoke test。
/// </summary>
/// <remarks>
/// BepInEx ランタイムが居ない環境で <see cref="ResoniteIOPlugin.Load"/> を
/// 直接呼ぶと <c>BasePlugin</c> 内部の <c>Log</c> が初期化されておらず NRE になる。
/// そのためここではアセンブリ名と <see cref="ResonitePluginAttribute"/> の
/// 静的メタデータのみを確認する。Resonite 起動を伴うロード確認は
/// <c>python/tests/e2e/</c> の harness が host-agent 経由で行う。
/// </remarks>
public sealed class ResoniteIOPluginTests
{
    [Fact]
    public void AssemblyName_Matches_ProjectAssemblyName()
    {
        var asm = typeof(ResoniteIOPlugin).Assembly;
        Assert.Equal("ResoniteIO", asm.GetName().Name);
    }

    [Fact]
    public void PluginType_HasResonitePluginAttribute_WithMatchingMetadata()
    {
        var attr = typeof(ResoniteIOPlugin).GetCustomAttribute<ResonitePlugin>();
        Assert.NotNull(attr);
        Assert.Equal(PluginMetadata.GUID, attr!.GUID);
        Assert.Equal(PluginMetadata.NAME, attr.Name);
        Assert.Equal(PluginMetadata.VERSION, attr.Version.ToString());
    }
}
