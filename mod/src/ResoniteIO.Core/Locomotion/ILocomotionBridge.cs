namespace ResoniteIO.Core.Locomotion;

/// <summary>
/// Mod 側 (FrooxEngine) が実装し DI で注入する Locomotion 制御抽象。
/// </summary>
/// <remarks>
/// <para>
/// stateful repeater: Bridge は最新コマンドを保持し engine update tick ごとに
/// ExternalInput へ再注入する。Service は変化があった command のみ
/// <see cref="SetState"/> へ流せばよい。
/// </para>
/// <para>
/// 本契約は **任意スレッドから呼ばれる**。engine thread への dispatch は実装側
/// で隠蔽する。precondition 失敗 (LocalUser 未生成、active module が
/// SmoothLocomotion でない等) は **例外を投げず** Bridge 内部で次 tick の再
/// 評価に委ねる。Service 経由で client に通知する経路は存在しない (consumer
/// に見せても retry 戦略にならないため)。
/// </para>
/// <para>
/// 各 field の semantics は <c>proto/resonite_io/v1/locomotion.proto</c> が
/// 一次正典 (velocity 単位元 1.0、jump consume-once pulse、pitch 符号など)。
/// </para>
/// </remarks>
public interface ILocomotionBridge
{
    /// <summary>最新コマンドを Bridge state に latest-wins で書き込む。</summary>
    void SetState(LocomotionInput command);

    /// <summary>
    /// 指定 field を中立値に戻す。<see cref="LocomotionResetFlags.None"/> は
    /// no-op (Service 層で <see cref="LocomotionResetFlags.All"/> へ展開する
    /// 規約は <c>LocomotionResetRequest</c> 参照)。
    /// </summary>
    void Reset(LocomotionResetFlags flags);

    /// <summary>
    /// gRPC Drive stream の終了種別を通知する。
    /// <see cref="LocomotionDisconnectReason.Graceful"/> は state 維持、
    /// それ以外は Bridge 側で全 state を safety reset する。
    /// 本メソッドは must not throw — Service 側は本契約を信頼してガードしない。
    /// </summary>
    void NotifyDisconnect(LocomotionDisconnectReason reason);
}

/// <summary>proto 生成型 <c>V1.LocomotionCommand</c> から独立した Core 層 POCO。</summary>
/// <remarks>各 field の semantics は <c>proto/resonite_io/v1/locomotion.proto</c>。</remarks>
public readonly record struct LocomotionInput(
    float MoveForward,
    float MoveRight,
    float MoveUp,
    float YawRate,
    float PitchRate,
    bool Jump,
    float Velocity,
    float Crouch,
    long UnixNanos
)
{
    /// <summary>
    /// 全 field 中立値の input (velocity=1.0、それ以外は 0/false)。Bridge
    /// 初期化や全 reset 後の派生 state として使う。<c>UnixNanos = 0</c>。
    /// </summary>
    public static LocomotionInput Neutral { get; } =
        new(
            MoveForward: 0f,
            MoveRight: 0f,
            MoveUp: 0f,
            YawRate: 0f,
            PitchRate: 0f,
            Jump: false,
            Velocity: 1.0f,
            Crouch: 0f,
            UnixNanos: 0L
        );

    /// <summary>
    /// 指定 <see cref="LocomotionResetFlags"/> に従って中立値を反映した派生
    /// input を返す。<see cref="LocomotionResetFlags.None"/> は元の input を
    /// そのまま返す。Move reset は velocity=1.0 への復帰も含む (proto velocity
    /// 単位元 1.0 の規約)。
    /// </summary>
    public LocomotionInput ApplyReset(LocomotionResetFlags flags)
    {
        var state = this;
        if (flags.HasFlag(LocomotionResetFlags.Move))
        {
            state = state with { MoveForward = 0f, MoveRight = 0f, MoveUp = 0f, Velocity = 1.0f };
        }
        if (flags.HasFlag(LocomotionResetFlags.Look))
        {
            state = state with { YawRate = 0f, PitchRate = 0f };
        }
        if (flags.HasFlag(LocomotionResetFlags.Crouch))
        {
            state = state with { Crouch = 0f };
        }
        if (flags.HasFlag(LocomotionResetFlags.Jump))
        {
            state = state with { Jump = false };
        }
        return state;
    }
}

/// <summary>
/// <see cref="ILocomotionBridge.Reset"/> で reset する field を指定する bitmask。
/// </summary>
[Flags]
public enum LocomotionResetFlags
{
    None = 0,
    Move = 1 << 0,
    Look = 1 << 1,
    Crouch = 1 << 2,
    Jump = 1 << 3,
    All = Move | Look | Crouch | Jump,
}

/// <summary>
/// <see cref="ILocomotionBridge.NotifyDisconnect"/> に渡される stream 終了種別。
/// </summary>
public enum LocomotionDisconnectReason
{
    /// <summary>client が <c>CompleteAsync</c> で stream を正常終了。state 維持。</summary>
    Graceful,

    /// <summary>UDS 切断 / client cancel / deadline 超過。全 state を reset。</summary>
    Cancelled,

    /// <summary>Bridge 内部 / Service 内部の予期せぬ例外。全 state を reset。</summary>
    Errored,
}
