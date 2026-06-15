using Grpc.Core;
using ResoniteIO.Core.Contact;
using ResoniteIO.Core.Tests.Common;
using ResoniteIO.Core.Tests.Common.Fakes;
using ResoniteIO.V1;
using Xunit;

namespace ResoniteIO.Core.Tests.Contact;

/// <summary>
/// <see cref="Core.Contact.ContactService"/> の各 RPC を実 Kestrel + UDS wire 越しに検証する。
/// </summary>
/// <remarks>
/// <para>
/// 仕様 (contact.proto + IContactBridge 契約) を正典とする。とくに本 modality の核心である
/// <b>search / filter の Service 側適用</b> (counts は ContactManager の snapshot 値をそのまま返す)
/// と、presence / status enum の wire 往復を end-to-end で assert する。
/// </para>
/// <para>
/// 例外翻訳は ContactNotReadyException→FailedPrecondition / ContactNotFoundException→NotFound /
/// ContactOperationException→Internal、bridge 未登録→Unavailable を <see cref="RpcException.StatusCode"/>
/// で検証する (SessionServiceTests と同じ作法)。
/// </para>
/// </remarks>
public sealed class ContactServiceTests
{
    // ===================================================================
    //  ListContacts — round-trip (presence / status enum) + counts
    // ===================================================================

    [Fact]
    public async Task ListContacts_round_trips_all_contacts_with_status_and_online_status_enums()
    {
        var bridge = new FakeContactBridge();
        await using var host = await ContactServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Contact.ContactClient(channel);

        var response = await client.ListContactsAsync(new ListContactsRequest());

        // 既定 Fake は Accepted な Alice と Requested な Bob を持つ → filter なしで 2 件。
        Assert.Equal(2, response.Contacts.Count);

        var alice = Assert.Single(response.Contacts, c => c.UserId == "U-alice");
        Assert.Equal("Alice", alice.Username);
        Assert.Equal(new[] { "AliceAlt" }, alice.AlternateUsernames);
        Assert.Equal(V1.ContactStatus.Accepted, alice.Status);
        Assert.True(alice.IsAccepted);
        Assert.False(alice.IsContactRequest);
        Assert.Equal(V1.OnlineStatus.Online, alice.OnlineStatus);
        Assert.Equal("Home", alice.CurrentSessionName);
        Assert.Equal("Private", alice.CurrentSessionAccessLevel);

        var bob = Assert.Single(response.Contacts, c => c.UserId == "U-bob");
        Assert.Equal(V1.ContactStatus.Requested, bob.Status);
        Assert.True(bob.IsContactRequest);
        Assert.Equal(V1.OnlineStatus.Away, bob.OnlineStatus);
    }

    [Fact]
    public async Task ListContacts_with_no_filter_returns_counts_from_bridge_snapshot()
    {
        var bridge = new FakeContactBridge();
        await using var host = await ContactServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Contact.ContactClient(channel);

        var response = await client.ListContactsAsync(new ListContactsRequest());

        // counts は ContactManager (bridge snapshot) の値をそのまま返す契約。
        Assert.Equal(1, response.ContactCount);
        Assert.Equal(1, response.RequestCount);
        Assert.True(response.ListLoaded);
    }

    [Fact]
    public async Task ListContacts_with_filter_accepted_returns_only_accepted_status_contacts()
    {
        var bridge = new FakeContactBridge();
        await using var host = await ContactServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Contact.ContactClient(channel);

        var response = await client.ListContactsAsync(
            new ListContactsRequest { Filter = V1.ContactFilter.Accepted }
        );

        // filter=Accepted は Status==Accepted のみ (Alice のみ、Bob は Requested で除外)。
        var contact = Assert.Single(response.Contacts);
        Assert.Equal("U-alice", contact.UserId);
        Assert.Equal(V1.ContactStatus.Accepted, contact.Status);
    }

