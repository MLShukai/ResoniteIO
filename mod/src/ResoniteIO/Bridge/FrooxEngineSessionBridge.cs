using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using FrooxEngine;
using ResoniteIO.Core.Logging;
using ResoniteIO.Core.Session;
using EngineAccessLevel = SkyFrost.Base.SessionAccessLevel;
using FrooxWorld = FrooxEngine.World;

namespace ResoniteIO.Bridge;

/// <summary>
/// focused world の <see cref="WorldConfiguration"/> / <see cref="FrooxWorld.AllUsers"/> /
/// <see cref="PermissionController"/> を直接 read/write する <see cref="ISessionBridge"/> 実装。
/// </summary>
/// <remarks>
/// <para>
/// engine state (Configuration / AllUsers / Permissions の各 collection) への read/write は
/// すべて <see cref="EngineDispatch.RunOnEngineAsync{T}(FrooxWorld, Func{T}, CancellationToken)"/>
/// で engine update tick 上に one-shot で marshal し、外に出すのは immutable POCO のみとする
/// (FrooxEngineWorldBridge / FrooxEngineCursorBridge と同型)。
/// </para>
/// <para>
/// focused world が無い / userspace のみのときは <see cref="SessionNotReadyException"/>、
/// host 権限を要する write を非 authority / 権限不足で実行しようとした場合は
/// <see cref="SessionPermissionDeniedException"/> を投げ、Service 層がそれぞれ
/// FailedPrecondition / PermissionDenied に翻訳する。
/// </para>
/// </remarks>
internal sealed class FrooxEngineSessionBridge : ISessionBridge
{
    private readonly Engine _engine;
    private readonly ILogSink _log;

    public FrooxEngineSessionBridge(Engine engine, ILogSink log)
    {
        ArgumentNullException.ThrowIfNull(engine);
        ArgumentNullException.ThrowIfNull(log);
        _engine = engine;
        _log = log;
    }

    /// <inheritdoc/>
    public Task<SessionSettingsSnapshot> GetSettingsAsync(CancellationToken ct)
    {
        ct.ThrowIfCancellationRequested();
        return RunOnEngineAsync(() => ReadSettings(ResolveWorld()), ct);
    }

    /// <inheritdoc/>
    public Task ApplySettingsAsync(SessionSettingsPatchSnapshot patch, CancellationToken ct)
    {
        ct.ThrowIfCancellationRequested();
        ArgumentNullException.ThrowIfNull(patch);

        return RunOnEngineAsync(
            () =>
            {
                var world = ResolveWorld();
                if (!world.IsAuthority)
                {
                    throw new SessionPermissionDeniedException(
                        "Only the session host can change session settings."
                    );
                }

                ApplySettings(world.Configuration, patch);
                _log.LogInfo("[ResoniteIO] Session.ApplySettings");
                return true;
            },
            ct
        );
    }

    /// <inheritdoc/>
    public Task<IReadOnlyList<SessionUserSnapshot>> ListUsersAsync(CancellationToken ct)
    {
        ct.ThrowIfCancellationRequested();
        return RunOnEngineAsync<IReadOnlyList<SessionUserSnapshot>>(
            () =>
            {
                var world = ResolveWorld();
                var result = new List<SessionUserSnapshot>();
                foreach (var user in world.AllUsers)
                {
                    if (user is null)
                    {
                        continue;
                    }
                    result.Add(ReadUser(user));
                }
                return result;
            },
            ct
        );
    }

    /// <inheritdoc/>
    public Task KickUserAsync(UserTargetSpec target, KickKind kind, CancellationToken ct)
    {
        ct.ThrowIfCancellationRequested();
        ArgumentNullException.ThrowIfNull(target);

        return RunOnEngineAsync(
            () =>
            {
                var world = ResolveWorld();
                var user = ResolveUser(world, target);
                if (!world.LocalUser.CanKick())
                {
                    throw new SessionPermissionDeniedException(
                        "You do not have permission to kick users in this session."
                    );
                }
                user.Kick(MapKick(kind));
                _log.LogInfo($"[ResoniteIO] Session.Kick: {user.UserName}");
                return true;
            },
            ct
        );
    }

