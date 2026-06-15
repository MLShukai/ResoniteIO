using Grpc.Core;
using ResoniteIO.Core.Tests.Common;
using ResoniteIO.Core.Tests.Common.Fakes;
using ResoniteIO.V1;
using Xunit;

namespace ResoniteIO.Core.Tests.Auth;

/// <summary>
/// <see cref="Core.Auth.AuthService"/> の Login / Logout / Status を実 Kestrel + UDS wire 越しに検証する。
/// </summary>
/// <remarks>
/// 仕様 (auth.proto + IAuthBridge 契約) を正典とする。とくに (1) login 引数 (credential / password /
/// totp の optional presence / remember_me) が bridge にそのまま届くこと、(2) 例外翻訳
/// (AuthFailed→Unauthenticated、AuthTotpRequired/AuthNotReady→FailedPrecondition、bridge==null→Unavailable)、
/// (3) <b>security pin</b>: 平文 password が失敗時の Status.Detail に決して漏れないこと、を核心として検証する。
/// </remarks>
public sealed class AuthServiceTests
{
    // ===================================================================
    //  Login — snapshot round-trip
    // ===================================================================

    [Fact]
    public async Task Login_returns_logged_in_AuthStatus_with_all_fields()
    {
        var bridge = new FakeAuthBridge();
        await using var host = await AuthServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Auth.AuthClient(channel);

        var status = await client.LoginAsync(
            new AuthLoginRequest { Credential = "tester", Password = "hunter2" }
        );

        Assert.True(status.LoggedIn);
        Assert.Equal("U-tester", status.UserId);
        Assert.Equal("Tester", status.UserName);
        Assert.Equal(1_700_000_000_000_000_000L, status.SessionExpiresUnixNanos);
    }

    // ===================================================================
    //  Login — argument forwarding to the bridge
    // ===================================================================

    [Fact]
    public async Task Login_forwards_credential_and_password_and_remember_me_to_bridge()
    {
        var bridge = new FakeAuthBridge();
        await using var host = await AuthServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Auth.AuthClient(channel);

        await client.LoginAsync(
            new AuthLoginRequest
            {
                Credential = "alice@example.com",
                Password = "s3cr3t",
                RememberMe = true,
            }
        );

        Assert.Equal("alice@example.com", bridge.LastCredential);
        Assert.Equal("s3cr3t", bridge.LastPassword);
        Assert.True(bridge.LastRememberMe);
    }

    [Fact]
    public async Task Login_with_remember_me_false_forwards_false_to_bridge()
    {
        // proto3 bool 既定は false。明示 false が bridge にそのまま届くこと。
        var bridge = new FakeAuthBridge();
        await using var host = await AuthServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Auth.AuthClient(channel);

        await client.LoginAsync(
            new AuthLoginRequest
            {
                Credential = "tester",
                Password = "pw",
                RememberMe = false,
            }
        );

        Assert.False(bridge.LastRememberMe);
    }

    // ===================================================================
    //  Login — totp optional presence (HasTotp -> null / value)
    // ===================================================================

    [Fact]
    public async Task Login_without_totp_passes_null_to_bridge()
    {
        // optional totp 非 set (HasTotp == false) は bridge に null として届く契約。
        var bridge = new FakeAuthBridge();
        await using var host = await AuthServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Auth.AuthClient(channel);

        await client.LoginAsync(new AuthLoginRequest { Credential = "tester", Password = "pw" });

        Assert.Contains("Login", bridge.Calls);
        Assert.Null(bridge.LastTotp);
    }

    [Fact]
    public async Task Login_with_totp_passes_value_to_bridge()
    {
        var bridge = new FakeAuthBridge();
        await using var host = await AuthServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Auth.AuthClient(channel);

        await client.LoginAsync(
            new AuthLoginRequest
            {
                Credential = "tester",
                Password = "pw",
                Totp = "123456",
            }
        );

        Assert.Equal("123456", bridge.LastTotp);
    }

    // ===================================================================
    //  Login — exception translation
    // ===================================================================

    [Fact]
    public async Task Login_translates_AuthFailedException_to_Unauthenticated()
    {
        var bridge = new FakeAuthBridge { ThrowFailed = true };
        await using var host = await AuthServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Auth.AuthClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.LoginAsync(new AuthLoginRequest { Credential = "tester", Password = "pw" })
        );

