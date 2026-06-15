using Grpc.Core;
using ResoniteIO.Core.Logging;
using ResoniteIO.Core.Rpc;

namespace ResoniteIO.Core.Auth;

/// <summary><c>resonite_io.v1.Auth</c> サービスの Core 実装。</summary>
/// <remarks>
/// <see cref="IAuthBridge"/> は optional DI: null なら <c>Unavailable</c> を返し、
/// Core 単体テストや auth 非対応 engine 構成も成立させる (SessionService と同 pattern)。
/// 各 RPC は engine を知らず、proto を Core POCO に変換して bridge に渡すだけ。例外翻訳は
/// <see cref="AuthTotpRequiredException"/> / <see cref="AuthNotReadyException"/> →
/// <c>FailedPrecondition</c>、<see cref="AuthFailedException"/> → <c>Unauthenticated</c>、
/// その他 → <c>Internal</c>。
/// セキュリティ上、<c>Login</c> override は request (password を含む) を一切ログに出さない。
/// </remarks>
public sealed class AuthService : V1.Auth.AuthBase
{
    private readonly IAuthBridge? _bridge;
    private readonly ILogSink _log;

    public AuthService(ILogSink log, IAuthBridge? bridge = null)
    {
        _log = log;
        _bridge = bridge;
    }

    public override async Task<V1.AuthStatus> Login(
        V1.AuthLoginRequest request,
        ServerCallContext context
    )
    {
        // セキュリティ: request は平文 password を含むため一切ログに出さない。
        var bridge = RequireBridge("Login");
        var totp = request.HasTotp ? request.Totp : null;
        var snapshot = await InvokeBridge(
                "Login",
                ct =>
                    bridge.LoginAsync(
                        request.Credential,
                        request.Password,
                        totp,
                        request.RememberMe,
                        ct
                    ),
                context.CancellationToken
            )
            .ConfigureAwait(false);
        return ToProto(snapshot);
    }

    public override async Task<V1.AuthStatus> Logout(
        V1.AuthLogoutRequest request,
        ServerCallContext context
    )
    {
        var bridge = RequireBridge("Logout");
        var snapshot = await InvokeBridge(
                "Logout",
                ct => bridge.LogoutAsync(ct),
                context.CancellationToken
            )
            .ConfigureAwait(false);
        return ToProto(snapshot);
    }

    public override async Task<V1.AuthStatus> Status(
        V1.AuthStatusRequest request,
        ServerCallContext context
    )
    {
        var bridge = RequireBridge("Status");
        var snapshot = await InvokeBridge(
                "Status",
                ct => bridge.GetStatusAsync(ct),
                context.CancellationToken
            )
            .ConfigureAwait(false);
        return ToProto(snapshot);
    }

    private IAuthBridge RequireBridge(string rpc) =>
        BridgeGuard.Require(_bridge, _log, "Auth", "IAuthBridge", rpc);

    /// <summary>全 RPC 共通の例外翻訳 (三 RPC とも <see cref="AuthStatusSnapshot"/> を返す)。</summary>
    private Task<T> InvokeBridge<T>(
        string rpc,
        Func<CancellationToken, Task<T>> call,
        CancellationToken ct
    ) => BridgeFault.InvokeAsync(_log, "Auth", rpc, call, ct, ex => Translate(rpc, ex));

    private RpcException? Translate(string rpc, Exception ex)
    {
        switch (ex)
        {
            case AuthTotpRequiredException totp:
                return BridgeFault.Translate(
                    _log,
                    "Auth",
                    rpc,
                    StatusCode.FailedPrecondition,
                    "totp required",
                    totp
                );
            case AuthNotReadyException notReady:
                return BridgeFault.Translate(
                    _log,
                    "Auth",
                    rpc,
                    StatusCode.FailedPrecondition,
                    "bridge not ready",
                    notReady
                );
            case AuthFailedException failed:
                return BridgeFault.Translate(
                    _log,
                    "Auth",
                    rpc,
                    StatusCode.Unauthenticated,
                    "auth failed",
                    failed
                );
            default:
                return null;
        }
    }

    private static V1.AuthStatus ToProto(AuthStatusSnapshot snapshot) =>
        new()
        {
            LoggedIn = snapshot.LoggedIn,
            UserId = snapshot.UserId,
            UserName = snapshot.UserName,
            SessionExpiresUnixNanos = snapshot.SessionExpiresUnixNanos,
        };
}
