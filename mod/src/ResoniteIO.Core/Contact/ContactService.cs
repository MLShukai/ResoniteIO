using Grpc.Core;
using ResoniteIO.Core.Logging;
using ResoniteIO.Core.Rpc;

namespace ResoniteIO.Core.Contact;

/// <summary><c>resonite_io.v1.Contact</c> サービスの Core 実装。</summary>
/// <remarks>
/// <see cref="IContactBridge"/> は optional DI: null なら <c>Unavailable</c> を返し、
/// Core 単体テストや contact 非対応 engine 構成も成立させる (SessionService と同 pattern)。
/// 各 RPC は engine を知らず、proto を Core POCO に変換して bridge に渡すだけ。
/// search / filter は <c>ListContacts</c> でのみ Service 側で適用する。例外翻訳は
/// <see cref="ContactNotReadyException"/> → <c>FailedPrecondition</c>、
/// <see cref="ContactNotFoundException"/> → <c>NotFound</c>、
/// <see cref="ContactOperationException"/> → <c>Internal</c>、その他 → <c>Internal</c>。
/// </remarks>
public sealed class ContactService : V1.Contact.ContactBase
{
    private readonly IContactBridge? _bridge;
    private readonly ILogSink _log;

    public ContactService(ILogSink log, IContactBridge? bridge = null)
    {
        _log = log;
        _bridge = bridge;
    }

    public override async Task<V1.ListContactsResponse> ListContacts(
        V1.ListContactsRequest request,
        ServerCallContext context
    )
    {
        var bridge = RequireBridge("ListContacts");
        var snapshot = await InvokeBridge(
                "ListContacts",
                ct => bridge.ListContactsAsync(ct),
                context.CancellationToken
            )
            .ConfigureAwait(false);

        // filter は Service 側で適用する。Accepted=承認済みのみ、Requests=受信リクエストのみ、
        // Unspecified=全件。counts は filter / search 前の総数なので上書きしない。
        IEnumerable<ContactSnapshot> contacts = request.Filter switch
        {
            V1.ContactFilter.Accepted => snapshot.Contacts.Where(c =>
                c.Status == ContactStatus.Accepted
            ),
            V1.ContactFilter.Requests => snapshot.Contacts.Where(c => c.IsContactRequest),
            _ => snapshot.Contacts,
        };

        // search が非空なら username / alternate_usernames に部分一致するものだけ残す。
        if (!string.IsNullOrEmpty(request.Search))
        {
            var search = request.Search;
            contacts = contacts.Where(c =>
                c.Username.Contains(search, StringComparison.OrdinalIgnoreCase)
                || c.AlternateUsernames.Any(a =>
                    a.Contains(search, StringComparison.OrdinalIgnoreCase)
                )
            );
        }

        var response = new V1.ListContactsResponse
        {
            ContactCount = snapshot.ContactCount,
            RequestCount = snapshot.RequestCount,
            ListLoaded = snapshot.ListLoaded,
        };
        foreach (var contact in contacts)
        {
            response.Contacts.Add(ToProto(contact));
        }

        return response;
    }

    public override async Task<V1.GetContactResponse> GetContact(
        V1.GetContactRequest request,
        ServerCallContext context
    )
    {
        var bridge = RequireBridge("GetContact");
        var snapshot = await InvokeBridge(
                "GetContact",
                ct => bridge.GetContactAsync(request.UserId, ct),
                context.CancellationToken
            )
            .ConfigureAwait(false);

        if (snapshot is null)
        {
            return new V1.GetContactResponse { Found = false };
        }

        return new V1.GetContactResponse { Found = true, Contact = ToProto(snapshot) };
    }

    public override async Task<V1.SearchUsersResponse> SearchUsers(
        V1.SearchUsersRequest request,
        ServerCallContext context
    )
    {
        var bridge = RequireBridge("SearchUsers");
        var results = await InvokeBridge(
                "SearchUsers",
                ct => bridge.SearchUsersAsync(request.Query, request.ExactMatch, ct),
                context.CancellationToken
            )
            .ConfigureAwait(false);

        var response = new V1.SearchUsersResponse();
        foreach (var result in results)
        {
            response.Results.Add(ToProto(result));
        }

        return response;
    }

    public override async Task<V1.AddContactResponse> AddContact(
        V1.AddContactRequest request,
        ServerCallContext context
    )
    {
        var bridge = RequireBridge("AddContact");
        var snapshot = await InvokeBridge(
                "AddContact",
                ct => bridge.AddContactAsync(request.UserId, request.Username, ct),
                context.CancellationToken
            )
            .ConfigureAwait(false);

        return new V1.AddContactResponse { Contact = ToProto(snapshot) };
    }

