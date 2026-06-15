using Grpc.Core;
using ResoniteIO.Core.Logging;
using ResoniteIO.Core.Rpc;

namespace ResoniteIO.Core.Session;

/// <summary><c>resonite_io.v1.Session</c> サービスの Core 実装。</summary>
/// <remarks>
/// <see cref="ISessionBridge"/> は optional DI: null なら <c>Unavailable</c> を返し、
/// Core 単体テストや session 非対応 engine 構成も成立させる (InventoryService と同 pattern)。
/// 各 RPC は engine を知らず、proto を Core POCO に変換して bridge に渡すだけ。例外翻訳は
/// <see cref="SessionNotReadyException"/> / <see cref="SessionAmbiguousUserException"/> /
/// <see cref="SessionResoniteLinkException"/> → <c>FailedPrecondition</c>、
/// <see cref="SessionUserNotFoundException"/> /
/// <see cref="SessionRoleNotFoundException"/> → <c>NotFound</c>、
/// <see cref="SessionPermissionDeniedException"/> → <c>PermissionDenied</c>、
/// <see cref="ArgumentException"/> (max_users 範囲外) → <c>InvalidArgument</c>、その他 → <c>Internal</c>。
/// </remarks>
public sealed class SessionService : V1.Session.SessionBase
{
    private readonly ISessionBridge? _bridge;
    private readonly ILogSink _log;

    public SessionService(ILogSink log, ISessionBridge? bridge = null)
    {
        _log = log;
        _bridge = bridge;
    }

    public override async Task<V1.SessionSettings> GetSettings(
        V1.GetSettingsRequest request,
        ServerCallContext context
    )
    {
        var bridge = RequireBridge("GetSettings");
        var snapshot = await InvokeBridge(
                "GetSettings",
                ct => bridge.GetSettingsAsync(ct),
                context.CancellationToken
            )
            .ConfigureAwait(false);
        return ToProto(snapshot);
    }

    public override async Task<V1.ApplySettingsResponse> ApplySettings(
        V1.SessionSettingsPatch request,
        ServerCallContext context
    )
    {
        var bridge = RequireBridge("ApplySettings");

        await InvokeBridge(
                "ApplySettings",
                async ct =>
                {
                    // ToPatch (max_users 検証を含む) は delegate 内で呼ぶ。範囲外の
                    // ArgumentException を BridgeFault.InvokeAsync の translate スコープに
                    // 入れ InvalidArgument に確実に翻訳するため (検証失敗時は bridge を呼ばない)。
                    var patch = ToPatch(request);
                    await bridge.ApplySettingsAsync(patch, ct).ConfigureAwait(false);
                    return true;
                },
                context.CancellationToken
            )
            .ConfigureAwait(false);

        // Apply の Empty 応答契約は session.proto / ISessionBridge.ApplySettingsAsync XML 参照。
        return new V1.ApplySettingsResponse();
    }

    public override async Task<V1.ListUsersResponse> ListUsers(
        V1.ListUsersRequest request,
        ServerCallContext context
    )
    {
        var bridge = RequireBridge("ListUsers");
        var users = await InvokeBridge(
                "ListUsers",
                ct => bridge.ListUsersAsync(ct),
                context.CancellationToken
            )
            .ConfigureAwait(false);

        var response = new V1.ListUsersResponse();
        foreach (var user in users)
        {
            response.Users.Add(ToProto(user));
        }

        return response;
    }

    public override async Task<V1.KickUserResponse> KickUser(
        V1.KickUserRequest request,
        ServerCallContext context
    )
    {
        var bridge = RequireBridge("KickUser");
        var target = ToTarget(request.Target);
        var kind = ToKickKind(request.Kind);

        await InvokeBridge(
                "KickUser",
                async ct =>
                {
                    await bridge.KickUserAsync(target, kind, ct).ConfigureAwait(false);
                    return true;
                },
                context.CancellationToken
            )
            .ConfigureAwait(false);

        return new V1.KickUserResponse();
    }

