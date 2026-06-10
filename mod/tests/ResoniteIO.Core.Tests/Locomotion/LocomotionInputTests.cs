using ResoniteIO.Core.Locomotion;
using Xunit;

namespace ResoniteIO.Core.Tests.Locomotion;

/// <summary>
/// <see cref="LocomotionInput"/> (Neutral / ApplyReset) と差分マージ型
/// <see cref="LocomotionPartialInput"/> (MergeInto) の単体テスト。Bridge 実装と
/// FakeLocomotionBridge が同じ規約を共有することの担保。移動 3 軸
/// (MoveForward / MoveRight / MoveUp) の方向ベース名と、視点独立の絶対
/// ワールド上下軸 MoveUp が Move reset に巻き込まれることを押さえる。
/// proto → delta の presence mapping そのものは private mapping なので
/// 公開 wire を通す <see cref="LocomotionRoundTripTests"/> で検証する。
/// </summary>
public sealed class LocomotionInputTests
{
    [Fact]
    public void Neutral_HasVelocityOne_AndZeroOrFalseForRest()
    {
        var n = LocomotionInput.Neutral;
        Assert.Equal(0f, n.MoveForward);
        Assert.Equal(0f, n.MoveRight);
        Assert.Equal(0f, n.MoveUp);
        Assert.Equal(0f, n.YawRate);
        Assert.Equal(0f, n.PitchRate);
        Assert.False(n.Jump);
        Assert.Equal(1.0f, n.Velocity);
        Assert.Equal(0f, n.Crouch);
        Assert.Equal(0L, n.UnixNanos);
    }

    [Fact]
    public void ApplyReset_None_ReturnsOriginal()
    {
        var input = new LocomotionInput(
            MoveForward: 0.5f,
            MoveRight: 0.25f,
            MoveUp: -0.75f,
            YawRate: 0.25f,
            PitchRate: -0.1f,
            Jump: true,
            Velocity: 2.0f,
            Crouch: 0.75f,
            UnixNanos: 42L
        );
        Assert.Equal(input, input.ApplyReset(LocomotionResetFlags.None));
    }

    [Fact]
    public void ApplyReset_Move_ZeroesAllThreeMoveAxes_AndRestoresUnitVelocity()
    {
        var input = new LocomotionInput(
            MoveForward: 0.5f,
            MoveRight: 0.25f,
            MoveUp: -0.75f,
            YawRate: 0.25f,
            PitchRate: -0.1f,
            Jump: true,
            Velocity: 2.0f,
            Crouch: 0.75f,
            UnixNanos: 42L
        );
        var reset = input.ApplyReset(LocomotionResetFlags.Move);

        // Move reset は移動 3 軸すべて (MoveUp 含む) を 0 にする。
        Assert.Equal(0f, reset.MoveForward);
        Assert.Equal(0f, reset.MoveRight);
        Assert.Equal(0f, reset.MoveUp);
        Assert.Equal(1.0f, reset.Velocity); // proto velocity 単位元 1.0
        // Move 以外の field は据え置き。
        Assert.Equal(0.25f, reset.YawRate);
        Assert.Equal(-0.1f, reset.PitchRate);
        Assert.True(reset.Jump);
        Assert.Equal(0.75f, reset.Crouch);
        Assert.Equal(42L, reset.UnixNanos);
    }

    [Fact]
    public void ApplyReset_Look_ZeroesYawAndPitchOnly()
    {
        var input = LocomotionInput.Neutral with
        {
            YawRate = 0.5f,
            PitchRate = -0.2f,
            MoveForward = 1.0f,
            MoveUp = 1.0f,
            Velocity = 2.0f,
        };
        var reset = input.ApplyReset(LocomotionResetFlags.Look);

        Assert.Equal(0f, reset.YawRate);
        Assert.Equal(0f, reset.PitchRate);
        // Look reset は移動軸 / velocity に触れない。
        Assert.Equal(1.0f, reset.MoveForward);
        Assert.Equal(1.0f, reset.MoveUp);
        Assert.Equal(2.0f, reset.Velocity);
    }

    [Fact]
    public void ApplyReset_Crouch_ZeroesCrouchOnly()
    {
        var input = LocomotionInput.Neutral with
        {
            Crouch = 0.9f,
            MoveForward = 1.0f,
            MoveUp = 1.0f,
        };
        var reset = input.ApplyReset(LocomotionResetFlags.Crouch);

        Assert.Equal(0f, reset.Crouch);
        Assert.Equal(1.0f, reset.MoveForward);
        Assert.Equal(1.0f, reset.MoveUp);
    }

    [Fact]
    public void ApplyReset_Jump_ClearsJumpOnly()
    {
        var input = LocomotionInput.Neutral with { Jump = true, MoveUp = 1.0f };
        var reset = input.ApplyReset(LocomotionResetFlags.Jump);

        Assert.False(reset.Jump);
        Assert.Equal(1.0f, reset.MoveUp);
    }

