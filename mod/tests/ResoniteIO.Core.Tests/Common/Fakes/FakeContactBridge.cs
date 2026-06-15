using ResoniteIO.Core.Contact;

namespace ResoniteIO.Core.Tests.Common.Fakes;

/// <summary>
/// テスト用 <see cref="IContactBridge"/>。in-memory の連絡先一覧 / カウント / 検索結果を保持し、
/// Service が proto から組み立てた引数 (user_id / query / exact_match / username) を素直に観測できるようにする。
/// </summary>
/// <remarks>
/// <para>
/// <see cref="LastUserId"/> / <see cref="LastUsername"/> / <see cref="LastQuery"/> /
/// <see cref="LastExactMatch"/> に最後の引数を控えるので、Service の proto→引数変換を
/// end-to-end で検証できる。<see cref="Calls"/> には RPC 名を時系列で記録する。
/// </para>
/// <para>
/// <see cref="ListResult"/> / <see cref="GetResult"/> / <see cref="SearchResult"/> /
/// <see cref="AddResult"/> / <see cref="AcceptResult"/> を差し替えると任意の戻り値を仕込める。
/// 例外翻訳テスト用に各 <c>Throw*</c> フラグを 1 つ立てると、以降の呼び出しで対応する例外を投げる。
/// <b>search / filter は Service 層</b>の責務なので、本 Fake は一覧をそのまま返す (契約準拠)。
/// </para>
/// </remarks>
internal sealed class FakeContactBridge : IContactBridge
{
    /// <summary><see cref="ListContactsAsync"/> が返す snapshot。search / filter は Service が適用する。</summary>
    public ContactListSnapshot ListResult { get; set; } =
        new(
            Contacts: new[]
            {
                new ContactSnapshot(
                    UserId: "U-alice",
                    Username: "Alice",
                    AlternateUsernames: new[] { "AliceAlt" },
                    Status: ContactStatus.Accepted,
                    IsAccepted: true,
                    IsContactRequest: false,
                    OnlineStatus: OnlineStatus.Online,
                    CurrentSessionName: "Home",
                    CurrentSessionAccessLevel: "Private"
                ),
                new ContactSnapshot(
                    UserId: "U-bob",
                    Username: "Bob",
                    AlternateUsernames: Array.Empty<string>(),
                    Status: ContactStatus.Requested,
                    IsAccepted: false,
                    IsContactRequest: true,
                    OnlineStatus: OnlineStatus.Away,
                    CurrentSessionName: "",
                    CurrentSessionAccessLevel: ""
                ),
            },
            ContactCount: 1,
            RequestCount: 1,
            ListLoaded: true
        );

    /// <summary>
    /// <see cref="GetContactAsync"/> が返す snapshot。<c>null</c> なら未登録 (Service は found=false に)。
    /// </summary>
    public ContactSnapshot? GetResult { get; set; } =
        new(
            UserId: "U-alice",
            Username: "Alice",
            AlternateUsernames: new[] { "AliceAlt" },
            Status: ContactStatus.Accepted,
            IsAccepted: true,
            IsContactRequest: false,
            OnlineStatus: OnlineStatus.Sociable,
            CurrentSessionName: "Home",
            CurrentSessionAccessLevel: "Private"
        );

    /// <summary><see cref="SearchUsersAsync"/> が返す検索結果。</summary>
    public IReadOnlyList<UserSearchSnapshot> SearchResult { get; set; } =
        new[]
        {
            new UserSearchSnapshot("U-carol", "Carol", IsVerified: true),
            new UserSearchSnapshot("U-dave", "Dave", IsVerified: false),
        };

    /// <summary><see cref="AddContactAsync"/> が返す snapshot。</summary>
    public ContactSnapshot AddResult { get; set; } =
        new(
            UserId: "U-carol",
            Username: "Carol",
            AlternateUsernames: Array.Empty<string>(),
            Status: ContactStatus.Accepted,
            IsAccepted: true,
            IsContactRequest: false,
            OnlineStatus: OnlineStatus.Online,
            CurrentSessionName: "",
            CurrentSessionAccessLevel: ""
        );

    /// <summary><see cref="AcceptRequestAsync"/> が返す snapshot。</summary>
    public ContactSnapshot AcceptResult { get; set; } =
        new(
            UserId: "U-bob",
            Username: "Bob",
            AlternateUsernames: Array.Empty<string>(),
            Status: ContactStatus.Accepted,
            IsAccepted: true,
            IsContactRequest: false,
            OnlineStatus: OnlineStatus.Online,
            CurrentSessionName: "",
            CurrentSessionAccessLevel: ""
        );

    public List<string> Calls { get; } = new();

    /// <summary>最後に user_id を取る RPC に渡された user_id。未呼び出しなら null。</summary>
    public string? LastUserId { get; private set; }

    /// <summary>最後に <see cref="AddContactAsync"/> に渡された username。未呼び出しなら null。</summary>
    public string? LastUsername { get; private set; }

    /// <summary>最後に <see cref="SearchUsersAsync"/> に渡された query。未呼び出しなら null。</summary>
    public string? LastQuery { get; private set; }

    /// <summary>最後に <see cref="SearchUsersAsync"/> に渡された exact_match。未呼び出しなら null。</summary>
    public bool? LastExactMatch { get; private set; }

    public bool ThrowNotReady { get; set; }
    public bool ThrowNotFound { get; set; }
    public bool ThrowOperation { get; set; }

    public Task<ContactListSnapshot> ListContactsAsync(CancellationToken ct)
    {
        Calls.Add("ListContacts");
        TripIfArmed();
        return Task.FromResult(ListResult);
    }

    public Task<ContactSnapshot?> GetContactAsync(string userId, CancellationToken ct)
    {
        Calls.Add("GetContact");
        LastUserId = userId;
        TripIfArmed();
        return Task.FromResult(GetResult);
    }

    public Task<IReadOnlyList<UserSearchSnapshot>> SearchUsersAsync(
        string query,
        bool exactMatch,
        CancellationToken ct
    )
    {
        Calls.Add("SearchUsers");
        LastQuery = query;
        LastExactMatch = exactMatch;
        TripIfArmed();
        return Task.FromResult(SearchResult);
    }

    public Task<ContactSnapshot> AddContactAsync(
        string userId,
        string username,
        CancellationToken ct
    )
    {
        Calls.Add("AddContact");
        LastUserId = userId;
        LastUsername = username;
        TripIfArmed();
        return Task.FromResult(AddResult);
    }

    public Task<ContactSnapshot> AcceptRequestAsync(string userId, CancellationToken ct)
    {
        Calls.Add("AcceptRequest");
        LastUserId = userId;
        TripIfArmed();
        return Task.FromResult(AcceptResult);
    }

    public Task RemoveContactAsync(string userId, CancellationToken ct)
    {
        Calls.Add("RemoveContact");
        LastUserId = userId;
        TripIfArmed();
        return Task.CompletedTask;
    }

    private void TripIfArmed()
    {
        if (ThrowNotReady)
        {
            throw new ContactNotReadyException("cloud not ready");
        }
        if (ThrowNotFound)
        {
            throw new ContactNotFoundException("no such contact");
        }
        if (ThrowOperation)
        {
            throw new ContactOperationException("cloud operation failed");
        }
    }
}
