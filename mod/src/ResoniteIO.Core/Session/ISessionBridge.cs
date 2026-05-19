namespace ResoniteIO.Core.Session;

/// <summary>
/// Core 層が FrooxEngine の Session 状態を読むための抽象。Mod 側が実装し DI で注入する。
/// </summary>
/// <remarks>
/// 実装は engine update tick 上で内部 snapshot を publish し、本プロパティの読み出しは
/// 任意スレッドから cost-free に行える前提。null は値が未確定 (engine ready 直後など)。
/// </remarks>
public interface ISessionBridge
{
    string? FocusedWorldName { get; }

    string? LocalUserName { get; }
}
