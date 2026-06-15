namespace ResoniteIO.Core.Auth;

/// <summary>
/// 現在の Resonite cloud ログイン状態の snapshot (proto <c>AuthStatus</c> から独立した Core 層 POCO)。
/// </summary>
/// <remarks>
/// <paramref name="LoggedIn"/> が false のとき他の field は既定値 (空文字 / 0) になる。
/// <paramref name="SessionExpiresUnixNanos"/> は不明 / 無期限のとき 0。秘匿情報 (password /
/// token) は一切含めない。
/// </remarks>
public sealed record AuthStatusSnapshot(
    bool LoggedIn,
    string UserId,
    string UserName,
    long SessionExpiresUnixNanos
);

/// <summary>
/// Mod 側 (FrooxEngine) が実装し DI で注入する Resonite cloud 認証 (login / logout / status) の抽象。
/// </summary>
/// <remarks>
/// engine の cloud session を直接操作する。秘密 (password / totp) は呼び出し時のみ受け取り、
/// 結果や例外には残さない。<c>rememberMe</c> の永続化は engine に委譲し、Core / Python 側は
/// 資格情報をディスクに保存しない。
/// </remarks>
public interface IAuthBridge
{
    /// <summary>
    /// <paramref name="credential"/> / <paramref name="password"/> (+ optional
    /// <paramref name="totp"/>) で Resonite cloud にログインし、更新後の状態 snapshot を返す。
    /// </summary>
    /// <param name="credential">ユーザー名 / メール / user id 等のログイン識別子。</param>
    /// <param name="password">平文パスワード。ログ・例外・戻り値に残してはならない。</param>
    /// <param name="totp">2 要素認証コード。不要なら <c>null</c>。</param>
    /// <param name="rememberMe">永続ログイン (engine 側に委譲) を要求するか。</param>
    /// <exception cref="AuthNotReadyException">engine がまだログインを受け付けられない状態。</exception>
    /// <exception cref="AuthTotpRequiredException">2 要素認証コードが必要 (未提供 / 不正)。</exception>
    /// <exception cref="AuthFailedException">資格情報が不正、その他ログイン失敗。</exception>
    Task<AuthStatusSnapshot> LoginAsync(
        string credential,
        string password,
        string? totp,
        bool rememberMe,
        CancellationToken ct
    );

    /// <summary>現在の cloud session をログアウトし、更新後の状態 snapshot を返す。</summary>
    /// <exception cref="AuthNotReadyException">engine 未準備。</exception>
    /// <exception cref="AuthFailedException">ログアウト失敗。</exception>
    Task<AuthStatusSnapshot> LogoutAsync(CancellationToken ct);

    /// <summary>現在の cloud ログイン状態 snapshot を返す (副作用なし)。</summary>
    /// <exception cref="AuthNotReadyException">engine 未準備。</exception>
    Task<AuthStatusSnapshot> GetStatusAsync(CancellationToken ct);
}

/// <summary>
/// Bridge が一時的に認証を処理できない状態 (engine 未準備等)。
/// Service 層は <c>FailedPrecondition</c> に翻訳するので Client は時間を置いて retry できる。
/// </summary>
/// <remarks>メッセージに秘密 (password / token) を含めてはならない (Status.Detail に転写される)。</remarks>
public sealed class AuthNotReadyException : Exception
{
    public AuthNotReadyException(string message)
        : base(message) { }

    public AuthNotReadyException(string message, Exception? innerException)
        : base(message, innerException) { }
}

/// <summary>
/// 資格情報が不正、その他ログイン / ログアウト失敗。Service 層は <c>Unauthenticated</c> に翻訳する。
/// </summary>
/// <remarks>
/// メッセージは generic に保つ (HTTP status のみ等)。password / credential を含めてはならない
/// (Status.Detail に転写されログにも出るため)。
/// </remarks>
public sealed class AuthFailedException : Exception
{
    public AuthFailedException(string message)
        : base(message) { }

    public AuthFailedException(string message, Exception? innerException)
        : base(message, innerException) { }
}

/// <summary>
/// 2 要素認証 (TOTP) コードが必要 / 不正。Service 層は <c>FailedPrecondition</c> に翻訳する
/// (Client は totp を付けて retry できる)。
/// </summary>
/// <remarks>メッセージに秘密を含めてはならない (Status.Detail に転写される)。</remarks>
public sealed class AuthTotpRequiredException : Exception
{
    public AuthTotpRequiredException(string message)
        : base(message) { }

    public AuthTotpRequiredException(string message, Exception? innerException)
        : base(message, innerException) { }
}