    /// <inheritdoc/>
    public Task BanUserAsync(UserTargetSpec target, CancellationToken ct)
    {
        ct.ThrowIfCancellationRequested();
        ArgumentNullException.ThrowIfNull(target);

        return RunOnEngineAsync(
            () =>
            {
                var world = ResolveWorld();
                var user = ResolveUser(world, target);
                if (!world.LocalUser.CanBan())
                {
                    throw new SessionPermissionDeniedException(
                        "You do not have permission to ban users in this session."
                    );
                }
                user.Ban();
                _log.LogInfo($"[ResoniteIO] Session.Ban: {user.UserName}");
                return true;
            },
            ct
        );
    }

    /// <inheritdoc/>
    public Task<SessionUserSnapshot> SilenceUserAsync(
        UserTargetSpec target,
        bool silenced,
        CancellationToken ct
    )
    {
        ct.ThrowIfCancellationRequested();
        ArgumentNullException.ThrowIfNull(target);

        return RunOnEngineAsync(
            () =>
            {
                var world = ResolveWorld();
                var user = ResolveUser(world, target);
                if (!world.LocalUser.CanSilence())
                {
                    throw new SessionPermissionDeniedException(
                        "You do not have permission to silence users in this session."
                    );
                }
                user.IsSilenced = silenced;
                _log.LogInfo($"[ResoniteIO] Session.Silence({silenced}): {user.UserName}");
                return ReadUser(user);
            },
            ct
        );
    }

    /// <inheritdoc/>
    public Task RespawnUserAsync(UserTargetSpec target, CancellationToken ct)
    {
        ct.ThrowIfCancellationRequested();
        ArgumentNullException.ThrowIfNull(target);

        return RunOnEngineAsync(
            () =>
            {
                var world = ResolveWorld();
                var user = ResolveUser(world, target);
                // ローカルユーザは自分を常に respawn できる (SessionUserController.OnRespawn と同じ)。
                if (!user.IsLocalUser && !user.CanRespawn())
                {
                    throw new SessionPermissionDeniedException(
                        "You do not have permission to respawn this user."
                    );
                }
                // SessionUserController.OnRespawn と同経路。既に engine thread 上なので直接呼ぶ。
                user.Root?.Slot?.DestroyPreservingAssets();
                _log.LogInfo($"[ResoniteIO] Session.Respawn: {user.UserName}");
                return true;
            },
            ct
        );
    }

    /// <inheritdoc/>
    public Task<SessionUserSnapshot> SetUserRoleAsync(
        UserTargetSpec target,
        string roleName,
        CancellationToken ct
    )
    {
        ct.ThrowIfCancellationRequested();
        ArgumentNullException.ThrowIfNull(target);
        ArgumentNullException.ThrowIfNull(roleName);

        return RunOnEngineAsync(
            () =>
            {
                var world = ResolveWorld();
                var user = ResolveUser(world, target);
                if (!world.LocalUser.CanAssignRoles())
                {
                    throw new SessionPermissionDeniedException(
                        "You do not have permission to assign roles in this session."
                    );
                }

                var role = FindRole(world.Permissions, roleName);
                if (role is null)
                {
                    throw new SessionRoleNotFoundException($"No role named '{roleName}' exists.");
                }

                // SessionPermissionController.SetRole と同経路:
                //   user.Role の setter が ForceWrite を行い、UserID があれば既定 role も更新する。
                user.Role = role;
                if (!string.IsNullOrEmpty(user.UserID))
                {
                    world.Permissions.AssignDefaultRole(user, role);
                }
                _log.LogInfo($"[ResoniteIO] Session.SetRole({roleName}): {user.UserName}");
                return ReadUser(user);
            },
            ct
        );
    }

    /// <inheritdoc/>
    public Task<SessionRolesSnapshot> ListRolesAsync(CancellationToken ct)
    {
        ct.ThrowIfCancellationRequested();
        return RunOnEngineAsync(() => ReadRoles(ResolveWorld().Permissions), ct);
    }

