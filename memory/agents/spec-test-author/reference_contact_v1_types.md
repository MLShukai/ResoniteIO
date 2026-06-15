---
name: contact-v1-types
description: Exact ResoniteIO.V1.* generated type names for the Contact modality, as pinned in ApiContractTests V1 snapshot
metadata:
  type: reference
---

Contact modality の `ResoniteIO.V1.*` 生成型一覧 (`ApiContractTests.ResoniteIOV1_GeneratedProtoTypes_MatchSnapshot` の expected に Ordinal 順で入れる)。csharp protobuf 生成物 `obj/.../resonite_io/v1/Contact.cs` / `ContactGrpc.cs` を読んで実測した値。

- Service / reflection / server base:
  - `ResoniteIO.V1.Contact` (static partial class)
  - `ResoniteIO.V1.Contact+ContactBase` (server stub; `+` は Ordinal で letter より前 → `ContactFilter` の直前)
  - `ResoniteIO.V1.ContactReflection`
- enum: `ResoniteIO.V1.ContactStatus` / `ResoniteIO.V1.OnlineStatus` / `ResoniteIO.V1.ContactFilter`
  - PascalCase values (prefix 剥がれ): ContactStatus = Unspecified/None/SearchResult/Requested/Ignored/Blocked/Accepted (0..6); OnlineStatus = Unspecified/Offline/Invisible/Away/Busy/Online/Sociable; ContactFilter = Unspecified/Accepted/Requests
- message: `ContactInfo`, `UserSearchResult`, `ListContactsRequest`, `ListContactsResponse`, `GetContactRequest`, `GetContactResponse`, `SearchUsersRequest`, `SearchUsersResponse`, `AddContactRequest`, `AddContactResponse`, `AcceptRequestRequest`, `AcceptRequestResponse`, `RemoveContactRequest`, `RemoveContactResponse`

連絡先 message は service 名 `Contact` と衝突回避で `ContactInfo`。client RPC method 名: ListContactsAsync / GetContactAsync / SearchUsersAsync / AddContactAsync / AcceptRequestAsync / RemoveContactAsync.

See \[\[core-tests-grpc-gen-split\]\].