    [Fact]
    public async Task ListContacts_with_filter_requests_returns_only_contact_request_entries()
    {
        var bridge = new FakeContactBridge();
        await using var host = await ContactServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Contact.ContactClient(channel);

        var response = await client.ListContactsAsync(
            new ListContactsRequest { Filter = V1.ContactFilter.Requests }
        );

        // filter=Requests は IsContactRequest==true のみ (Bob のみ)。
        var contact = Assert.Single(response.Contacts);
        Assert.Equal("U-bob", contact.UserId);
        Assert.True(contact.IsContactRequest);
    }

    [Fact]
    public async Task ListContacts_filter_does_not_alter_counts_which_stay_snapshot_values()
    {
        var bridge = new FakeContactBridge();
        await using var host = await ContactServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Contact.ContactClient(channel);

        var response = await client.ListContactsAsync(
            new ListContactsRequest { Filter = V1.ContactFilter.Accepted }
        );

        // filter で contacts は 1 件に絞られても、counts は snapshot 値 (filter/search 適用前) のまま。
        Assert.Single(response.Contacts);
        Assert.Equal(1, response.ContactCount);
        Assert.Equal(1, response.RequestCount);
        Assert.True(response.ListLoaded);
    }

    [Fact]
    public async Task ListContacts_search_matches_username_substring_case_insensitively()
    {
        var bridge = new FakeContactBridge();
        await using var host = await ContactServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Contact.ContactClient(channel);

        // "ali" は Alice.Username "Alice" に大小文字無視で部分一致、Bob は不一致。
        var response = await client.ListContactsAsync(new ListContactsRequest { Search = "ali" });

        var contact = Assert.Single(response.Contacts);
        Assert.Equal("U-alice", contact.UserId);
    }

    [Fact]
    public async Task ListContacts_search_matches_alternate_usernames_substring()
    {
        var bridge = new FakeContactBridge();
        await using var host = await ContactServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Contact.ContactClient(channel);

        // "alicealt" は Username では一致しないが、AlternateUsernames "AliceAlt" に部分一致。
        var response = await client.ListContactsAsync(
            new ListContactsRequest { Search = "alicealt" }
        );

        var contact = Assert.Single(response.Contacts);
        Assert.Equal("U-alice", contact.UserId);
    }

    [Fact]
    public async Task ListContacts_search_with_no_match_returns_empty_but_keeps_counts()
    {
        var bridge = new FakeContactBridge();
        await using var host = await ContactServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Contact.ContactClient(channel);

        var response = await client.ListContactsAsync(
            new ListContactsRequest { Search = "no-such-name" }
        );

        Assert.Empty(response.Contacts);
        // search で 0 件でも counts は snapshot 値のまま。
        Assert.Equal(1, response.ContactCount);
        Assert.Equal(1, response.RequestCount);
    }

    // ===================================================================
    //  ListContacts — hidden (dash-hidden None/Ignored/Blocked) exclusion
    //
    //  仕様: ListContacts は既定で IsHidden==true の snapshot を除外し、
    //  include_hidden=true でのみ全件返す。除外は filter / search より先に
    //  効き、ContactInfo.is_hidden は wire を往復し、counts は snapshot 値のまま。
    // ===================================================================

    /// <summary>
    /// 既定 Fake の Alice/Bob (どちらも IsHidden==false) に、IsHidden==true の連絡先を
    /// 1 件足した snapshot を仕込む。hidden は Accepted 扱いにして「hidden な Accepted は
    /// ACCEPTED filter でも出ない」ケースまで検証できるようにする。
    /// </summary>
    private static FakeContactBridge BridgeWithHiddenContact()
    {
        var bridge = new FakeContactBridge
        {
            ListResult = new ContactListSnapshot(
                Contacts: new[]
                {
                    new ContactSnapshot(
                        UserId: "U-alice",
                        Username: "Alice",
                        AlternateUsernames: Array.Empty<string>(),
                        Status: Core.Contact.ContactStatus.Accepted,
                        IsAccepted: true,
                        IsContactRequest: false,
                        OnlineStatus: Core.Contact.OnlineStatus.Online,
                        CurrentSessionName: "",
                        CurrentSessionAccessLevel: "",
                        IsHidden: false
                    ),
                    new ContactSnapshot(
                        UserId: "U-blocked",
                        Username: "Blocked",
                        AlternateUsernames: Array.Empty<string>(),
                        Status: Core.Contact.ContactStatus.Accepted,
                        IsAccepted: true,
                        IsContactRequest: false,
                        OnlineStatus: Core.Contact.OnlineStatus.Offline,
                        CurrentSessionName: "",
                        CurrentSessionAccessLevel: "",
                        IsHidden: true
                    ),
                },
                ContactCount: 2,
                RequestCount: 0,
                ListLoaded: true
            ),
        };
        return bridge;
    }