    public override async Task<V1.BanUserResponse> BanUser(
        V1.BanUserRequest request,
        ServerCallContext context
    )
    {
        var bridge = RequireBridge("BanUser");
        var target = ToTarget(request.Target);

        await InvokeBridge(
                "BanUser",
                async ct =>
                {
                    await bridge.BanUserAsync(target, ct).ConfigureAwait(false);
                    return true;
                },
                context.CancellationToken
            )
            .ConfigureAwait(false);

        return new V1.BanUserResponse();
    }

    public override async Task<V1.SilenceUserResponse> SilenceUser(
        V1.SilenceUserRequest request,
        ServerCallContext context
    )
    {
        var bridge = RequireBridge("SilenceUser");
        var target = ToTarget(request.Target);
        var user = await InvokeBridge(
                "SilenceUser",
                ct => bridge.SilenceUserAsync(target, request.Silenced, ct),
                context.CancellationToken
            )
            .ConfigureAwait(false);

        return new V1.SilenceUserResponse { User = ToProto(user) };
    }

    public override async Task<V1.RespawnUserResponse> RespawnUser(
        V1.RespawnUserRequest request,
        ServerCallContext context
    )
    {
        var bridge = RequireBridge("RespawnUser");
        var target = ToTarget(request.Target);

        await InvokeBridge(
                "RespawnUser",
                async ct =>
                {
                    await bridge.RespawnUserAsync(target, ct).ConfigureAwait(false);
                    return true;
                },
                context.CancellationToken
            )
            .ConfigureAwait(false);

        return new V1.RespawnUserResponse();
    }

    public override async Task<V1.SetUserRoleResponse> SetUserRole(
        V1.SetUserRoleRequest request,
        ServerCallContext context
    )
    {
        var bridge = RequireBridge("SetUserRole");
        var target = ToTarget(request.Target);
        var user = await InvokeBridge(
                "SetUserRole",
                ct => bridge.SetUserRoleAsync(target, request.RoleName, ct),
                context.CancellationToken
            )
            .ConfigureAwait(false);

        return new V1.SetUserRoleResponse { User = ToProto(user) };
    }

    public override async Task<V1.ListRolesResponse> ListRoles(
        V1.ListRolesRequest request,
        ServerCallContext context
    )
    {
        var bridge = RequireBridge("ListRoles");
        var snapshot = await InvokeBridge(
                "ListRoles",
                ct => bridge.ListRolesAsync(ct),
                context.CancellationToken
            )
            .ConfigureAwait(false);

        return ToProto(snapshot);
    }

    public override async Task<V1.GetUserRoleOverridesResponse> GetUserRoleOverrides(
        V1.GetUserRoleOverridesRequest request,
        ServerCallContext context
    )
    {
        var bridge = RequireBridge("GetUserRoleOverrides");
        var overrides = await InvokeBridge(
                "GetUserRoleOverrides",
                ct => bridge.GetUserRoleOverridesAsync(ct),
                context.CancellationToken
            )
            .ConfigureAwait(false);

        var response = new V1.GetUserRoleOverridesResponse();
        foreach (var entry in overrides)
        {
            response.Overrides.Add(
                new V1.UserRoleOverride { UserId = entry.UserId, RoleName = entry.RoleName }
            );
        }

        return response;
    }

    private ISessionBridge RequireBridge(string rpc) =>
        BridgeGuard.Require(_bridge, _log, "Session", "ISessionBridge", rpc);

    /// <summary>
    /// 全 RPC 共通の例外翻訳。Session は複数の戻り型を返すため generic 化 (InventoryService と同形)。
    /// </summary>
    private Task<T> InvokeBridge<T>(
        string rpc,
        Func<CancellationToken, Task<T>> call,
        CancellationToken ct
    ) => BridgeFault.InvokeAsync(_log, "Session", rpc, call, ct, ex => Translate(rpc, ex));

