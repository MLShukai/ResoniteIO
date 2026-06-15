namespace ResoniteIO.Core.Session;

/// <summary>
/// セッションアクセスレベル (proto <c>SessionAccessLevel</c> / <c>SkyFrost.Base.SessionAccessLevel</c>
/// から独立した Core 層 enum)。
/// </summary>
/// <remarks>
/// <see cref="Unspecified"/> は patch における "変更しない" signal として使う
/// (proto の <c>SESSION_ACCESS_LEVEL_UNSPECIFIED</c> と 1:1)。
/// </remarks>
public enum SessionAccessLevel
{
    Unspecified,
    Private,
    Lan,
    Contacts,
    ContactsPlus,
    RegisteredUsers,
    Anyone,
}

/// <summary>kick 種別 (proto <c>KickKind</c> / <c>User.Kick</c> の KickRequestState から独立した Core 層 enum)。</summary>
/// <remarks><see cref="Default"/> は engine 既定 (KickAndRevokeInvite) として扱う。</remarks>
public enum KickKind
{
    Default,
    Kick,
    KickAndRevoke,
}

/// <summary>
/// 現在の <c>WorldConfiguration</c> snapshot (proto <c>SessionSettings</c> から独立した Core 層 POCO)。
/// </summary>
/// <remarks>
/// 全 field に actual 値を入れる (presence 概念なし)。<paramref name="SessionId"/> /
/// <paramref name="IsHost"/> は読み取り専用メタ。<paramref name="ResoniteLinkEnabled"/> /
/// <paramref name="ResoniteLinkPort"/> は ResoniteLink の読み取り専用状態 (無効時 port は 0)。
/// </remarks>
public sealed record SessionSettingsSnapshot(
    string WorldName,
    string WorldDescription,
    int MaxUsers,
    SessionAccessLevel AccessLevel,
    bool HideFromListing,
    bool MobileFriendly,
    bool AwayKickEnabled,
    float AwayKickMinutes,
    bool AutoSaveEnabled,
    float AutoSaveIntervalMinutes,
    bool AutoCleanupEnabled,
    float AutoCleanupIntervalSeconds,
    IReadOnlyList<string> Tags,
    string SessionId,
    bool IsHost,
    bool ResoniteLinkEnabled,
    int ResoniteLinkPort
);

/// <summary>
/// <c>ApplySettings</c> の部分更新 patch (proto <c>SessionSettingsPatch</c> から独立した Core 層 POCO)。
/// </summary>
/// <remarks>
/// 各 nullable field の <c>null</c> は「変更しない」signal。<see cref="AccessLevel"/> の
/// <see cref="SessionAccessLevel.Unspecified"/> も Service 層で <c>null</c> に正規化される。
/// <see cref="Tags"/> は <c>null</c> なら変更しない (proto の <c>replace_tags=false</c> に対応)、
/// non-null なら全置換 (空配列で全消し)。
/// </remarks>
public sealed record SessionSettingsPatchSnapshot
{
    public string? WorldName { get; init; }
    public string? WorldDescription { get; init; }
    public int? MaxUsers { get; init; }

    /// <summary>新しい access level。<c>null</c> なら変更しない。</summary>
    public SessionAccessLevel? AccessLevel { get; init; }
    public bool? HideFromListing { get; init; }
    public bool? MobileFriendly { get; init; }
    public bool? AwayKickEnabled { get; init; }
    public float? AwayKickMinutes { get; init; }
    public bool? AutoSaveEnabled { get; init; }
    public float? AutoSaveIntervalMinutes { get; init; }
    public bool? AutoCleanupEnabled { get; init; }
    public float? AutoCleanupIntervalSeconds { get; init; }

    /// <summary><c>null</c> なら tags を変更しない。non-null なら全置換 (空配列で全消し)。</summary>
    public IReadOnlyList<string>? Tags { get; init; }

    /// <summary>
    /// ResoniteLink の有効化。<c>true</c> で有効化 (冪等)、<c>null</c> なら変更しない。
    /// <c>false</c> (runtime disable) は engine が stop API を持たないため Bridge 層で
    /// <see cref="SessionResoniteLinkException"/> になる。
    /// </summary>
    public bool? ResoniteLinkEnabled { get; init; }
}