        Assert.Equal(StatusCode.Unauthenticated, ex.StatusCode);
    }

    [Fact]
    public async Task Login_translates_AuthTotpRequiredException_to_FailedPrecondition()
    {
        var bridge = new FakeAuthBridge { ThrowTotpRequired = true };
        await using var host = await AuthServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Auth.AuthClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.LoginAsync(new AuthLoginRequest { Credential = "tester", Password = "pw" })
        );

        Assert.Equal(StatusCode.FailedPrecondition, ex.StatusCode);
    }

    [Fact]
    public async Task Login_translates_AuthNotReadyException_to_FailedPrecondition()
    {
        var bridge = new FakeAuthBridge { ThrowNotReady = true };
        await using var host = await AuthServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Auth.AuthClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.LoginAsync(new AuthLoginRequest { Credential = "tester", Password = "pw" })
        );

        Assert.Equal(StatusCode.FailedPrecondition, ex.StatusCode);
    }

    // ===================================================================
    //  Security pin — password must never leak on the failure path
    // ===================================================================

    [Fact]
    public async Task Login_failure_does_not_leak_password_in_status_detail()
    {
        // SECURITY PIN: 平文 password が失敗時の RpcException Status.Detail に決して
        // 載らないこと。BridgeFault.Translate は ex.Message を Detail に転写するので、
        // Auth 例外の Message が generic (password を含まない) であることが前提。
        const string secret = "TOP_SECRET_PASSWORD_9f3a";
        var bridge = new FakeAuthBridge { ThrowFailed = true };
        await using var host = await AuthServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Auth.AuthClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.LoginAsync(
                new AuthLoginRequest { Credential = "tester", Password = secret }
            )
        );

        Assert.Equal(StatusCode.Unauthenticated, ex.StatusCode);
        Assert.DoesNotContain(secret, ex.Status.Detail);
        Assert.DoesNotContain(secret, ex.Message);
    }

    // ===================================================================
    //  Logout / Status — snapshot round-trip
    // ===================================================================

    [Fact]
    public async Task Logout_returns_logged_out_AuthStatus()
    {
        var bridge = new FakeAuthBridge();
        await using var host = await AuthServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Auth.AuthClient(channel);

        var status = await client.LogoutAsync(new AuthLogoutRequest());

        Assert.Contains("Logout", bridge.Calls);
        Assert.False(status.LoggedIn);
        Assert.Equal("", status.UserId);
        Assert.Equal("", status.UserName);
        Assert.Equal(0L, status.SessionExpiresUnixNanos);
    }

    [Fact]
    public async Task Status_returns_current_snapshot()
    {
        var bridge = new FakeAuthBridge();
        await using var host = await AuthServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Auth.AuthClient(channel);

        var status = await client.StatusAsync(new AuthStatusRequest());

        Assert.Contains("Status", bridge.Calls);
        Assert.True(status.LoggedIn);
        Assert.Equal("U-tester", status.UserId);
        Assert.Equal("Tester", status.UserName);
    }

    // ===================================================================
    //  bridge == null -> Unavailable (all three RPCs)
    // ===================================================================

    [Fact]
    public async Task Login_without_bridge_returns_Unavailable()
    {
        await using var host = await AuthServiceHost.StartAsync(bridge: null);
        using var channel = host.CreateChannel();
        var client = new V1.Auth.AuthClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.LoginAsync(new AuthLoginRequest { Credential = "tester", Password = "pw" })
        );

        Assert.Equal(StatusCode.Unavailable, ex.StatusCode);
    }

    [Fact]
    public async Task Logout_without_bridge_returns_Unavailable()
    {
        await using var host = await AuthServiceHost.StartAsync(bridge: null);
        using var channel = host.CreateChannel();
        var client = new V1.Auth.AuthClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.LogoutAsync(new AuthLogoutRequest())
        );

        Assert.Equal(StatusCode.Unavailable, ex.StatusCode);
    }

    [Fact]
    public async Task Status_without_bridge_returns_Unavailable()
    {
        await using var host = await AuthServiceHost.StartAsync(bridge: null);
        using var channel = host.CreateChannel();
        var client = new V1.Auth.AuthClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.StatusAsync(new AuthStatusRequest())
        );

        Assert.Equal(StatusCode.Unavailable, ex.StatusCode);
    }
}
