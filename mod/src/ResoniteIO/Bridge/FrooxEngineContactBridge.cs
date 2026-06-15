using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using FrooxEngine;
using ResoniteIO.Core.Contact;
using ResoniteIO.Core.Logging;
using SkyFrost.Base;
using CoreContactStatus = ResoniteIO.Core.Contact.ContactStatus;
using CoreOnlineStatus = ResoniteIO.Core.Contact.OnlineStatus;
using EngineContactStatus = SkyFrost.Base.ContactStatus;
using EngineOnlineStatus = SkyFrost.Base.OnlineStatus;
using EngineUser = SkyFrost.Base.User;

namespace ResoniteIO.Bridge;

/// <summary>
/// ローカルユーザの連絡先 (<see cref="Engine.Cloud"/> の <c>Contacts</c> / <c>Users</c>) を
/// 直接操作する <see cref="IContactBridge"/> 実装。
/// </summary>
/// <remarks>
/// <para>
/// 一覧 / 単一取得は <see cref="ContactManager"/> の cloud 同期キャッシュ
/// (<c>ForeachContactData</c> / <c>GetContact</c>) を read するだけで、検索 / 追加 / 承認 /
/// 削除は <see cref="UsersManager"/> / <see cref="ContactManager"/> の非同期 cloud write を
/// await する。<see cref="ContactManager"/> は内部 lock で thread-safe、<see cref="UsersManager"/>
/// は async cloud I/O なので、ここでは engine update thread への marshal を行わない
/// (FrooxEngineWorldBridge の read-only cloud 呼び出しと同じ扱い)。
/// </para>
/// <para>
/// cloud が未準備 (未ログイン等) のときは <see cref="ContactNotReadyException"/>、指定
/// user_id の連絡先 / ユーザーが見つからないときは <see cref="ContactNotFoundException"/>、
/// cloud の追加 / 承認 / 削除操作が失敗したときは <see cref="ContactOperationException"/> を
/// 投げ、Service 層がそれぞれ FailedPrecondition / NotFound / Internal に翻訳する。
/// </para>
/// </remarks>
internal sealed class FrooxEngineContactBridge : IContactBridge
{
    private readonly Engine _engine;
    private readonly ILogSink _log;

    public FrooxEngineContactBridge(Engine engine, ILogSink log)
    {
        ArgumentNullException.ThrowIfNull(engine);
        ArgumentNullException.ThrowIfNull(log);
        _engine = engine;
        _log = log;
    }

    /// <inheritdoc/>
    public Task<ContactListSnapshot> ListContactsAsync(CancellationToken ct)
    {
        ct.ThrowIfCancellationRequested();
        var contacts = RequireContacts();

        var snapshots = new List<ContactSnapshot>();
        contacts.ForeachContactData(data =>
        {
            if (data?.Contact is null)
            {
                return;
            }
            snapshots.Add(BuildSnapshot(data.Contact, data));
        });

        var snapshot = new ContactListSnapshot(
            Contacts: snapshots,
            ContactCount: contacts.ContactCount,
            RequestCount: contacts.ContactRequestCount,
            ListLoaded: contacts.ContactListLoaded
        );
        return Task.FromResult(snapshot);
    }

    /// <inheritdoc/>
    public Task<ContactSnapshot?> GetContactAsync(string userId, CancellationToken ct)
    {
        ct.ThrowIfCancellationRequested();
        ArgumentNullException.ThrowIfNull(userId);
        var contacts = RequireContacts();

        var contact = contacts.GetContact(userId);
        if (contact is null)
        {
            return Task.FromResult<ContactSnapshot?>(null);
        }

        var data = FindContactData(contacts, userId);
        return Task.FromResult<ContactSnapshot?>(BuildSnapshot(contact, data));
    }

    /// <inheritdoc/>
    public async Task<IReadOnlyList<UserSearchSnapshot>> SearchUsersAsync(
        string query,
        bool exactMatch,
        CancellationToken ct
    )
    {
        ct.ThrowIfCancellationRequested();
        ArgumentNullException.ThrowIfNull(query);
        var users = RequireUsers();

        var results = new List<UserSearchSnapshot>();
        if (exactMatch)
        {
            var single = await users.GetUserByName(query).ConfigureAwait(false);
            if (single.IsOK && single.Entity is { } user)
            {
                results.Add(ToSearchSnapshot(user));
            }
            return results;
        }

        var many = await users.GetUsers(query).ConfigureAwait(false);
        if (many.IsError || many.Entity is null)
        {
            return results;
        }
        foreach (var user in many.Entity)
        {
            if (user is null)
            {
                continue;
            }
            results.Add(ToSearchSnapshot(user));
        }
        return results;
    }

