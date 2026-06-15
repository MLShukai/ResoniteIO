using System;
using System.Threading;
using System.Threading.Tasks;
using FrooxEngine;
using ResoniteIO.Core.Auth;
using ResoniteIO.Core.Logging;
using SkyFrost.Base;

namespace ResoniteIO.Bridge;

/// <summary>
/// Resonite cloud のログイン / ログアウト / セッション状態取得を <see cref="IAuthBridge"/> として
/// 露出する実装。<see cref="Engine.Cloud"/> の <see cref="SessionManager"/> を直接叩く。
/// </summary>
/// <remarks>
/// <para>
/// Login / Logout / status read はいずれも engine update tick に縛られない (Cloud REST 呼び出しと
/// lock 保護された property read のみ) ため、engine-thread dispatch は不要。
/// <c>await ... .ConfigureAwait(false)</c> で Cloud を直接呼ぶ
/// (<see cref="World.RunSynchronously"/> / <see cref="EngineDispatch"/> は使わない)。
/// </para>
/// <para>
/// 例外メッセージにはパスワードや credential を一切含めない。ログにも出さない
/// (server 由来の HTTP status / content のみ、これらは secret を含まない)。
/// </para>
/// </remarks>
internal sealed class FrooxEngineAuthBridge : IAuthBridge
{
    private readonly Engine _engine;
    private readonly ILogSink _log;

    public FrooxEngineAuthBridge(Engine engine, ILogSink log)
    {
        ArgumentNullException.ThrowIfNull(engine);
        ArgumentNullException.ThrowIfNull(log);
        _engine = engine;
        _log = log;
    }

    /// <inheritdoc/>
    public async Task<AuthStatusSnapshot> LoginAsync(
        string credential,
        string password,
        string? totp,
        bool rememberMe,
        CancellationToken ct
    )
    {
        ct.ThrowIfCancellationRequested();

        var session = _engine.Cloud?.Session;
        if (session is null)
        {
            throw new AuthNotReadyException("Cloud session manager is not ready.");
        }

        CloudResult<UserSessionResult<UserSession>> result;
        try
        {
            result = await session
                .Login(
                    credential,
                    new PasswordLogin(password),
                    _engine.LocalDB.SecretMachineID,
                    rememberMe,
                    totp
                )
                .ConfigureAwait(false);
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (Exception)
        {
            // engine の生例外は request body (平文 password) を含み得るため、メッセージにも
            // inner exception にも一切載せず generic な AuthFailedException に畳む
            // (inner を chain すると BridgeFault の {ex} ToString 経路で漏れ得るため null のまま)。
            throw new AuthFailedException("Login failed.");
        }

        if (result.IsOK)
        {
            return ReadStatus();
        }

        if (result.Content == "TOTP")
        {
            if (string.IsNullOrEmpty(totp))
            {
                throw new AuthTotpRequiredException("Two-factor authentication code is required.");
            }
            throw new AuthFailedException("Two-factor authentication code was rejected.");
        }

        // server 由来のメッセージ。パスワードを含まないためログ出力は安全。
        _log.LogInfo($"Auth.Login failed: HTTP {(int)result.State}: {result.Content}");
        // 例外メッセージは generic に保つ (password / credential を含めない)。
        throw new AuthFailedException($"Login failed (HTTP {(int)result.State}).");
    }

    /// <inheritdoc/>
    public async Task<AuthStatusSnapshot> LogoutAsync(CancellationToken ct)
    {
        ct.ThrowIfCancellationRequested();

        var session = _engine.Cloud?.Session;
        if (session is null)
        {
            throw new AuthNotReadyException("Cloud session manager is not ready.");
        }

        await session.Logout(isManual: true).ConfigureAwait(false);
        return ReadStatus();
    }

    /// <inheritdoc/>
    public Task<AuthStatusSnapshot> GetStatusAsync(CancellationToken ct)
    {
        ct.ThrowIfCancellationRequested();
        return Task.FromResult(ReadStatus());
    }

    /// <summary>
    /// 現在の cloud session から <see cref="AuthStatusSnapshot"/> を読む。未ログイン時は
    /// logged-in=false の空 snapshot を返す。パスワード / credential は一切触れない。
    /// </summary>
    private AuthStatusSnapshot ReadStatus()
    {
        var cloud = _engine.Cloud;
        var session = cloud?.Session?.CurrentSession;
        if (session is null)
        {
            return new AuthStatusSnapshot(false, string.Empty, string.Empty, 0L);
        }

        var userId = cloud!.CurrentUserID ?? session.UserId ?? string.Empty;
        var userName = cloud.CurrentUsername ?? string.Empty;

        // SessionExpire の DateTime→unix-nanos は兄弟 bridge (Inventory / World) と同形の
        // 100ns tick ベース変換に揃える。負値クランプにより default(DateTime) / pre-1970 は
        // 0 になる (proto 契約: 期限不明なら 0)。
        var expires = ToUnixNanos(session.SessionExpire);

        return new AuthStatusSnapshot(true, userId, userName, expires);
    }

    /// <summary>
    /// <see cref="DateTime"/> を unix epoch からの nanos に変換する (兄弟 bridge と同形の
    /// 100ns tick ベース)。default(DateTime) / pre-1970 など epoch 以前は 0 にクランプする。
    /// </summary>
    private static long ToUnixNanos(DateTime dt)
    {
        var utc =
            dt.Kind == DateTimeKind.Unspecified
                ? DateTime.SpecifyKind(dt, DateTimeKind.Utc)
                : dt.ToUniversalTime();
        var ticks = utc.Ticks - DateTime.UnixEpoch.Ticks;
        return ticks <= 0 ? 0L : ticks * 100L;
    }
}