    [Fact]
    public async Task ListContacts_default_excludes_hidden_contacts()
    {
        var bridge = BridgeWithHiddenContact();
        await using var host = await ContactServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Contact.ContactClient(channel);

        // include_hidden を立てない既定リクエスト。
        var response = await client.ListContactsAsync(new ListContactsRequest());

        // IsHidden==true の U-blocked は除外され、Alice のみ残る。
        var contact = Assert.Single(response.Contacts);
        Assert.Equal("U-alice", contact.UserId);
        Assert.DoesNotContain(response.Contacts, c => c.UserId == "U-blocked");
    }

    [Fact]
    public async Task ListContacts_with_include_hidden_returns_hidden_contacts_too()
    {
        var bridge = BridgeWithHiddenContact();
        await using var host = await ContactServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Contact.ContactClient(channel);

        var response = await client.ListContactsAsync(
            new ListContactsRequest { IncludeHidden = true }
        );

        // include_hidden=true なら hidden な U-blocked も含めて全件。
        Assert.Equal(2, response.Contacts.Count);
        Assert.Contains(response.Contacts, c => c.UserId == "U-alice");
        Assert.Contains(response.Contacts, c => c.UserId == "U-blocked");
    }

    [Fact]
    public async Task ListContacts_round_trips_is_hidden_flag_on_wire()
    {
        var bridge = BridgeWithHiddenContact();
        await using var host = await ContactServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Contact.ContactClient(channel);

        // include_hidden=true で hidden 連絡先を含めて取得し、is_hidden を観測する。
        var response = await client.ListContactsAsync(
            new ListContactsRequest { IncludeHidden = true }
        );

        var alice = Assert.Single(response.Contacts, c => c.UserId == "U-alice");
        Assert.False(alice.IsHidden);
        var blocked = Assert.Single(response.Contacts, c => c.UserId == "U-blocked");
        Assert.True(blocked.IsHidden);
    }

    [Fact]
    public async Task ListContacts_hidden_exclusion_does_not_alter_counts()
    {
        var bridge = BridgeWithHiddenContact();
        await using var host = await ContactServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Contact.ContactClient(channel);

        var response = await client.ListContactsAsync(new ListContactsRequest());

        // hidden 除外で contacts は 1 件に絞られても counts は snapshot 値のまま。
        Assert.Single(response.Contacts);
        Assert.Equal(2, response.ContactCount);
        Assert.Equal(0, response.RequestCount);
        Assert.True(response.ListLoaded);
    }

    [Fact]
    public async Task ListContacts_hidden_accepted_contact_is_absent_under_accepted_filter()
    {
        var bridge = BridgeWithHiddenContact();
        await using var host = await ContactServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Contact.ContactClient(channel);

        // U-blocked は Status==Accepted だが IsHidden==true。hidden 除外が filter より
        // 先に効くので、ACCEPTED filter でも hidden な Accepted は出てこない。
        var response = await client.ListContactsAsync(
            new ListContactsRequest { Filter = V1.ContactFilter.Accepted }
        );

        var contact = Assert.Single(response.Contacts);
        Assert.Equal("U-alice", contact.UserId);
        Assert.DoesNotContain(response.Contacts, c => c.UserId == "U-blocked");
    }