    [Fact]
    public void ApplyReset_All_FromArbitrary_EqualsNeutralExceptUnixNanos()
    {
        var input = new LocomotionInput(
            MoveForward: 0.5f,
            MoveRight: 0.25f,
            MoveUp: -0.75f,
            YawRate: 0.25f,
            PitchRate: -0.1f,
            Jump: true,
            Velocity: 2.0f,
            Crouch: 0.75f,
            UnixNanos: 42L
        );
        var reset = input.ApplyReset(LocomotionResetFlags.All);

        // 全 field reset 後は UnixNanos を除いて Neutral と一致する。
        Assert.Equal(LocomotionInput.Neutral with { UnixNanos = 42L }, reset);
    }

    // --- LocomotionPartialInput.MergeInto: 部分更新セマンティクス ---

    [Fact]
    public void MergeInto_OverlaysOnlyPresentFields_AndKeepsAbsentBaseValues()
    {
        // base は前回 tick まで保持していた held-state を模す。
        var baseState = new LocomotionInput(
            MoveForward: 1.0f,
            MoveRight: 0.5f,
            MoveUp: -0.25f,
            YawRate: 0.1f,
            PitchRate: -0.1f,
            Jump: false,
            Velocity: 2.0f,
            Crouch: 0.3f,
            UnixNanos: 10L
        );
        // delta は YawRate のみ present (他は null = 未送信)。
        var delta = new LocomotionPartialInput(
            MoveForward: null,
            MoveRight: null,
            MoveUp: null,
            YawRate: 0.75f,
            PitchRate: null,
            Jump: null,
            Velocity: null,
            Crouch: null,
            UnixNanos: 99L
        );

        var merged = delta.MergeInto(baseState);

        // present field だけが上書きされる。
        Assert.Equal(0.75f, merged.YawRate);
        // UnixNanos は delta 側を採用する。
        Assert.Equal(99L, merged.UnixNanos);
        // absent (null) field は base の値をそのまま保持する。
        Assert.Equal(1.0f, merged.MoveForward);
        Assert.Equal(0.5f, merged.MoveRight);
        Assert.Equal(-0.25f, merged.MoveUp);
        Assert.Equal(-0.1f, merged.PitchRate);
        Assert.False(merged.Jump);
        Assert.Equal(2.0f, merged.Velocity);
        Assert.Equal(0.3f, merged.Crouch);
    }

    [Fact]
    public void MergeInto_AllPresent_ReplacesEveryField()
    {
        var delta = new LocomotionPartialInput(
            MoveForward: 0.1f,
            MoveRight: 0.2f,
            MoveUp: 0.3f,
            YawRate: 0.4f,
            PitchRate: 0.5f,
            Jump: true,
            Velocity: 3.0f,
            Crouch: 0.6f,
            UnixNanos: 7L
        );

        var merged = delta.MergeInto(LocomotionInput.Neutral);

        Assert.Equal(0.1f, merged.MoveForward);
        Assert.Equal(0.2f, merged.MoveRight);
        Assert.Equal(0.3f, merged.MoveUp);
        Assert.Equal(0.4f, merged.YawRate);
        Assert.Equal(0.5f, merged.PitchRate);
        Assert.True(merged.Jump);
        Assert.Equal(3.0f, merged.Velocity);
        Assert.Equal(0.6f, merged.Crouch);
        Assert.Equal(7L, merged.UnixNanos);
    }

    [Fact]
    public void MergeInto_VelocityNullOntoNeutral_KeepsUnitVelocity()
    {
        // velocity を一度も送らなければ単位元 1.0 を保持し続ける (= 停止しない)。
        // 単位元は Neutral base が担保し、null delta はそれを上書きしない。
        var delta = new LocomotionPartialInput(
            MoveForward: 1.0f,
            MoveRight: null,
            MoveUp: null,
            YawRate: null,
            PitchRate: null,
            Jump: null,
            Velocity: null,
            Crouch: null,
            UnixNanos: 1L
        );

        var merged = delta.MergeInto(LocomotionInput.Neutral);

        Assert.Equal(1.0f, merged.MoveForward);
        Assert.Equal(1.0f, merged.Velocity);
    }

    [Fact]
    public void MergeInto_SequentialDeltas_AccumulateHeldState()
    {
        // 連続 delta を畳み込むと、過去の present field が保持されつつ新しい
        // field が積み重なる (stateful repeater の held-state 累積)。
        var afterFirst = new LocomotionPartialInput(
            MoveForward: 1.0f,
            MoveRight: null,
            MoveUp: null,
            YawRate: null,
            PitchRate: null,
            Jump: null,
            Velocity: null,
            Crouch: null,
            UnixNanos: 1L
        ).MergeInto(LocomotionInput.Neutral);

        var afterSecond = new LocomotionPartialInput(
            MoveForward: null,
            MoveRight: null,
            MoveUp: null,
            YawRate: 0.5f,
            PitchRate: null,
            Jump: null,
            Velocity: null,
            Crouch: null,
            UnixNanos: 2L
        ).MergeInto(afterFirst);

        // 2 件目で MoveForward を送っていないが、前回値 1.0 が保持される。
        Assert.Equal(1.0f, afterSecond.MoveForward);
        Assert.Equal(0.5f, afterSecond.YawRate);
        Assert.Equal(2L, afterSecond.UnixNanos);
    }
}