    /// <inheritdoc/>
    public Task<IReadOnlyList<UserRoleOverrideSnapshot>> GetUserRoleOverridesAsync(
        CancellationToken ct
    )
    {
        ct.ThrowIfCancellationRequested();
        return RunOnEngineAsync<IReadOnlyList<UserRoleOverrideSnapshot>>(
            () =>
            {
                var permissions = ResolveWorld().Permissions;
                var result = new List<UserRoleOverrideSnapshot>();
                foreach (var entry in permissions.DefaultUserPermissions)
                {
                    var roleName = entry.Value?.Target?.RoleName.Value ?? "";
                    result.Add(new UserRoleOverrideSnapshot(entry.Key ?? "", roleName));
                }
                return result;
            },
            ct
        );
    }

    // ---- engine-thread readers / writers ----------------------------------

    /// <summary>現在の <see cref="WorldConfiguration"/> snapshot を読む。前提: engine thread 上で呼ぶ。</summary>
    private static SessionSettingsSnapshot ReadSettings(FrooxWorld world)
    {
        var config = world.Configuration;
        return new SessionSettingsSnapshot(
            WorldName: config.WorldName.Value ?? "",
            WorldDescription: config.WorldDescription.Value ?? "",
            MaxUsers: config.MaxUsers.Value,
            AccessLevel: FromEngineAccessLevel(config.AccessLevel.Value),
            HideFromListing: config.HideFromListing.Value,
            MobileFriendly: config.MobileFriendly.Value,
            AwayKickEnabled: config.AwayKickEnabled.Value,
            AwayKickMinutes: config.AwayKickMinutes.Value,
            AutoSaveEnabled: config.AutoSaveEnabled.Value,
            AutoSaveIntervalMinutes: config.AutoSaveInterval.Value,
            AutoCleanupEnabled: config.AutoCleanupEnabled.Value,
            AutoCleanupIntervalSeconds: config.AutoCleanupInterval.Value,
            Tags: ReadTags(config.WorldTags),
            SessionId: world.SessionId ?? "",
            IsHost: world.IsAuthority
        );
    }

    /// <summary>patch の set された field のみ <see cref="WorldConfiguration"/> に書く。前提: engine thread 上で呼ぶ。</summary>
    private static void ApplySettings(WorldConfiguration config, SessionSettingsPatchSnapshot patch)
    {
        if (patch.WorldName is not null)
        {
            config.WorldName.Value = patch.WorldName;
        }
        if (patch.WorldDescription is not null)
        {
            config.WorldDescription.Value = patch.WorldDescription;
        }
        if (patch.MaxUsers is { } maxUsers)
        {
            config.MaxUsers.Value = maxUsers;
        }
        if (patch.AccessLevel is { } accessLevel && accessLevel != SessionAccessLevel.Unspecified)
        {
            config.AccessLevel.Value = ToEngineAccessLevel(accessLevel);
        }
        if (patch.HideFromListing is { } hide)
        {
            config.HideFromListing.Value = hide;
        }
        if (patch.MobileFriendly is { } mobile)
        {
            config.MobileFriendly.Value = mobile;
        }
        if (patch.AwayKickEnabled is { } awayKick)
        {
            config.AwayKickEnabled.Value = awayKick;
        }
        if (patch.AwayKickMinutes is { } awayKickMinutes)
        {
            config.AwayKickMinutes.Value = awayKickMinutes;
        }
        if (patch.AutoSaveEnabled is { } autoSave)
        {
            config.AutoSaveEnabled.Value = autoSave;
        }
        if (patch.AutoSaveIntervalMinutes is { } autoSaveInterval)
        {
            config.AutoSaveInterval.Value = autoSaveInterval;
        }
        if (patch.AutoCleanupEnabled is { } autoCleanup)
        {
            config.AutoCleanupEnabled.Value = autoCleanup;
        }
        if (patch.AutoCleanupIntervalSeconds is { } autoCleanupInterval)
        {
            config.AutoCleanupInterval.Value = autoCleanupInterval;
        }
        if (patch.Tags is not null)
        {
            config.WorldTags.Clear();
            foreach (var tag in patch.Tags)
            {
                config.WorldTags.Add(tag);
            }
        }
    }

