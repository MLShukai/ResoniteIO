using ResoniteIO.Core.Locomotion;
using Xunit;

namespace ResoniteIO.Core.Tests.Locomotion;

/// <summary>
/// <see cref="LocomotionInput.Neutral"/> と <see cref="LocomotionInput.ApplyReset"/>
/// の単体テスト。Bridge 実装と FakeLocomotionBridge が同じ規約を共有することの担保。
/// </summary>
public sealed class LocomotionInputTests
{
    [Fact]
    public void Neutral_HasVelocityOne_AndZeroOrFalseForRest()
    {
        var n = LocomotionInput.Neutral;
        Assert.Equal(0f, n.MoveX);
        Assert.Equal(0f, n.MoveY);
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
            MoveX: 0.5f,
            MoveY: 1.0f,
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
    public void ApplyReset_Move_ZeroesMoveAndRestoresUnitVelocity()
    {
        var input = new LocomotionInput(
            MoveX: 0.5f,
            MoveY: 1.0f,
            YawRate: 0.25f,
            PitchRate: -0.1f,
            Jump: true,
            Velocity: 2.0f,
            Crouch: 0.75f,
            UnixNanos: 42L
        );
        var reset = input.ApplyReset(LocomotionResetFlags.Move);

        Assert.Equal(0f, reset.MoveX);
        Assert.Equal(0f, reset.MoveY);
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
            MoveY = 1.0f,
            Velocity = 2.0f,
        };
        var reset = input.ApplyReset(LocomotionResetFlags.Look);

        Assert.Equal(0f, reset.YawRate);
        Assert.Equal(0f, reset.PitchRate);
        Assert.Equal(1.0f, reset.MoveY);
        Assert.Equal(2.0f, reset.Velocity);
    }

    [Fact]
    public void ApplyReset_Crouch_ZeroesCrouchOnly()
    {
        var input = LocomotionInput.Neutral with { Crouch = 0.9f, MoveY = 1.0f };
        var reset = input.ApplyReset(LocomotionResetFlags.Crouch);

        Assert.Equal(0f, reset.Crouch);
        Assert.Equal(1.0f, reset.MoveY);
    }

    [Fact]
    public void ApplyReset_Jump_ClearsJumpOnly()
    {
        var input = LocomotionInput.Neutral with { Jump = true, MoveY = 1.0f };
        var reset = input.ApplyReset(LocomotionResetFlags.Jump);

        Assert.False(reset.Jump);
        Assert.Equal(1.0f, reset.MoveY);
    }

    [Fact]
    public void ApplyReset_All_FromArbitrary_EqualsNeutralExceptUnixNanos()
    {
        var input = new LocomotionInput(
            MoveX: 0.5f,
            MoveY: 1.0f,
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
