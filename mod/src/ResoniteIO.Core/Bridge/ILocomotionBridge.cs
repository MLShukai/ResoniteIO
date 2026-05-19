namespace ResoniteIO.Core.Bridge;

/// <summary>
/// Mod 側 (FrooxEngine) が実装し DI で注入する Locomotion 制御抽象。
/// </summary>
/// <remarks>
/// 本契約は ExternalInput を書き込むだけの "1 frame ぶんの指令" を表す。
/// engine 側 `Analog3DAction.ExternalInput` は update tick で消費 + null reset
/// されるので、入力を持続させたい場合は Service 層が同じ command を 30Hz 程度
/// で連続発行する。<see cref="ApplyAsync"/> は任意スレッドから呼ばれる
/// (engine thread への dispatch が必要なら実装側で隠蔽する)。
/// </remarks>
public interface ILocomotionBridge
{
    /// <exception cref="LocomotionNotReadyException">
    /// engine がまだ locomotion を制御できる状態に無い (LocalUser 未生成、active
    /// module が SmoothLocomotion ではない、world 切替中等)。
    /// </exception>
    Task ApplyAsync(LocomotionCommand command, CancellationToken ct);
}

/// <summary>proto 生成型 <c>V1.LocomotionCommand</c> から独立した Core 層 POCO。</summary>
/// <remarks>
/// 各 field の semantics は <c>proto/resonite_io/v1/locomotion.proto</c> を参照
/// (velocity の 0→1.0 再解釈・pitch の符号反転責務もそこに定義)。
/// </remarks>
public readonly record struct LocomotionCommand(
    float MoveX,
    float MoveY,
    float YawRate,
    float PitchRate,
    bool Jump,
    float Velocity,
    float Crouch,
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