    public override async Task<V1.AcceptRequestResponse> AcceptRequest(
        V1.AcceptRequestRequest request,
        ServerCallContext context
    )
    {
        var bridge = RequireBridge("AcceptRequest");
        var snapshot = await InvokeBridge(
                "AcceptRequest",
                ct => bridge.AcceptRequestAsync(request.UserId, ct),
                context.CancellationToken
            )
            .ConfigureAwait(false);

        return new V1.AcceptRequestResponse { Contact = ToProto(snapshot) };
    }

    public override async Task<V1.RemoveContactResponse> RemoveContact(
        V1.RemoveContactRequest request,
        ServerCallContext context
    )
    {
        var bridge = RequireBridge("RemoveContact");

        await InvokeBridge(
                "RemoveContact",
                async ct =>
                {
                    await bridge.RemoveContactAsync(request.UserId, ct).ConfigureAwait(false);
                    return true;
                },
                context.CancellationToken
            )
            .ConfigureAwait(false);

        return new V1.RemoveContactResponse();
    }

    private IContactBridge RequireBridge(string rpc) =>
        BridgeGuard.Require(_bridge, _log, "Contact", "IContactBridge", rpc);

    /// <summary>
    /// 全 RPC 共通の例外翻訳。Contact は複数の戻り型を返すため generic 化 (SessionService と同形)。
    /// </summary>
    private Task<T> InvokeBridge<T>(
        string rpc,
        Func<CancellationToken, Task<T>> call,
        CancellationToken ct
    ) => BridgeFault.InvokeAsync(_log, "Contact", rpc, call, ct, ex => Translate(rpc, ex));

    private RpcException? Translate(string rpc, Exception ex)
    {
        switch (ex)
        {
            case ContactNotReadyException notReady:
                return BridgeFault.Translate(
                    _log,
                    "Contact",
                    rpc,
                    StatusCode.FailedPrecondition,
                    "bridge not ready",
                    notReady
                );
            case ContactNotFoundException notFound:
                return BridgeFault.Translate(
                    _log,
                    "Contact",
                    rpc,
                    StatusCode.NotFound,
                    "contact not found",
                    notFound
                );
            case ContactOperationException operation:
                return BridgeFault.Translate(
                    _log,
                    "Contact",
                    rpc,
                    StatusCode.Internal,
                    "contact operation failed",
                    operation
                );
            default:
                return null;
        }
    }

    private static V1.ContactInfo ToProto(ContactSnapshot s)
    {
        var info = new V1.ContactInfo
        {
            UserId = s.UserId,
            Username = s.Username,
            Status = MapStatus(s.Status),
            IsAccepted = s.IsAccepted,
            IsContactRequest = s.IsContactRequest,
            OnlineStatus = MapOnline(s.OnlineStatus),
            CurrentSessionName = s.CurrentSessionName,
            CurrentSessionAccessLevel = s.CurrentSessionAccessLevel,
        };
        info.AlternateUsernames.AddRange(s.AlternateUsernames);
        return info;
    }

    private static V1.UserSearchResult ToProto(UserSearchSnapshot u) =>
        new()
        {
            UserId = u.UserId,
            Username = u.Username,
            IsVerified = u.IsVerified,
        };

    private static V1.ContactStatus MapStatus(ContactStatus s) =>
        s switch
        {
            ContactStatus.None => V1.ContactStatus.None,
            ContactStatus.SearchResult => V1.ContactStatus.SearchResult,
            ContactStatus.Requested => V1.ContactStatus.Requested,
            ContactStatus.Ignored => V1.ContactStatus.Ignored,
            ContactStatus.Blocked => V1.ContactStatus.Blocked,
            ContactStatus.Accepted => V1.ContactStatus.Accepted,
            _ => V1.ContactStatus.Unspecified,
        };

    private static V1.OnlineStatus MapOnline(OnlineStatus s) =>
        s switch
        {
            OnlineStatus.Offline => V1.OnlineStatus.Offline,
            OnlineStatus.Invisible => V1.OnlineStatus.Invisible,
            OnlineStatus.Away => V1.OnlineStatus.Away,
            OnlineStatus.Busy => V1.OnlineStatus.Busy,
            OnlineStatus.Online => V1.OnlineStatus.Online,
            OnlineStatus.Sociable => V1.OnlineStatus.Sociable,
            _ => V1.OnlineStatus.Unspecified,
        };
}