    private RpcException? Translate(string rpc, Exception ex)
    {
        switch (ex)
        {
            case SessionNotReadyException notReady:
                return BridgeFault.Translate(
                    _log,
                    "Session",
                    rpc,
                    StatusCode.FailedPrecondition,
                    "bridge not ready",
                    notReady
                );
            case SessionAmbiguousUserException ambiguous:
                return BridgeFault.Translate(
                    _log,
                    "Session",
                    rpc,
                    StatusCode.FailedPrecondition,
                    "ambiguous user",
                    ambiguous
                );
            case SessionUserNotFoundException userNotFound:
                return BridgeFault.Translate(
                    _log,
                    "Session",
                    rpc,
                    StatusCode.NotFound,
                    "user not found",
                    userNotFound
                );
            case SessionRoleNotFoundException roleNotFound:
                return BridgeFault.Translate(
                    _log,
                    "Session",
                    rpc,
                    StatusCode.NotFound,
                    "role not found",
                    roleNotFound
                );
            case SessionResoniteLinkException resoniteLink:
                return BridgeFault.Translate(
                    _log,
                    "Session",
                    rpc,
                    StatusCode.FailedPrecondition,
                    "resonite link",
                    resoniteLink
                );
            case SessionPermissionDeniedException denied:
                return BridgeFault.Translate(
                    _log,
                    "Session",
                    rpc,
                    StatusCode.PermissionDenied,
                    "permission denied",
                    denied
                );
            case ArgumentException invalid:
                return BridgeFault.Translate(
                    _log,
                    "Session",
                    rpc,
                    StatusCode.InvalidArgument,
                    "invalid argument",
                    invalid
                );
            default:
                return null;
        }
    }

    /// <summary>
    /// proto patch を Core POCO に変換する。<c>optional</c> field は <c>HasXxx</c> で presence を
    /// 判定し未指定なら <c>null</c>、<c>access_level</c> は <c>Unspecified</c>→null に正規化、
    /// <c>tags</c> は <c>replace_tags</c> gate で全置換 / 不変を切り替える。
    /// </summary>
    /// <exception cref="RpcException"><c>max_users</c> が 1..255 の範囲外なら <c>InvalidArgument</c>。</exception>
    private static SessionSettingsPatchSnapshot ToPatch(V1.SessionSettingsPatch request)
    {
        int? maxUsers = request.HasMaxUsers ? request.MaxUsers : null;
        if (maxUsers is { } value && (value < 1 || value > 255))
        {
            throw new ArgumentException($"max_users must be in [1, 255], got {value}.");
        }

        var accessLevel =
            request.AccessLevel == V1.SessionAccessLevel.Unspecified
                ? (SessionAccessLevel?)null
                : ToCoreAccessLevel(request.AccessLevel);

        var tags = request.ReplaceTags ? request.Tags.ToList() : (IReadOnlyList<string>?)null;

        return new SessionSettingsPatchSnapshot
        {
            WorldName = request.HasWorldName ? request.WorldName : null,
            WorldDescription = request.HasWorldDescription ? request.WorldDescription : null,
            MaxUsers = maxUsers,
            AccessLevel = accessLevel,
            HideFromListing = request.HasHideFromListing ? request.HideFromListing : null,
            MobileFriendly = request.HasMobileFriendly ? request.MobileFriendly : null,
            AwayKickEnabled = request.HasAwayKickEnabled ? request.AwayKickEnabled : null,
            AwayKickMinutes = request.HasAwayKickMinutes ? request.AwayKickMinutes : null,
            AutoSaveEnabled = request.HasAutoSaveEnabled ? request.AutoSaveEnabled : null,
            AutoSaveIntervalMinutes = request.HasAutoSaveIntervalMinutes
                ? request.AutoSaveIntervalMinutes
                : null,
            AutoCleanupEnabled = request.HasAutoCleanupEnabled ? request.AutoCleanupEnabled : null,
            AutoCleanupIntervalSeconds = request.HasAutoCleanupIntervalSeconds
                ? request.AutoCleanupIntervalSeconds
                : null,
            Tags = tags,
            ResoniteLinkEnabled = request.HasResoniteLinkEnabled
                ? request.ResoniteLinkEnabled
                : (bool?)null,
        };
    }

    private static UserTargetSpec ToTarget(V1.UserTarget? target) =>
        target is null
            ? new UserTargetSpec(string.Empty, string.Empty, false)
            : new UserTargetSpec(target.UserId, target.UserName, target.Local);