    /// <summary>接続ユーザ 1 名の snapshot を読む。前提: engine thread 上で呼ぶ。</summary>
    private static SessionUserSnapshot ReadUser(User user)
    {
        return new SessionUserSnapshot(
            UserId: user.UserID ?? "",
            UserName: user.UserName ?? "",
            IsHost: user.IsHost,
            IsLocalUser: user.IsLocalUser,
            IsPresentInWorld: user.IsPresentInWorld,
            IsSilenced: user.IsSilenced,
            LocalVolume: user.LocalVolume,
            RoleName: user.Role?.RoleName.Value ?? "",
            Platform: user.Platform.ToString(),
            HeadDevice: user.HeadDevice.ToString()
        );
    }

    /// <summary>role 一覧 + 既定 role 名の snapshot を読む。前提: engine thread 上で呼ぶ。</summary>
    private static SessionRolesSnapshot ReadRoles(PermissionController permissions)
    {
        var roles = permissions.Roles;
        var last = roles.Count - 1;
        var roleSnapshots = new List<SessionRoleSnapshot>(roles.Count);
        for (var i = 0; i < roles.Count; i++)
        {
            var role = roles[i];
            roleSnapshots.Add(
                new SessionRoleSnapshot(
                    RoleName: role?.RoleName.Value ?? "",
                    RoleDescription: role?.RoleDescription.Value ?? "",
                    IsHighest: i == 0,
                    IsLowest: i == last
                )
            );
        }

        return new SessionRolesSnapshot(
            Roles: roleSnapshots,
            DefaultAnonymousRole: permissions.DefaultAnonymousRole.Target?.RoleName.Value ?? "",
            DefaultVisitorRole: permissions.DefaultVisitorRole.Target?.RoleName.Value ?? "",
            DefaultContactRole: permissions.DefaultContactRole.Target?.RoleName.Value ?? "",
            DefaultHostRole: permissions.DefaultHostRole.Target?.RoleName.Value ?? "",
            DefaultOwnerRole: permissions.DefaultOwnerRole.Target?.RoleName.Value ?? ""
        );
    }

    private static IReadOnlyList<string> ReadTags(SyncFieldList<string> tags)
    {
        var result = new List<string>(tags.Count);
        for (var i = 0; i < tags.Count; i++)
        {
            result.Add(tags[i] ?? "");
        }
        return result;
    }

    // ---- resolution helpers -----------------------------------------------

    /// <summary>
    /// focused world を解決する。null / dispose 済み / userspace のみのときは
    /// <see cref="SessionNotReadyException"/>。
    /// </summary>
    private FrooxWorld ResolveWorld()
    {
        var world = _engine.WorldManager.FocusedWorld;
        if (world is null || world.IsDisposed || world.IsUserspace())
        {
            throw new SessionNotReadyException(
                "No active session world is available yet (engine may still be initializing "
                    + "or only userspace is open)."
            );
        }
        return world;
    }