    /// <inheritdoc/>
    public async Task<ContactSnapshot> AddContactAsync(
        string userId,
        string username,
        CancellationToken ct
    )
    {
        ct.ThrowIfCancellationRequested();
        ArgumentNullException.ThrowIfNull(userId);
        ArgumentNullException.ThrowIfNull(username);
        var contacts = RequireContacts();

        var resolvedName = username;
        if (string.IsNullOrEmpty(resolvedName))
        {
            var users = RequireUsers();
            var fetched = await users.GetUser(userId).ConfigureAwait(false);
            if (fetched.IsError || fetched.Entity is null)
            {
                throw new ContactNotFoundException(
                    $"User '{userId}' was not found in the cloud ({fetched.State})."
                );
            }
            resolvedName = fetched.Entity.Username ?? string.Empty;
        }

        var added = await contacts.AddContact(userId, resolvedName).ConfigureAwait(false);
        if (!added)
        {
            throw new ContactOperationException($"The cloud rejected adding contact '{userId}'.");
        }
        _log.LogInfo($"[ResoniteIO] Contact.Add: {userId}");

        return ReadSnapshotOrMinimal(contacts, userId, resolvedName);
    }

    /// <inheritdoc/>
    public async Task<ContactSnapshot> AcceptRequestAsync(string userId, CancellationToken ct)
    {
        ct.ThrowIfCancellationRequested();
        ArgumentNullException.ThrowIfNull(userId);
        var contacts = RequireContacts();

        var contact = contacts.GetContact(userId);
        if (contact is null)
        {
            throw new ContactNotFoundException($"No contact with id '{userId}' exists.");
        }

        var accepted = await contacts.AddContact(contact).ConfigureAwait(false);
        if (!accepted)
        {
            throw new ContactOperationException(
                $"The cloud rejected accepting the request from '{userId}'."
            );
        }
        _log.LogInfo($"[ResoniteIO] Contact.Accept: {userId}");

        return ReadSnapshotOrMinimal(contacts, userId, contact.ContactUsername ?? string.Empty);
    }

    /// <inheritdoc/>
    public async Task RemoveContactAsync(string userId, CancellationToken ct)
    {
        ct.ThrowIfCancellationRequested();
        ArgumentNullException.ThrowIfNull(userId);
        var contacts = RequireContacts();

        var contact = contacts.GetContact(userId);
        if (contact is null)
        {
            throw new ContactNotFoundException($"No contact with id '{userId}' exists.");
        }

        // 受信中のフレンドリクエストは拒否 (IgnoreRequest)、確立済み連絡先は削除 (RemoveContact)。
        // engine 上はどちらも status を Ignored にして送る同じ経路だが、意味を区別して呼ぶ。
        var removed = contact.IsContactRequest
            ? await contacts.IgnoreRequest(contact).ConfigureAwait(false)
            : await contacts.RemoveContact(contact).ConfigureAwait(false);
        if (!removed)
        {
            throw new ContactOperationException($"The cloud rejected removing contact '{userId}'.");
        }
        _log.LogInfo($"[ResoniteIO] Contact.Remove: {userId}");
    }

    // ---- cloud accessors ---------------------------------------------------

    private ContactManager RequireContacts()
    {
        var contacts = _engine.Cloud?.Contacts;
        if (contacts is null)
        {
            throw new ContactNotReadyException(
                "The contact cloud is not available yet (engine may still be initializing "
                    + "or not signed in)."
            );
        }
        return contacts;
    }

    private UsersManager RequireUsers()
    {
        var users = _engine.Cloud?.Users;
        if (users is null)
        {
            throw new ContactNotReadyException(
                "The user cloud is not available yet (engine may still be initializing "
                    + "or not signed in)."
            );
        }
        return users;
    }