/// <summary>接続ユーザー 1 名の snapshot (proto <c>SessionUser</c> から独立した Core 層 POCO)。</summary>
/// <remarks><paramref name="UserId"/> はゲストでは空のことがある。<paramref name="RoleName"/> は無ければ空。</remarks>
public sealed record SessionUserSnapshot(
    string UserId,
    string UserName,
    bool IsHost,
    bool IsLocalUser,
    bool IsPresentInWorld,
    bool IsSilenced,
    float LocalVolume,
    string RoleName,
    string Platform,
    string HeadDevice
);

/// <summary>role 1 件の snapshot (proto <c>SessionRole</c> / <c>PermissionSet</c> 由来)。</summary>
public sealed record SessionRoleSnapshot(
    string RoleName,
    string RoleDescription,
    bool IsHighest,
    bool IsLowest
);

/// <summary>
/// role 一覧 + 既定 role 名の snapshot (proto <c>ListRolesResponse</c> から独立した Core 層 POCO)。
/// </summary>
/// <remarks>既定 role 名は空もありうる。</remarks>
public sealed record SessionRolesSnapshot(
    IReadOnlyList<SessionRoleSnapshot> Roles,
    string DefaultAnonymousRole,
    string DefaultVisitorRole,
    string DefaultContactRole,
    string DefaultHostRole,
    string DefaultOwnerRole
);

/// <summary>ユーザー別 role override 1 件 (proto <c>UserRoleOverride</c> /
/// <c>DefaultUserPermissions</c> 由来)。</summary>
public sealed record UserRoleOverrideSnapshot(string UserId, string RoleName);

/// <summary>
/// 対象ユーザーの指定方法 (proto <c>UserTarget</c> から独立した Core 層 POCO)。
/// </summary>
/// <remarks>
/// <paramref name="Local"/> が true のとき local user (自分) を対象にする。否なら
/// <paramref name="UserId"/> を優先し、空なら <paramref name="UserName"/> で解決する。
/// </remarks>
public sealed record UserTargetSpec(string UserId, string UserName, bool Local);

/// <summary>
/// Mod 側 (FrooxEngine) が実装し DI で注入する session 操作 (Settings / Users / Permissions) の抽象。
/// </summary>
/// <remarks>
/// engine の <c>World.Configuration</c> / <c>World.AllUsers</c> / <c>World.Permissions</c> を
/// 直接 read/write する。host 権限を要する write は権限不足のとき
/// <see cref="SessionPermissionDeniedException"/> を throw する。
/// </remarks>
public interface ISessionBridge
{
    /// <summary>現在の <c>WorldConfiguration</c> snapshot を engine から読む。</summary>
    /// <exception cref="SessionNotReadyException">engine がまだ読めない状態 (userspace のみ等)。</exception>
    Task<SessionSettingsSnapshot> GetSettingsAsync(CancellationToken ct);

    /// <summary><paramref name="patch"/> の set された field だけを engine に書き込む。値は返さない。</summary>
    /// <exception cref="SessionNotReadyException">engine 未準備。</exception>
    /// <exception cref="SessionPermissionDeniedException">非 authority / 権限不足。</exception>
    Task ApplySettingsAsync(SessionSettingsPatchSnapshot patch, CancellationToken ct);

    /// <summary>接続ユーザー一覧を返す。</summary>
    /// <exception cref="SessionNotReadyException">engine 未準備。</exception>
    Task<IReadOnlyList<SessionUserSnapshot>> ListUsersAsync(CancellationToken ct);

    /// <summary><paramref name="target"/> のユーザーを kick する。</summary>
    /// <exception cref="SessionNotReadyException">engine 未準備。</exception>
    /// <exception cref="SessionUserNotFoundException">対象が見つからない。</exception>
    /// <exception cref="SessionAmbiguousUserException">user_name で複数一致。</exception>
    /// <exception cref="SessionPermissionDeniedException">権限不足。</exception>
    Task KickUserAsync(UserTargetSpec target, KickKind kind, CancellationToken ct);

    /// <summary><paramref name="target"/> のユーザーを ban する。</summary>
    /// <exception cref="SessionNotReadyException">engine 未準備。</exception>
    /// <exception cref="SessionUserNotFoundException">対象が見つからない。</exception>
    /// <exception cref="SessionAmbiguousUserException">user_name で複数一致。</exception>
    /// <exception cref="SessionPermissionDeniedException">権限不足。</exception>
    Task BanUserAsync(UserTargetSpec target, CancellationToken ct);

