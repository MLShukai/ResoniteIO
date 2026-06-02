using ResoniteIO.Core.Locomotion;
using Xunit;

namespace ResoniteIO.Core.Tests.Locomotion;

/// <summary>
/// <see cref="LocomotionInput.Neutral"/> と <see cref="LocomotionInput.ApplyReset"/>
/// の単体テスト。Bridge 実装と FakeLocomotionBridge が同じ規約を共有することの担保。
/// 移動 3 軸 (MoveForward / MoveRight / MoveUp) の方向ベース名と、視点独立の絶対
/// ワールド上下軸 MoveUp が Move reset に巻き込まれることを押さえる。
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
}
