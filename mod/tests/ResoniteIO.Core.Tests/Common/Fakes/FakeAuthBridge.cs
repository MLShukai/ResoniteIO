using ResoniteIO.Core.Auth;

namespace ResoniteIO.Core.Tests.Common.Fakes;

/// <summary>
/// テスト用 <see cref="IAuthBridge"/>。in-memory の logged-in / logged-out snapshot を保持し、
/// Service が proto から組み立てた login 引数 (credential / password / totp / remember_me) を
/// そのまま観測できるようにする (<see cref="FakeSessionBridge"/> と同 pattern)。
/// </summary>
/// <remarks>
/// <para>
/// <see cref="LastCredential"/> / <see cref="LastPassword"/> / <see cref="LastTotp"/> /
/// <see cref="LastRememberMe"/> に最後の login 引数を控えるので、Service の proto→引数 変換
/// (とくに totp の optional presence → null) を end-to-end で検証できる。<see cref="Calls"/> には
/// RPC 名を時系列で記録する。
/// </para>
/// <para>
/// 例外翻訳テスト用に <see cref="ThrowNotReady"/> / <see cref="ThrowFailed"/> /
/// <see cref="ThrowTotpRequired"/> のいずれかを立てると、以降の呼び出しで対応する例外を投げる。
/// 例外 Message は本番同様 password を含まない汎用文言にしてある (security pin の対象)。
/// </para>
/// </remarks>
internal sealed class FakeAuthBridge : IAuthBridge
{
    private readonly AuthStatusSnapshot _loggedIn = new(
        LoggedIn: true,
        UserId: "U-tester",
        UserName: "Tester",
        SessionExpiresUnixNanos: 1_700_000_000_000_000_000L
    );

    private readonly AuthStatusSnapshot _loggedOut = new(
        LoggedIn: false,
        UserId: "",
        UserName: "",
        SessionExpiresUnixNanos: 0L
    );

    public List<string> Calls { get; } = new();

    /// <summary>最後に <see cref="LoginAsync"/> に渡された credential。未呼び出しなら null。</summary>
    public string? LastCredential { get; private set; }

    /// <summary>最後に <see cref="LoginAsync"/> に渡された password。未呼び出しなら null。</summary>
    public string? LastPassword { get; private set; }

    /// <summary>最後に <see cref="LoginAsync"/> に渡された totp。未指定なら null。</summary>
    public string? LastTotp { get; private set; }

    /// <summary>最後に <see cref="LoginAsync"/> に渡された remember_me。未呼び出しなら null。</summary>
    public bool? LastRememberMe { get; private set; }

    public bool ThrowNotReady { get; set; }
    public bool ThrowFailed { get; set; }
    public bool ThrowTotpRequired { get; set; }

    public Task<AuthStatusSnapshot> LoginAsync(
        string credential,
        string password,
        string? totp,
        bool rememberMe,
        CancellationToken ct
    )
    {
        Calls.Add("Login");
        LastCredential = credential;
        LastPassword = password;
        LastTotp = totp;
        LastRememberMe = rememberMe;
        TripIfArmed();
        return Task.FromResult(_loggedIn);
    }

    public Task<AuthStatusSnapshot> LogoutAsync(CancellationToken ct)
    {
        Calls.Add("Logout");
        TripIfArmed();
        return Task.FromResult(_loggedOut);
    }

    public Task<AuthStatusSnapshot> GetStatusAsync(CancellationToken ct)
    {
        Calls.Add("Status");
        TripIfArmed();
        return Task.FromResult(_loggedIn);
    }

    private void TripIfArmed()
    {
        // 例外 Message は generic only (password / credential を絶対に含めない)。
        if (ThrowNotReady)
        {
            throw new AuthNotReadyException("engine cloud session not ready");
        }
        if (ThrowFailed)
        {
            throw new AuthFailedException("login failed (HTTP 401)");
        }
        if (ThrowTotpRequired)
        {
            throw new AuthTotpRequiredException("two-factor code required");
        }
    }
}
