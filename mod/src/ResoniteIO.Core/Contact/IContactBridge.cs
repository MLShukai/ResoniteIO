namespace ResoniteIO.Core.Contact;

/// <summary>連絡先ステータス (proto ContactStatus / engine SkyFrost.Base.ContactStatus から独立した Core 層 enum)。</summary>
public enum ContactStatus
{
    None,
    SearchResult,
    Requested,
    Ignored,
    Blocked,
    Accepted,
}

/// <summary>連絡先の presence (proto OnlineStatus / engine SkyFrost.Base.OnlineStatus から独立した Core 層 enum)。</summary>
public enum OnlineStatus
{
    Offline,
    Invisible,
    Away,
    Busy,
    Online,
    Sociable,
}

/// <summary>連絡先 1 件の snapshot (proto ContactInfo から独立した Core 層 POCO、presence 付き)。</summary>
public sealed record ContactSnapshot(
    string UserId,
    string Username,
    IReadOnlyList<string> AlternateUsernames,
    ContactStatus Status,
    bool IsAccepted,
    bool IsContactRequest,
    OnlineStatus OnlineStatus,
    string CurrentSessionName,
    string CurrentSessionAccessLevel,
    /// <summary>dash の Contacts タブで非表示になる対象か (engine <c>Contact.ShouldBeHidden</c>: None / Ignored / Blocked)。</summary>
    bool IsHidden
);

/// <summary>連絡先一覧 + ContactManager のカウントの snapshot (proto ListContactsResponse 由来)。</summary>
/// <remarks>search / filter は Service 層で適用する。counts は filter / search 適用前の総数。</remarks>
public sealed record ContactListSnapshot(
    IReadOnlyList<ContactSnapshot> Contacts,
    int ContactCount,
    int RequestCount,
    bool ListLoaded
);

/// <summary>ユーザー検索結果 1 件 (proto UserSearchResult 由来)。</summary>
public sealed record UserSearchSnapshot(string UserId, string Username, bool IsVerified);

/// <summary>
/// Mod 側 (FrooxEngine) が実装し DI で注入する連絡先操作 (Cloud.Contacts / Cloud.Users) の抽象。
/// </summary>
/// <remarks>
/// cloud 同期キャッシュの read (一覧 / 単一取得) と cloud への非同期 write (検索 / 追加 / 承認 / 削除) を提供する。
/// engine thread dispatch は不要 (ContactManager は内部 lock で thread-safe、Users は async cloud I/O)。
/// </remarks>
public interface IContactBridge
{
    /// <summary>連絡先一覧 (presence 付き) + カウントを返す。search / filter は Service 層で適用する。</summary>
    /// <exception cref="ContactNotReadyException">cloud がまだ利用できない。</exception>
    Task<ContactListSnapshot> ListContactsAsync(CancellationToken ct);

    /// <summary>単一連絡先をキャッシュから取得する。未登録なら <c>null</c> (Service は found=false にする)。</summary>
    /// <exception cref="ContactNotReadyException">cloud がまだ利用できない。</exception>
    Task<ContactSnapshot?> GetContactAsync(string userId, CancellationToken ct);

    /// <summary>cloud のユーザー検索 (<paramref name="exactMatch"/> なら username 完全一致のみ)。0 件なら空。</summary>
    /// <exception cref="ContactNotReadyException">cloud がまだ利用できない。</exception>
    Task<IReadOnlyList<UserSearchSnapshot>> SearchUsersAsync(
        string query,
        bool exactMatch,
        CancellationToken ct
    );

    /// <summary>
    /// <paramref name="userId"/> をフレンド追加する (status を Accepted にして送信)。
    /// <paramref name="username"/> が空なら cloud から解決する。追加後の snapshot を返す。
    /// </summary>
    /// <exception cref="ContactNotReadyException">cloud がまだ利用できない。</exception>
    /// <exception cref="ContactNotFoundException"><paramref name="userId"/> が cloud に存在しない。</exception>
    /// <exception cref="ContactOperationException">cloud 追加操作が失敗した。</exception>
    Task<ContactSnapshot> AddContactAsync(string userId, string username, CancellationToken ct);

    /// <summary>受信中フレンドリクエストを承認し、承認後の snapshot を返す。</summary>
    /// <exception cref="ContactNotReadyException">cloud がまだ利用できない。</exception>
    /// <exception cref="ContactNotFoundException"><paramref name="userId"/> の連絡先が無い。</exception>
    /// <exception cref="ContactOperationException">cloud 承認操作が失敗した。</exception>
    Task<ContactSnapshot> AcceptRequestAsync(string userId, CancellationToken ct);

    /// <summary>連絡先を削除 / リクエストを拒否する (status を Ignored に)。</summary>
    /// <exception cref="ContactNotReadyException">cloud がまだ利用できない。</exception>
    /// <exception cref="ContactNotFoundException"><paramref name="userId"/> の連絡先が無い。</exception>
    /// <exception cref="ContactOperationException">cloud 削除操作が失敗した。</exception>
    Task RemoveContactAsync(string userId, CancellationToken ct);
}

/// <summary>cloud がまだ連絡先操作を受け付けられない (engine 未ログイン等)。Service 層は FailedPrecondition に翻訳する。</summary>
public sealed class ContactNotReadyException : Exception
{
    public ContactNotReadyException(string message)
        : base(message) { }

    public ContactNotReadyException(string message, Exception? innerException)
        : base(message, innerException) { }
}

/// <summary>指定 user_id の連絡先 / ユーザーが見つからない。Service 層は NotFound に翻訳する。</summary>
public sealed class ContactNotFoundException : Exception
{
    public ContactNotFoundException(string message)
        : base(message) { }

    public ContactNotFoundException(string message, Exception? innerException)
        : base(message, innerException) { }
}

/// <summary>cloud 操作 (追加 / 承認 / 削除) が失敗を返した。Service 層は Internal に翻訳する。</summary>
public sealed class ContactOperationException : Exception
{
    public ContactOperationException(string message)
        : base(message) { }

    public ContactOperationException(string message, Exception? innerException)
        : base(message, innerException) { }
}