    /// <summary><paramref name="target"/> のユーザーを silence / unsilence し、更新後 snapshot を返す。</summary>
    /// <exception cref="SessionNotReadyException">engine 未準備。</exception>
    /// <exception cref="SessionUserNotFoundException">対象が見つからない。</exception>
    /// <exception cref="SessionAmbiguousUserException">user_name で複数一致。</exception>
    /// <exception cref="SessionPermissionDeniedException">権限不足。</exception>
    Task<SessionUserSnapshot> SilenceUserAsync(
        UserTargetSpec target,
        bool silenced,
        CancellationToken ct
    );

    /// <summary><paramref name="target"/> のユーザーを respawn する。</summary>
    /// <exception cref="SessionNotReadyException">engine 未準備。</exception>
    /// <exception cref="SessionUserNotFoundException">対象が見つからない。</exception>
    /// <exception cref="SessionAmbiguousUserException">user_name で複数一致。</exception>
    /// <exception cref="SessionPermissionDeniedException">権限不足。</exception>
    Task RespawnUserAsync(UserTargetSpec target, CancellationToken ct);

    /// <summary><paramref name="target"/> のユーザーに <paramref name="roleName"/> を割り当て、更新後 snapshot を返す。</summary>
    /// <exception cref="SessionNotReadyException">engine 未準備。</exception>
    /// <exception cref="SessionUserNotFoundException">対象が見つからない。</exception>
    /// <exception cref="SessionAmbiguousUserException">user_name で複数一致。</exception>
    /// <exception cref="SessionRoleNotFoundException"><paramref name="roleName"/> が存在しない。</exception>
    /// <exception cref="SessionPermissionDeniedException">権限不足。</exception>
    Task<SessionUserSnapshot> SetUserRoleAsync(
        UserTargetSpec target,
        string roleName,
        CancellationToken ct
    );

    /// <summary>role 一覧 + 既定 role 名の snapshot を返す。</summary>
    /// <exception cref="SessionNotReadyException">engine 未準備。</exception>
    Task<SessionRolesSnapshot> ListRolesAsync(CancellationToken ct);

    /// <summary>ユーザー別 role override (<c>DefaultUserPermissions</c>) の一覧を返す。</summary>
    /// <exception cref="SessionNotReadyException">engine 未準備。</exception>
    Task<IReadOnlyList<UserRoleOverrideSnapshot>> GetUserRoleOverridesAsync(CancellationToken ct);
}

/// <summary>
/// Bridge が一時的に session を操作できない状態 (engine 未準備 / userspace のみ等)。
/// Service 層は <c>FailedPrecondition</c> に翻訳するので Client は時間を置いて retry できる。
/// </summary>
public sealed class SessionNotReadyException : Exception
{
    public SessionNotReadyException(string message)
        : base(message) { }

    public SessionNotReadyException(string message, Exception? innerException)
        : base(message, innerException) { }
}

/// <summary>指定ユーザーが見つからない。Service 層は <c>NotFound</c> に翻訳する。</summary>
public sealed class SessionUserNotFoundException : Exception
{
    public SessionUserNotFoundException(string message)
        : base(message) { }

    public SessionUserNotFoundException(string message, Exception? innerException)
        : base(message, innerException) { }
}

/// <summary>
/// user_name による解決で複数のユーザーに一致した (同名ゲスト等)。
/// Service 層は <c>FailedPrecondition</c> に翻訳する。
/// </summary>
public sealed class SessionAmbiguousUserException : Exception
{
    public SessionAmbiguousUserException(string message)
        : base(message) { }

    public SessionAmbiguousUserException(string message, Exception? innerException)
        : base(message, innerException) { }
}

/// <summary>非 authority / host 権限不足で操作できない。Service 層は <c>PermissionDenied</c> に翻訳する。</summary>
public sealed class SessionPermissionDeniedException : Exception
{
    public SessionPermissionDeniedException(string message)
        : base(message) { }

    public SessionPermissionDeniedException(string message, Exception? innerException)
        : base(message, innerException) { }
}

/// <summary>指定 role 名が存在しない。Service 層は <c>NotFound</c> に翻訳する。</summary>
public sealed class SessionRoleNotFoundException : Exception
{
    public SessionRoleNotFoundException(string message)
        : base(message) { }

    public SessionRoleNotFoundException(string message, Exception? innerException)
        : base(message, innerException) { }
}

/// <summary>
/// ResoniteLink を要求どおりに変更できない (runtime disable 不可 / 有効化失敗)。
/// Service 層は <c>FailedPrecondition</c> に翻訳する。
/// </summary>
public sealed class SessionResoniteLinkException : Exception
{
    public SessionResoniteLinkException(string message)
        : base(message) { }

    public SessionResoniteLinkException(string message, Exception? innerException)
        : base(message, innerException) { }
}