    /// <summary>
    /// write 後に <c>GetContact</c> を read し直して snapshot を組む。キャッシュ反映がまだなら
    /// (cloud write は非同期に push されるため一時的に null になり得る) 最小 snapshot を返す。
    /// </summary>
    private ContactSnapshot ReadSnapshotOrMinimal(
        ContactManager contacts,
        string userId,
        string username
    )
    {
        var contact = contacts.GetContact(userId);
        if (contact is null)
        {
            return new ContactSnapshot(
                UserId: userId,
                Username: username,
                AlternateUsernames: Array.Empty<string>(),
                Status: CoreContactStatus.Accepted,
                IsAccepted: true,
                IsContactRequest: false,
                OnlineStatus: CoreOnlineStatus.Offline,
                CurrentSessionName: string.Empty,
                CurrentSessionAccessLevel: string.Empty
            );
        }
        return BuildSnapshot(contact, FindContactData(contacts, userId));
    }

    /// <summary>同じ ContactUserId の <see cref="ContactData"/> を presence 用に探す (無ければ null)。</summary>
    private static ContactData? FindContactData(ContactManager contacts, string userId)
    {
        ContactData? found = null;
        contacts.ForeachContactData(data =>
        {
            if (
                found is null
                && data?.Contact is not null
                && string.Equals(data.Contact.ContactUserId, userId, StringComparison.Ordinal)
            )
            {
                found = data;
            }
        });
        return found;
    }

    // ---- snapshot builders -------------------------------------------------

    /// <summary>
    /// <paramref name="contact"/> と (あれば) <paramref name="data"/> の presence から
    /// <see cref="ContactSnapshot"/> を組む。<paramref name="data"/> が無ければ presence は
    /// Offline / 空とする。
    /// </summary>
    private static ContactSnapshot BuildSnapshot(Contact contact, ContactData? data)
    {
        var online = EngineOnlineStatus.Offline;
        var sessionName = string.Empty;
        var sessionAccessLevel = string.Empty;

        if (data is not null)
        {
            online = data.CurrentStatus?.OnlineStatus ?? EngineOnlineStatus.Offline;
            var session = data.CurrentSessionInfo;
            if (session is not null)
            {
                sessionName = session.Name ?? string.Empty;
                sessionAccessLevel = session.AccessLevel.ToString();
            }
        }

        return new ContactSnapshot(
            UserId: contact.ContactUserId ?? string.Empty,
            Username: contact.ContactUsername ?? string.Empty,
            AlternateUsernames: contact.AlternateUsernames?.ToArray() ?? Array.Empty<string>(),
            Status: MapStatus(contact.ContactStatus),
            IsAccepted: contact.IsAccepted,
            IsContactRequest: contact.IsContactRequest,
            OnlineStatus: MapOnline(online),
            CurrentSessionName: sessionName,
            CurrentSessionAccessLevel: sessionAccessLevel
        );
    }

    private static UserSearchSnapshot ToSearchSnapshot(EngineUser user) =>
        new(user.Id ?? string.Empty, user.Username ?? string.Empty, user.IsVerified);

    // ---- enum mapping ------------------------------------------------------

    /// <summary>engine の連絡先ステータスを Core <c>ContactStatus</c> に 1:1 で写す。</summary>
    private static CoreContactStatus MapStatus(EngineContactStatus status) =>
        status switch
        {
            EngineContactStatus.None => CoreContactStatus.None,
            EngineContactStatus.SearchResult => CoreContactStatus.SearchResult,
            EngineContactStatus.Requested => CoreContactStatus.Requested,
            EngineContactStatus.Ignored => CoreContactStatus.Ignored,
            EngineContactStatus.Blocked => CoreContactStatus.Blocked,
            EngineContactStatus.Accepted => CoreContactStatus.Accepted,
            _ => CoreContactStatus.None,
        };

    /// <summary>engine の presence を Core <c>OnlineStatus</c> に 1:1 で写す。</summary>
    private static CoreOnlineStatus MapOnline(EngineOnlineStatus status) =>
        status switch
        {
            EngineOnlineStatus.Offline => CoreOnlineStatus.Offline,
            EngineOnlineStatus.Invisible => CoreOnlineStatus.Invisible,
            EngineOnlineStatus.Away => CoreOnlineStatus.Away,
            EngineOnlineStatus.Busy => CoreOnlineStatus.Busy,
            EngineOnlineStatus.Online => CoreOnlineStatus.Online,
            EngineOnlineStatus.Sociable => CoreOnlineStatus.Sociable,
            _ => CoreOnlineStatus.Offline,
        };
}