    /// <summary>
    /// <paramref name="target"/> を world のユーザに解決する。前提: engine thread 上で呼ぶ。
    /// </summary>
    /// <exception cref="SessionUserNotFoundException">対象が見つからない。</exception>
    /// <exception cref="SessionAmbiguousUserException">user_name で複数一致。</exception>
    private static User ResolveUser(FrooxWorld world, UserTargetSpec target)
    {
        if (target.Local)
        {
            return world.LocalUser
                ?? throw new SessionUserNotFoundException("No local user is present.");
        }

        if (!string.IsNullOrEmpty(target.UserId))
        {
            foreach (var user in world.AllUsers)
            {
                if (
                    user is not null
                    && string.Equals(user.UserID, target.UserId, StringComparison.Ordinal)
                )
                {
                    return user;
                }
            }
            throw new SessionUserNotFoundException(
                $"No user with id '{target.UserId}' is present in the session."
            );
        }

        if (!string.IsNullOrEmpty(target.UserName))
        {
            User? match = null;
            foreach (var user in world.AllUsers)
            {
                if (
                    user is not null
                    && string.Equals(user.UserName, target.UserName, StringComparison.Ordinal)
                )
                {
                    if (match is not null)
                    {
                        throw new SessionAmbiguousUserException(
                            $"Multiple users named '{target.UserName}' are present; "
                                + "use a user id instead."
                        );
                    }
                    match = user;
                }
            }
            if (match is not null)
            {
                return match;
            }
            throw new SessionUserNotFoundException(
                $"No user named '{target.UserName}' is present in the session."
            );
        }

        throw new SessionUserNotFoundException(
            "A user target must specify local, a user id, or a user name."
        );
    }

    /// <summary>role 名 (大小文字を区別しない) で <see cref="PermissionSet"/> を引く。前提: engine thread 上で呼ぶ。</summary>
    private static PermissionSet? FindRole(PermissionController permissions, string roleName)
    {
        var roles = permissions.Roles;
        for (var i = 0; i < roles.Count; i++)
        {
            var role = roles[i];
            if (
                role is not null
                && string.Equals(role.RoleName.Value, roleName, StringComparison.OrdinalIgnoreCase)
            )
            {
                return role;
            }
        }
        return null;
    }

    // ---- enum / kick mapping ----------------------------------------------

    /// <summary>
    /// engine <see cref="EngineAccessLevel"/> (Private=0..Anyone=5) を Core
    /// <see cref="SessionAccessLevel"/> (Unspecified=0, Private=1..Anyone=6) に写す (core = engine + 1)。
    /// </summary>
    private static SessionAccessLevel FromEngineAccessLevel(EngineAccessLevel level) =>
        level switch
        {
            EngineAccessLevel.Private => SessionAccessLevel.Private,
            EngineAccessLevel.LAN => SessionAccessLevel.Lan,
            EngineAccessLevel.Contacts => SessionAccessLevel.Contacts,
            EngineAccessLevel.ContactsPlus => SessionAccessLevel.ContactsPlus,
            EngineAccessLevel.RegisteredUsers => SessionAccessLevel.RegisteredUsers,
            EngineAccessLevel.Anyone => SessionAccessLevel.Anyone,
            _ => SessionAccessLevel.Unspecified,
        };

    /// <summary>
    /// Core <see cref="SessionAccessLevel"/> (Private=1..Anyone=6) を engine
    /// <see cref="EngineAccessLevel"/> (Private=0..Anyone=5) に写す (engine = core - 1)。
    /// <see cref="SessionAccessLevel.Unspecified"/> は呼び出し前に弾く前提。
    /// </summary>
    private static EngineAccessLevel ToEngineAccessLevel(SessionAccessLevel level) =>
        level switch
        {
            SessionAccessLevel.Private => EngineAccessLevel.Private,
            SessionAccessLevel.Lan => EngineAccessLevel.LAN,
            SessionAccessLevel.Contacts => EngineAccessLevel.Contacts,
            SessionAccessLevel.ContactsPlus => EngineAccessLevel.ContactsPlus,
            SessionAccessLevel.RegisteredUsers => EngineAccessLevel.RegisteredUsers,
            SessionAccessLevel.Anyone => EngineAccessLevel.Anyone,
            _ => EngineAccessLevel.Private,
        };

    private static User.KickRequestState MapKick(KickKind kind) =>
        kind switch
        {
            KickKind.Kick => User.KickRequestState.Kick,
            KickKind.KickAndRevoke => User.KickRequestState.KickAndRevokeInvite,
            _ => User.KickRequestState.KickAndRevokeInvite,
        };

    private Task<T> RunOnEngineAsync<T>(Func<T> fn, CancellationToken ct) =>
        ResolveWorld().RunOnEngineAsync(fn, ct);
}
