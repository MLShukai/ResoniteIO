using ResoniteIO.Core.Session;

namespace ResoniteIO.Core.Tests.Common.Fakes;

/// <summary>
/// テスト用 <see cref="ISessionBridge"/>。in-memory の settings / users / roles を保持し、
/// Service が proto から組み立てた Core POCO 引数 (patch / target / kind 等) を素直に観測できるようにする。
/// </summary>
/// <remarks>
/// <para>
/// <see cref="LastApplyPatch"/> / <see cref="LastTarget"/> / <see cref="LastKickKind"/> /
/// <see cref="LastRoleName"/> に最後の引数を控えるので、Service の proto→POCO 変換 (とくに
/// optional presence) を end-to-end で検証できる。<see cref="Calls"/> には RPC 名を時系列で記録する。
/// </para>
/// <para>
/// 例外翻訳テスト用に各 <c>Throw*</c> フラグを 1 つ立てると、以降の呼び出しで対応する例外を投げる。
/// <c>max_users</c> 範囲検証は <b>Service 層</b>の責務なので、本 Fake は範囲チェックしない (契約準拠)。
/// </para>
/// </remarks>
internal sealed class FakeSessionBridge : ISessionBridge
{
    private SessionSettingsSnapshot _settings = new(
        WorldName: "Test World",
        WorldDescription: "a place",
        MaxUsers: 16,
        AccessLevel: SessionAccessLevel.Contacts,
        HideFromListing: false,
        MobileFriendly: true,
        AwayKickEnabled: false,
        AwayKickMinutes: 5f,
        AutoSaveEnabled: true,
        AutoSaveIntervalMinutes: 10f,
        AutoCleanupEnabled: false,
        AutoCleanupIntervalSeconds: 120f,
        Tags: new[] { "social", "test" },
        SessionId: "S-test-session",
        IsHost: true,
        ResoniteLinkEnabled: false,
        ResoniteLinkPort: 0
    );

    /// <summary>
    /// ResoniteLink を有効化したときに engine が割り当てるポートを模した値。
    /// 実 engine は 2000-65535 の動的割当だが、Fake では決定的な値を返す
    /// (snapshot に「有効時 port は &gt; 0」が載ることを観測するための代理値)。
    /// </summary>
    private const int ResoniteLinkEnabledPort = 50000;

    private readonly List<SessionUserSnapshot> _users = new()
    {
        new SessionUserSnapshot(
            UserId: "U-host",
            UserName: "Host",
            IsHost: true,
            IsLocalUser: true,
            IsPresentInWorld: true,
            IsSilenced: false,
            LocalVolume: 1.0f,
            RoleName: "Admin",
            Platform: "Windows",
            HeadDevice: "Desktop"
        ),
        new SessionUserSnapshot(
            UserId: "U-guest",
            UserName: "Guest",
            IsHost: false,
            IsLocalUser: false,
            IsPresentInWorld: true,
            IsSilenced: false,
            LocalVolume: 1.0f,
            RoleName: "Guest",
            Platform: "Linux",
            HeadDevice: "Index"
        ),
    };

    private readonly SessionRolesSnapshot _roles = new(
        Roles: new[]
        {
            new SessionRoleSnapshot("Admin", "full control", IsHighest: true, IsLowest: false),
            new SessionRoleSnapshot("Builder", "can build", IsHighest: false, IsLowest: false),
            new SessionRoleSnapshot("Guest", "view only", IsHighest: false, IsLowest: true),
        },
        DefaultAnonymousRole: "Guest",
        DefaultVisitorRole: "Guest",
        DefaultContactRole: "Builder",
        DefaultHostRole: "Admin",
        DefaultOwnerRole: "Admin"
    );

    private readonly List<UserRoleOverrideSnapshot> _overrides = new()
    {
        new UserRoleOverrideSnapshot("U-friend", "Builder"),
    };

    public List<string> Calls { get; } = new();

    /// <summary>最後に <see cref="ApplySettingsAsync"/> に渡された patch。未呼び出しなら null。</summary>
    public SessionSettingsPatchSnapshot? LastApplyPatch { get; private set; }

    /// <summary>最後に user 操作 RPC に渡された target。未呼び出しなら null。</summary>
    public UserTargetSpec? LastTarget { get; private set; }

    /// <summary>最後に <see cref="KickUserAsync"/> に渡された kind。未呼び出しなら null。</summary>
    public KickKind? LastKickKind { get; private set; }

    /// <summary>最後に <see cref="SetUserRoleAsync"/> に渡された role 名。未呼び出しなら null。</summary>
    public string? LastRoleName { get; private set; }

    public bool ThrowNotReady { get; set; }
    public bool ThrowPermissionDenied { get; set; }
    public bool ThrowUserNotFound { get; set; }
    public bool ThrowAmbiguous { get; set; }
    public bool ThrowRoleNotFound { get; set; }

    public Task<SessionSettingsSnapshot> GetSettingsAsync(CancellationToken ct)
    {
        Calls.Add("GetSettings");
        TripIfArmed();
        return Task.FromResult(_settings);
    }