    [Fact]
    public async Task ListContacts_include_hidden_keeps_hidden_accepted_under_accepted_filter()
    {
        var bridge = BridgeWithHiddenContact();
        await using var host = await ContactServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Contact.ContactClient(channel);

        // include_hidden=true なら hidden 除外を飛ばすので、hidden な Accepted も
        // ACCEPTED filter を通る (両方 Accepted なので 2 件)。
        var response = await client.ListContactsAsync(
            new ListContactsRequest { IncludeHidden = true, Filter = V1.ContactFilter.Accepted }
        );

        Assert.Equal(2, response.Contacts.Count);
        Assert.Contains(response.Contacts, c => c.UserId == "U-alice");
        Assert.Contains(response.Contacts, c => c.UserId == "U-blocked");
    }

    // ===================================================================
    //  GetContact — found / not-found
    // ===================================================================

    [Fact]
    public async Task GetContact_with_known_user_returns_found_contact()
    {
        var bridge = new FakeContactBridge();
        await using var host = await ContactServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Contact.ContactClient(channel);

        var response = await client.GetContactAsync(new GetContactRequest { UserId = "U-alice" });

        Assert.True(response.Found);
        Assert.Equal("U-alice", response.Contact.UserId);
        Assert.Equal("Alice", response.Contact.Username);
        Assert.Equal(V1.OnlineStatus.Sociable, response.Contact.OnlineStatus);
        Assert.Equal("U-alice", bridge.LastUserId);
    }

    [Fact]
    public async Task GetContact_with_unknown_user_returns_found_false()
    {
        // bridge が null を返すと Service は found=false にする契約。
        var bridge = new FakeContactBridge { GetResult = null };
        await using var host = await ContactServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Contact.ContactClient(channel);

        var response = await client.GetContactAsync(new GetContactRequest { UserId = "U-nobody" });

        Assert.False(response.Found);
    }

    // ===================================================================
    //  SearchUsers — round-trip + exact_match flag propagation
    // ===================================================================

    [Fact]
    public async Task SearchUsers_round_trips_results_with_is_verified()
    {
        var bridge = new FakeContactBridge();
        await using var host = await ContactServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Contact.ContactClient(channel);

        var response = await client.SearchUsersAsync(new SearchUsersRequest { Query = "ca" });

        Assert.Equal(2, response.Results.Count);
        var carol = Assert.Single(response.Results, r => r.UserId == "U-carol");
        Assert.Equal("Carol", carol.Username);
        Assert.True(carol.IsVerified);

        var dave = Assert.Single(response.Results, r => r.UserId == "U-dave");
        Assert.False(dave.IsVerified);

        Assert.Equal("ca", bridge.LastQuery);
    }

    [Fact]
    public async Task SearchUsers_forwards_exact_match_true_to_bridge()
    {
        var bridge = new FakeContactBridge();
        await using var host = await ContactServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Contact.ContactClient(channel);

        await client.SearchUsersAsync(
            new SearchUsersRequest { Query = "Carol", ExactMatch = true }
        );

        Assert.True(bridge.LastExactMatch);
    }

    [Fact]
    public async Task SearchUsers_forwards_exact_match_false_to_bridge()
    {
        var bridge = new FakeContactBridge();
        await using var host = await ContactServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Contact.ContactClient(channel);

        await client.SearchUsersAsync(
            new SearchUsersRequest { Query = "Carol", ExactMatch = false }
        );

        Assert.False(bridge.LastExactMatch);
    }

    // ===================================================================
    //  AddContact — username present / omitted + returned contact
    // ===================================================================

    [Fact]
    public async Task AddContact_with_username_forwards_both_user_id_and_username()
    {
        var bridge = new FakeContactBridge();
        await using var host = await ContactServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Contact.ContactClient(channel);

        var response = await client.AddContactAsync(
            new AddContactRequest { UserId = "U-carol", Username = "Carol" }
        );

        Assert.Equal("U-carol", bridge.LastUserId);
        Assert.Equal("Carol", bridge.LastUsername);
        Assert.Equal("U-carol", response.Contact.UserId);
        Assert.True(response.Contact.IsAccepted);
        Assert.Equal(V1.ContactStatus.Accepted, response.Contact.Status);
    }

