namespace ResoniteIO.Core.Bridge;

/// <summary>
/// Mod 側 (FrooxEngine) が実装し DI で注入する Locomotion (移動 + 視点 + jump /
/// sprint / crouch) 制御抽象。
/// </summary>
/// <remarks>
/// <see cref="ApplyAsync"/> は任意スレッドから呼ばれる。engine update tick への
/// dispatch (例えば component lookup が engine thread を要求する場合) は実装側で
/// 隠蔽する。本契約は ExternalInput を書き込むだけの "1 frame ぶんの指令" を
/// 表す。入力を持続させたい場合 Service 層が client-streaming RPC で同じ command
/// を 30Hz 程度で連続発行する。
/// </remarks>
public interface ILocomotionBridge
{
    /// <summary>
    /// 1 件の <see cref="LocomotionCommand"/> を engine に適用する。
    /// </summary>
    /// <exception cref="LocomotionNotReadyException">
    /// engine がまだ locomotion を制御できる状態に無い (LocalUser 未生成、active
    /// module が SmoothLocomotion ではない、world 切替中等)。
    /// </exception>
    Task ApplyAsync(LocomotionCommand command, CancellationToken ct);
}

/// <summary>proto 生成型 <c>V1.LocomotionCommand</c> から独立した Core 層 POCO。</summary>
/// <remarks>
/// 各 field の semantics は <c>proto/resonite_io/v1/locomotion.proto</c> に揃える。
/// pitch は「上向き正」で API 化し、engine 側の符号反転は Bridge 実装の責務。
/// </remarks>
public readonly record struct LocomotionCommand(
    float MoveX,
    float MoveY,
    float YawRate,
    float PitchRate,
    bool Jump,
    bool Sprint,
    float Crouch,
    float SprintMultiplier,
    long UnixNanos
);

/// <summary>
/// Bridge が一時的に locomotion を制御できない状態。Service 層が
/// <c>Status.FailedPrecondition</c> に翻訳するので Client は時間を置いて再 Drive で
/// retry できる。
/// </summary>
public sealed class LocomotionNotReadyException : Exception
{
    public LocomotionNotReadyException(string message)
        : base(message) { }

    public LocomotionNotReadyException(string message, Exception innerException)
        : base(message, innerException) { }
}