    public Task ApplySettingsAsync(SessionSettingsPatchSnapshot patch, CancellationToken ct)
    {
        Calls.Add("ApplySettings");
        LastApplyPatch = patch;
        TripIfArmed();

        // ResoniteLink: true=有効化 (冪等), false=runtime disable 不可 (例外),
        // null=変更しない。engine 契約 (ISessionBridge / session.proto) に準拠。
        var resoniteLinkEnabled = _settings.ResoniteLinkEnabled;
        var resoniteLinkPort = _settings.ResoniteLinkPort;
        switch (patch.ResoniteLinkEnabled)
        {
            case true:
                resoniteLinkEnabled = true;
                resoniteLinkPort = ResoniteLinkEnabledPort;
                break;
            case false:
                throw new SessionResoniteLinkException(
                    "ResoniteLink cannot be disabled at runtime (the engine exposes no stop API)."
                );
            case null:
                break;
        }

        _settings = _settings with
        {
            WorldName = patch.WorldName ?? _settings.WorldName,
            WorldDescription = patch.WorldDescription ?? _settings.WorldDescription,
            MaxUsers = patch.MaxUsers ?? _settings.MaxUsers,
            AccessLevel = patch.AccessLevel ?? _settings.AccessLevel,
            HideFromListing = patch.HideFromListing ?? _settings.HideFromListing,
            MobileFriendly = patch.MobileFriendly ?? _settings.MobileFriendly,
            AwayKickEnabled = patch.AwayKickEnabled ?? _settings.AwayKickEnabled,
            AwayKickMinutes = patch.AwayKickMinutes ?? _settings.AwayKickMinutes,
            AutoSaveEnabled = patch.AutoSaveEnabled ?? _settings.AutoSaveEnabled,
            AutoSaveIntervalMinutes =
                patch.AutoSaveIntervalMinutes ?? _settings.AutoSaveIntervalMinutes,
            AutoCleanupEnabled = patch.AutoCleanupEnabled ?? _settings.AutoCleanupEnabled,
            AutoCleanupIntervalSeconds =
                patch.AutoCleanupIntervalSeconds ?? _settings.AutoCleanupIntervalSeconds,
            Tags = patch.Tags ?? _settings.Tags,
            ResoniteLinkEnabled = resoniteLinkEnabled,
            ResoniteLinkPort = resoniteLinkPort,
        };

        return Task.CompletedTask;
    }

    public Task<IReadOnlyList<SessionUserSnapshot>> ListUsersAsync(CancellationToken ct)
    {
        Calls.Add("ListUsers");
        TripIfArmed();
        return Task.FromResult<IReadOnlyList<SessionUserSnapshot>>(_users.ToList());
    }

    public Task KickUserAsync(UserTargetSpec target, KickKind kind, CancellationToken ct)
    {
        Calls.Add("KickUser");
        LastTarget = target;
        LastKickKind = kind;
        TripIfArmed();
        _users.RemoveAll(u => Matches(u, target));
        return Task.CompletedTask;
    }

    public Task BanUserAsync(UserTargetSpec target, CancellationToken ct)
    {
        Calls.Add("BanUser");
        LastTarget = target;
        TripIfArmed();
        _users.RemoveAll(u => Matches(u, target));
        return Task.CompletedTask;
    }

    public Task<SessionUserSnapshot> SilenceUserAsync(
        UserTargetSpec target,
        bool silenced,
        CancellationToken ct
    )
    {
        Calls.Add("SilenceUser");
        LastTarget = target;
        TripIfArmed();
        var index = _users.FindIndex(u => Matches(u, target));
        var updated = _users[index] with { IsSilenced = silenced };
        _users[index] = updated;
        return Task.FromResult(updated);
    }

    public Task RespawnUserAsync(UserTargetSpec target, CancellationToken ct)
    {
        Calls.Add("RespawnUser");
        LastTarget = target;
        TripIfArmed();
        return Task.CompletedTask;
    }

    public Task<SessionUserSnapshot> SetUserRoleAsync(
        UserTargetSpec target,
        string roleName,
        CancellationToken ct
    )
    {
        Calls.Add("SetUserRole");
        LastTarget = target;
        LastRoleName = roleName;
        TripIfArmed();
        var index = _users.FindIndex(u => Matches(u, target));
        var updated = _users[index] with { RoleName = roleName };
        _users[index] = updated;
        return Task.FromResult(updated);
    }

    public Task<SessionRolesSnapshot> ListRolesAsync(CancellationToken ct)
    {
        Calls.Add("ListRoles");
        TripIfArmed();
        return Task.FromResult(_roles);
    }

    public Task<IReadOnlyList<UserRoleOverrideSnapshot>> GetUserRoleOverridesAsync(
        CancellationToken ct
    )
    {
        Calls.Add("GetUserRoleOverrides");
        TripIfArmed();
        return Task.FromResult<IReadOnlyList<UserRoleOverrideSnapshot>>(_overrides.ToList());
    }

    /// <summary>テスト補助: 現在保持しているユーザー数。kick / ban で減る。</summary>
    public int UserCount => _users.Count;

    /// <summary>テスト補助: 指定 user_id のユーザーがまだ在席しているか。</summary>
    public bool HasUser(string userId) => _users.Any(u => u.UserId == userId);

    private static bool Matches(SessionUserSnapshot user, UserTargetSpec target)
    {
        if (target.Local)
        {
            return user.IsLocalUser;
        }
        if (!string.IsNullOrEmpty(target.UserId))
        {
            return user.UserId == target.UserId;
        }
        return user.UserName == target.UserName;
    }

    private void TripIfArmed()
    {
        if (ThrowNotReady)
        {
            throw new SessionNotReadyException("engine not ready");
        }
        if (ThrowPermissionDenied)
        {
            throw new SessionPermissionDeniedException("not authority");
        }
        if (ThrowUserNotFound)
        {
            throw new SessionUserNotFoundException("no such user");
        }
        if (ThrowAmbiguous)
        {
            throw new SessionAmbiguousUserException("name matched multiple users");
        }
        if (ThrowRoleNotFound)
        {
            throw new SessionRoleNotFoundException("no such role");
        }
    }
}