    [Fact]
    public async Task AddContact_without_username_forwards_empty_username()
    {
        // username 省略時は空文字が bridge に渡る (bridge 側が cloud から解決する契約)。
        var bridge = new FakeContactBridge();
        await using var host = await ContactServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Contact.ContactClient(channel);

        await client.AddContactAsync(new AddContactRequest { UserId = "U-carol" });

        Assert.Equal("U-carol", bridge.LastUserId);
        Assert.Equal("", bridge.LastUsername);
    }

    // ===================================================================
    //  AcceptRequest / RemoveContact — happy path
    // ===================================================================

    [Fact]
    public async Task AcceptRequest_forwards_user_id_and_returns_accepted_contact()
    {
        var bridge = new FakeContactBridge();
        await using var host = await ContactServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Contact.ContactClient(channel);

        var response = await client.AcceptRequestAsync(
            new AcceptRequestRequest { UserId = "U-bob" }
        );

        Assert.Equal("U-bob", bridge.LastUserId);
        Assert.Equal("U-bob", response.Contact.UserId);
        Assert.Equal(V1.ContactStatus.Accepted, response.Contact.Status);
        Assert.True(response.Contact.IsAccepted);
    }

    [Fact]
    public async Task RemoveContact_forwards_user_id()
    {
        var bridge = new FakeContactBridge();
        await using var host = await ContactServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Contact.ContactClient(channel);

        await client.RemoveContactAsync(new RemoveContactRequest { UserId = "U-bob" });

        Assert.Contains("RemoveContact", bridge.Calls);
        Assert.Equal("U-bob", bridge.LastUserId);
    }

    // ===================================================================
    //  Exception translation
    // ===================================================================

    [Fact]
    public async Task ListContacts_translates_ContactNotReadyException_to_FailedPrecondition()
    {
        var bridge = new FakeContactBridge { ThrowNotReady = true };
        await using var host = await ContactServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Contact.ContactClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.ListContactsAsync(new ListContactsRequest())
        );

        Assert.Equal(StatusCode.FailedPrecondition, ex.StatusCode);
    }

    [Fact]
    public async Task AddContact_translates_ContactNotFoundException_to_NotFound()
    {
        var bridge = new FakeContactBridge { ThrowNotFound = true };
        await using var host = await ContactServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Contact.ContactClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.AddContactAsync(new AddContactRequest { UserId = "U-nobody" })
        );

        Assert.Equal(StatusCode.NotFound, ex.StatusCode);
    }

    [Fact]
    public async Task AcceptRequest_translates_ContactOperationException_to_Internal()
    {
        var bridge = new FakeContactBridge { ThrowOperation = true };
        await using var host = await ContactServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Contact.ContactClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.AcceptRequestAsync(new AcceptRequestRequest { UserId = "U-bob" })
        );

        Assert.Equal(StatusCode.Internal, ex.StatusCode);
    }

    [Fact]
    public async Task RemoveContact_translates_ContactNotFoundException_to_NotFound()
    {
        var bridge = new FakeContactBridge { ThrowNotFound = true };
        await using var host = await ContactServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Contact.ContactClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.RemoveContactAsync(new RemoveContactRequest { UserId = "U-nobody" })
        );

        Assert.Equal(StatusCode.NotFound, ex.StatusCode);
    }

    // ===================================================================
    //  bridge == null -> Unavailable (representative RPCs)
    // ===================================================================

    [Fact]
    public async Task ListContacts_without_bridge_returns_Unavailable()
    {
        await using var host = await ContactServiceHost.StartAsync(bridge: null);
        using var channel = host.CreateChannel();
        var client = new V1.Contact.ContactClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.ListContactsAsync(new ListContactsRequest())
        );

        Assert.Equal(StatusCode.Unavailable, ex.StatusCode);
    }

    [Fact]
    public async Task AddContact_without_bridge_returns_Unavailable()
    {
        await using var host = await ContactServiceHost.StartAsync(bridge: null);
        using var channel = host.CreateChannel();
        var client = new V1.Contact.ContactClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.AddContactAsync(new AddContactRequest { UserId = "U-carol" })
        );

        Assert.Equal(StatusCode.Unavailable, ex.StatusCode);
    }
}