    private static V1.SessionSettings ToProto(SessionSettingsSnapshot snapshot)
    {
        var settings = new V1.SessionSettings
        {
            WorldName = snapshot.WorldName,
            WorldDescription = snapshot.WorldDescription,
            MaxUsers = snapshot.MaxUsers,
            AccessLevel = ToProtoAccessLevel(snapshot.AccessLevel),
            HideFromListing = snapshot.HideFromListing,
            MobileFriendly = snapshot.MobileFriendly,
            AwayKickEnabled = snapshot.AwayKickEnabled,
            AwayKickMinutes = snapshot.AwayKickMinutes,
            AutoSaveEnabled = snapshot.AutoSaveEnabled,
            AutoSaveIntervalMinutes = snapshot.AutoSaveIntervalMinutes,
            AutoCleanupEnabled = snapshot.AutoCleanupEnabled,
            AutoCleanupIntervalSeconds = snapshot.AutoCleanupIntervalSeconds,
            SessionId = snapshot.SessionId,
            IsHost = snapshot.IsHost,
            ResoniteLinkEnabled = snapshot.ResoniteLinkEnabled,
            ResoniteLinkPort = snapshot.ResoniteLinkPort,
        };
        settings.Tags.AddRange(snapshot.Tags);
        return settings;
    }

    private static V1.SessionUser ToProto(SessionUserSnapshot user) =>
        new()
        {
            UserId = user.UserId,
            UserName = user.UserName,
            IsHost = user.IsHost,
            IsLocalUser = user.IsLocalUser,
            IsPresentInWorld = user.IsPresentInWorld,
            IsSilenced = user.IsSilenced,
            LocalVolume = user.LocalVolume,
            RoleName = user.RoleName,
            Platform = user.Platform,
            HeadDevice = user.HeadDevice,
        };

    private static V1.ListRolesResponse ToProto(SessionRolesSnapshot snapshot)
    {
        var response = new V1.ListRolesResponse
        {
            DefaultAnonymousRole = snapshot.DefaultAnonymousRole,
            DefaultVisitorRole = snapshot.DefaultVisitorRole,
            DefaultContactRole = snapshot.DefaultContactRole,
            DefaultHostRole = snapshot.DefaultHostRole,
            DefaultOwnerRole = snapshot.DefaultOwnerRole,
        };
        foreach (var role in snapshot.Roles)
        {
            response.Roles.Add(
                new V1.SessionRole
                {
                    RoleName = role.RoleName,
                    RoleDescription = role.RoleDescription,
                    IsHighest = role.IsHighest,
                    IsLowest = role.IsLowest,
                }
            );
        }

        return response;
    }

    private static KickKind ToKickKind(V1.KickKind kind) =>
        kind switch
        {
            V1.KickKind.Kick => KickKind.Kick,
            V1.KickKind.KickAndRevoke => KickKind.KickAndRevoke,
            _ => KickKind.Default,
        };

    private static SessionAccessLevel ToCoreAccessLevel(V1.SessionAccessLevel level) =>
        level switch
        {
            V1.SessionAccessLevel.Private => SessionAccessLevel.Private,
            V1.SessionAccessLevel.Lan => SessionAccessLevel.Lan,
            V1.SessionAccessLevel.Contacts => SessionAccessLevel.Contacts,
            V1.SessionAccessLevel.ContactsPlus => SessionAccessLevel.ContactsPlus,
            V1.SessionAccessLevel.RegisteredUsers => SessionAccessLevel.RegisteredUsers,
            V1.SessionAccessLevel.Anyone => SessionAccessLevel.Anyone,
            _ => SessionAccessLevel.Unspecified,
        };

    private static V1.SessionAccessLevel ToProtoAccessLevel(SessionAccessLevel level) =>
        level switch
        {
            SessionAccessLevel.Private => V1.SessionAccessLevel.Private,
            SessionAccessLevel.Lan => V1.SessionAccessLevel.Lan,
            SessionAccessLevel.Contacts => V1.SessionAccessLevel.Contacts,
            SessionAccessLevel.ContactsPlus => V1.SessionAccessLevel.ContactsPlus,
            SessionAccessLevel.RegisteredUsers => V1.SessionAccessLevel.RegisteredUsers,
            SessionAccessLevel.Anyone => V1.SessionAccessLevel.Anyone,
            _ => V1.SessionAccessLevel.Unspecified,
        };
}
