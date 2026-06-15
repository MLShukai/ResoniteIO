using Grpc.Core;
using ResoniteIO.Core.Tests.Common;
using ResoniteIO.Core.Tests.Common.Fakes;
using ResoniteIO.V1;
using Xunit;

namespace ResoniteIO.Core.Tests.Session;

/// <summary>
/// <see cref="Core.Session.SessionService"/> の各 RPC を実 Kestrel + UDS wire 越しに検証する。
/// </summary>
/// <remarks>
/// 仕様 (session.proto + ISessionBridge 契約) を正典とする。とくに ApplySettings の
/// <b>explicit presence</b> (optional field の有無を bridge patch の null / non-null として観測) が
/// 本 modality の核心なので、Fake bridge に渡る Core POCO を直接 assert する。
/// </remarks>
public sealed class SessionServiceTests
{
    // ===================================================================
    //  GetSettings — full round-trip (enum / tags / meta)
    // ===================================================================

    [Fact]
    public async Task GetSettings_round_trips_all_fields_including_enum_tags_and_meta()
    {
        var bridge = new FakeSessionBridge();
        await using var host = await SessionServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Session.SessionClient(channel);

        var settings = await client.GetSettingsAsync(new GetSettingsRequest());

        Assert.Equal("Test World", settings.WorldName);
        Assert.Equal("a place", settings.WorldDescription);
        Assert.Equal(16, settings.MaxUsers);
        Assert.Equal(V1.SessionAccessLevel.Contacts, settings.AccessLevel);
        Assert.False(settings.HideFromListing);
        Assert.True(settings.MobileFriendly);
        Assert.Equal(new[] { "social", "test" }, settings.Tags);
        Assert.Equal("S-test-session", settings.SessionId);
        Assert.True(settings.IsHost);
    }

    // ===================================================================
    //  ApplySettings — explicit presence (the critical retro pins)
    // ===================================================================

    [Fact]
    public async Task ApplySettings_with_only_world_name_set_passes_world_name_and_leaves_others_null()
    {
        var bridge = new FakeSessionBridge();
        await using var host = await SessionServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Session.SessionClient(channel);

        await client.ApplySettingsAsync(new SessionSettingsPatch { WorldName = "Renamed" });

        var patch = Assert.IsType<Core.Session.SessionSettingsPatchSnapshot>(bridge.LastApplyPatch);
        Assert.Equal("Renamed", patch.WorldName);
        Assert.Null(patch.WorldDescription);
        Assert.Null(patch.MaxUsers);
        Assert.Null(patch.AccessLevel);
        Assert.Null(patch.HideFromListing);
        Assert.Null(patch.MobileFriendly);
        Assert.Null(patch.Tags);
    }

    [Fact]
    public async Task ApplySettings_with_explicit_false_hide_from_listing_passes_false_not_null()
    {
        // proto3 optional の核心: 0/false が有効値のため、明示 set した false が presence と
        // して bridge に届かなければならない (HasHideFromListing で判定される)。
        var bridge = new FakeSessionBridge();
        await using var host = await SessionServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Session.SessionClient(channel);

        await client.ApplySettingsAsync(new SessionSettingsPatch { HideFromListing = false });

        var patch = Assert.IsType<Core.Session.SessionSettingsPatchSnapshot>(bridge.LastApplyPatch);
        Assert.False(patch.HideFromListing);
        // 他は一切 set していないので変更しない (null)。
        Assert.Null(patch.WorldName);
        Assert.Null(patch.MobileFriendly);
    }

    [Fact]
    public async Task ApplySettings_with_explicit_zero_away_kick_minutes_passes_zero_not_null()
    {
        // float の 0 も有効値。明示した 0 が presence として bridge に届くこと。
        var bridge = new FakeSessionBridge();
        await using var host = await SessionServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Session.SessionClient(channel);

        await client.ApplySettingsAsync(new SessionSettingsPatch { AwayKickMinutes = 0f });

        var patch = Assert.IsType<Core.Session.SessionSettingsPatchSnapshot>(bridge.LastApplyPatch);
        Assert.Equal(0f, patch.AwayKickMinutes);
    }

    [Fact]
    public async Task ApplySettings_with_nothing_set_passes_all_null_patch()
    {
        var bridge = new FakeSessionBridge();
        await using var host = await SessionServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Session.SessionClient(channel);

        await client.ApplySettingsAsync(new SessionSettingsPatch());

        var patch = Assert.IsType<Core.Session.SessionSettingsPatchSnapshot>(bridge.LastApplyPatch);
        Assert.Null(patch.WorldName);
        Assert.Null(patch.WorldDescription);
        Assert.Null(patch.MaxUsers);
        Assert.Null(patch.AccessLevel);
        Assert.Null(patch.HideFromListing);
        Assert.Null(patch.MobileFriendly);
        Assert.Null(patch.AwayKickEnabled);
        Assert.Null(patch.AwayKickMinutes);
        Assert.Null(patch.AutoSaveEnabled);
        Assert.Null(patch.AutoSaveIntervalMinutes);
        Assert.Null(patch.AutoCleanupEnabled);
        Assert.Null(patch.AutoCleanupIntervalSeconds);
        Assert.Null(patch.Tags);
        Assert.Null(patch.ResoniteLinkEnabled);
    }

    // ===================================================================
    //  ApplySettings — access_level presence via UNSPECIFIED sentinel
    // ===================================================================

    [Fact]
    public async Task ApplySettings_with_unspecified_access_level_leaves_access_level_null()
    {
        var bridge = new FakeSessionBridge();
        await using var host = await SessionServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Session.SessionClient(channel);

        await client.ApplySettingsAsync(
            new SessionSettingsPatch { AccessLevel = V1.SessionAccessLevel.Unspecified }
        );

        var patch = Assert.IsType<Core.Session.SessionSettingsPatchSnapshot>(bridge.LastApplyPatch);
        Assert.Null(patch.AccessLevel);
    }

    [Fact]
    public async Task ApplySettings_with_concrete_access_level_maps_to_core_enum()
    {
        var bridge = new FakeSessionBridge();
        await using var host = await SessionServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Session.SessionClient(channel);

        await client.ApplySettingsAsync(
            new SessionSettingsPatch { AccessLevel = V1.SessionAccessLevel.Anyone }
        );

        var patch = Assert.IsType<Core.Session.SessionSettingsPatchSnapshot>(bridge.LastApplyPatch);
        Assert.Equal(Core.Session.SessionAccessLevel.Anyone, patch.AccessLevel);
    }

    // ===================================================================
    //  ApplySettings — tags replace gate
    // ===================================================================

    [Fact]
    public async Task ApplySettings_with_replace_tags_true_and_empty_list_passes_empty_non_null_tags()
    {
        // replace_tags=true, tags=[] は「全消し」セマンティクス → patch.Tags は空 list (non-null)。
        var bridge = new FakeSessionBridge();
        await using var host = await SessionServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Session.SessionClient(channel);

        await client.ApplySettingsAsync(new SessionSettingsPatch { ReplaceTags = true });

        var patch = Assert.IsType<Core.Session.SessionSettingsPatchSnapshot>(bridge.LastApplyPatch);
        Assert.NotNull(patch.Tags);
        Assert.Empty(patch.Tags);
    }

    [Fact]
    public async Task ApplySettings_with_replace_tags_true_and_values_passes_those_tags()
    {
        var bridge = new FakeSessionBridge();
        await using var host = await SessionServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Session.SessionClient(channel);

        var request = new SessionSettingsPatch { ReplaceTags = true };
        request.Tags.Add("game");
        request.Tags.Add("vr");
        await client.ApplySettingsAsync(request);

        var patch = Assert.IsType<Core.Session.SessionSettingsPatchSnapshot>(bridge.LastApplyPatch);
        Assert.Equal(new[] { "game", "vr" }, patch.Tags);
    }

    [Fact]
    public async Task ApplySettings_with_replace_tags_false_ignores_tags_and_passes_null()
    {
        // replace_tags=false なら tags フィールドは無視 → patch.Tags == null (変更しない)。
        var bridge = new FakeSessionBridge();
        await using var host = await SessionServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Session.SessionClient(channel);

        var request = new SessionSettingsPatch { ReplaceTags = false };
        request.Tags.Add("ignored");
        await client.ApplySettingsAsync(request);

        var patch = Assert.IsType<Core.Session.SessionSettingsPatchSnapshot>(bridge.LastApplyPatch);
        Assert.Null(patch.Tags);
    }

    // ===================================================================
    //  ResoniteLink — GetSettings state + ApplySettings enable/disable
    // ===================================================================

    [Fact]
    public async Task GetSettings_carries_resonite_link_disabled_state_with_zero_port()
    {
        // 既定 (未起動) では disabled かつ port=0 が snapshot に載る契約。
        var bridge = new FakeSessionBridge();
        await using var host = await SessionServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Session.SessionClient(channel);

        var settings = await client.GetSettingsAsync(new GetSettingsRequest());

        Assert.False(settings.ResoniteLinkEnabled);
        Assert.Equal(0, settings.ResoniteLinkPort);
    }

    [Fact]
    public async Task GetSettings_after_enable_carries_resonite_link_enabled_with_nonzero_port()
    {
        // 有効化後の GetSettings は enabled=true かつ port>0 を載せる
        // (read-only な ResoniteLinkPort が wire を越えて伝わることの確認)。
        var bridge = new FakeSessionBridge();
        await using var host = await SessionServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Session.SessionClient(channel);

        await client.ApplySettingsAsync(new SessionSettingsPatch { ResoniteLinkEnabled = true });
        var settings = await client.GetSettingsAsync(new GetSettingsRequest());

        Assert.True(settings.ResoniteLinkEnabled);
        Assert.True(settings.ResoniteLinkPort > 0);
    }

    [Fact]
    public async Task ApplySettings_with_resonite_link_enabled_true_passes_true_to_bridge()
    {
        // optional bool の presence: 明示 true が patch に non-null true として届く。
        var bridge = new FakeSessionBridge();
        await using var host = await SessionServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Session.SessionClient(channel);

        await client.ApplySettingsAsync(new SessionSettingsPatch { ResoniteLinkEnabled = true });

        var patch = Assert.IsType<Core.Session.SessionSettingsPatchSnapshot>(bridge.LastApplyPatch);
        Assert.True(patch.ResoniteLinkEnabled);
    }

    [Fact]
    public async Task ApplySettings_with_resonite_link_enabled_false_returns_FailedPrecondition()
    {
        // engine は runtime disable を提供しないため、false は FailedPrecondition
        // (SessionResoniteLinkException の翻訳) になる契約。
        var bridge = new FakeSessionBridge();
        await using var host = await SessionServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Session.SessionClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.ApplySettingsAsync(
                new SessionSettingsPatch { ResoniteLinkEnabled = false }
            )
        );

        Assert.Equal(StatusCode.FailedPrecondition, ex.StatusCode);
    }

    [Fact]
    public async Task ApplySettings_without_resonite_link_field_leaves_resonite_link_enabled_null()
    {
        // 未指定 (optional 非 set) は「変更しない」→ patch.ResoniteLinkEnabled == null。
        var bridge = new FakeSessionBridge();
        await using var host = await SessionServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Session.SessionClient(channel);

        await client.ApplySettingsAsync(new SessionSettingsPatch { WorldName = "x" });

        var patch = Assert.IsType<Core.Session.SessionSettingsPatchSnapshot>(bridge.LastApplyPatch);
        Assert.Null(patch.ResoniteLinkEnabled);
    }

    // ===================================================================
    //  ApplySettings — max_users range validation (Service layer)
    // ===================================================================

    [Fact]
    public async Task ApplySettings_with_max_users_zero_returns_InvalidArgument_without_invoking_bridge()
    {
        var bridge = new FakeSessionBridge();
        await using var host = await SessionServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Session.SessionClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.ApplySettingsAsync(new SessionSettingsPatch { MaxUsers = 0 })
        );

        Assert.Equal(StatusCode.InvalidArgument, ex.StatusCode);
        Assert.DoesNotContain("ApplySettings", bridge.Calls);
    }

    [Fact]
    public async Task ApplySettings_with_max_users_above_range_returns_InvalidArgument_without_invoking_bridge()
    {
        var bridge = new FakeSessionBridge();
        await using var host = await SessionServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Session.SessionClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.ApplySettingsAsync(new SessionSettingsPatch { MaxUsers = 256 })
        );

        Assert.Equal(StatusCode.InvalidArgument, ex.StatusCode);
        Assert.DoesNotContain("ApplySettings", bridge.Calls);
    }

    [Fact]
    public async Task ApplySettings_with_max_users_at_lower_bound_one_passes_to_bridge()
    {
        var bridge = new FakeSessionBridge();
        await using var host = await SessionServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Session.SessionClient(channel);

        await client.ApplySettingsAsync(new SessionSettingsPatch { MaxUsers = 1 });

        var patch = Assert.IsType<Core.Session.SessionSettingsPatchSnapshot>(bridge.LastApplyPatch);
        Assert.Equal(1, patch.MaxUsers);
    }

    [Fact]
    public async Task ApplySettings_with_max_users_at_upper_bound_255_passes_to_bridge()
    {
        var bridge = new FakeSessionBridge();
        await using var host = await SessionServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Session.SessionClient(channel);

        await client.ApplySettingsAsync(new SessionSettingsPatch { MaxUsers = 255 });

        var patch = Assert.IsType<Core.Session.SessionSettingsPatchSnapshot>(bridge.LastApplyPatch);
        Assert.Equal(255, patch.MaxUsers);
    }

    // ===================================================================
    //  ListUsers — round-trip of multiple users
    // ===================================================================

    [Fact]
    public async Task ListUsers_round_trips_all_users_with_fields()
    {
        var bridge = new FakeSessionBridge();
        await using var host = await SessionServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Session.SessionClient(channel);

        var response = await client.ListUsersAsync(new ListUsersRequest());

        var host_ = Assert.Single(response.Users, u => u.UserId == "U-host");
        Assert.Equal("Host", host_.UserName);
        Assert.True(host_.IsHost);
        Assert.True(host_.IsLocalUser);
        Assert.Equal("Admin", host_.RoleName);
        Assert.Equal("Windows", host_.Platform);
        Assert.Equal("Desktop", host_.HeadDevice);

        var guest = Assert.Single(response.Users, u => u.UserId == "U-guest");
        Assert.Equal("Guest", guest.UserName);
        Assert.False(guest.IsHost);
    }

    // ===================================================================
    //  User operations — Kick / Ban / Silence / Respawn / SetUserRole
    // ===================================================================

    [Fact]
    public async Task KickUser_forwards_kind_and_removes_target()
    {
        var bridge = new FakeSessionBridge();
        await using var host = await SessionServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Session.SessionClient(channel);

        await client.KickUserAsync(
            new KickUserRequest
            {
                Target = new UserTarget { UserId = "U-guest" },
                Kind = V1.KickKind.KickAndRevoke,
            }
        );

        Assert.Equal(Core.Session.KickKind.KickAndRevoke, bridge.LastKickKind);
        Assert.False(bridge.HasUser("U-guest"));
    }

    [Fact]
    public async Task KickUser_with_unspecified_kind_maps_to_default()
    {
        var bridge = new FakeSessionBridge();
        await using var host = await SessionServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Session.SessionClient(channel);

        await client.KickUserAsync(
            new KickUserRequest
            {
                Target = new UserTarget { UserId = "U-guest" },
                Kind = V1.KickKind.Unspecified,
            }
        );

        Assert.Equal(Core.Session.KickKind.Default, bridge.LastKickKind);
    }

    [Fact]
    public async Task BanUser_removes_target()
    {
        var bridge = new FakeSessionBridge();
        await using var host = await SessionServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Session.SessionClient(channel);

        await client.BanUserAsync(
            new BanUserRequest { Target = new UserTarget { UserId = "U-guest" } }
        );

        Assert.False(bridge.HasUser("U-guest"));
    }

    [Fact]
    public async Task SilenceUser_forwards_flag_and_returns_updated_user()
    {
        var bridge = new FakeSessionBridge();
        await using var host = await SessionServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Session.SessionClient(channel);

        var response = await client.SilenceUserAsync(
            new SilenceUserRequest
            {
                Target = new UserTarget { UserId = "U-guest" },
                Silenced = true,
            }
        );

        Assert.Equal("U-guest", response.User.UserId);
        Assert.True(response.User.IsSilenced);
    }

    [Fact]
    public async Task RespawnUser_forwards_target()
    {
        var bridge = new FakeSessionBridge();
        await using var host = await SessionServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Session.SessionClient(channel);

        await client.RespawnUserAsync(
            new RespawnUserRequest { Target = new UserTarget { UserId = "U-guest" } }
        );

        Assert.Contains("RespawnUser", bridge.Calls);
        Assert.Equal("U-guest", bridge.LastTarget?.UserId);
    }

    [Fact]
    public async Task SetUserRole_forwards_role_name_and_returns_updated_user()
    {
        var bridge = new FakeSessionBridge();
        await using var host = await SessionServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Session.SessionClient(channel);

        var response = await client.SetUserRoleAsync(
            new SetUserRoleRequest
            {
                Target = new UserTarget { UserId = "U-guest" },
                RoleName = "Builder",
            }
        );

        Assert.Equal("Builder", bridge.LastRoleName);
        Assert.Equal("U-guest", response.User.UserId);
        Assert.Equal("Builder", response.User.RoleName);
    }

    // ===================================================================
    //  UserTarget propagation (proto -> UserTargetSpec)
    // ===================================================================

    [Fact]
    public async Task UserTarget_user_id_field_propagates_to_spec()
    {
        var bridge = new FakeSessionBridge();
        await using var host = await SessionServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Session.SessionClient(channel);

        await client.RespawnUserAsync(
            new RespawnUserRequest { Target = new UserTarget { UserId = "U-host" } }
        );

        Assert.Equal("U-host", bridge.LastTarget?.UserId);
        Assert.Equal("", bridge.LastTarget?.UserName);
        Assert.False(bridge.LastTarget?.Local);
    }

    [Fact]
    public async Task UserTarget_user_name_field_propagates_to_spec()
    {
        var bridge = new FakeSessionBridge();
        await using var host = await SessionServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Session.SessionClient(channel);

        await client.RespawnUserAsync(
            new RespawnUserRequest { Target = new UserTarget { UserName = "Host" } }
        );

        Assert.Equal("", bridge.LastTarget?.UserId);
        Assert.Equal("Host", bridge.LastTarget?.UserName);
        Assert.False(bridge.LastTarget?.Local);
    }

    [Fact]
    public async Task UserTarget_local_flag_propagates_to_spec()
    {
        var bridge = new FakeSessionBridge();
        await using var host = await SessionServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Session.SessionClient(channel);

        await client.RespawnUserAsync(
            new RespawnUserRequest { Target = new UserTarget { Local = true } }
        );

        Assert.True(bridge.LastTarget?.Local);
    }

    // ===================================================================
    //  Exception translation
    // ===================================================================

    [Fact]
    public async Task GetSettings_translates_SessionNotReadyException_to_FailedPrecondition()
    {
        var bridge = new FakeSessionBridge { ThrowNotReady = true };
        await using var host = await SessionServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Session.SessionClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.GetSettingsAsync(new GetSettingsRequest())
        );

        Assert.Equal(StatusCode.FailedPrecondition, ex.StatusCode);
    }

    [Fact]
    public async Task ApplySettings_translates_SessionPermissionDeniedException_to_PermissionDenied()
    {
        var bridge = new FakeSessionBridge { ThrowPermissionDenied = true };
        await using var host = await SessionServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Session.SessionClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.ApplySettingsAsync(new SessionSettingsPatch { WorldName = "x" })
        );

        Assert.Equal(StatusCode.PermissionDenied, ex.StatusCode);
    }

    [Fact]
    public async Task KickUser_translates_SessionUserNotFoundException_to_NotFound()
    {
        var bridge = new FakeSessionBridge { ThrowUserNotFound = true };
        await using var host = await SessionServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Session.SessionClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.KickUserAsync(
                new KickUserRequest { Target = new UserTarget { UserId = "U-nobody" } }
            )
        );

        Assert.Equal(StatusCode.NotFound, ex.StatusCode);
    }

    [Fact]
    public async Task KickUser_translates_SessionAmbiguousUserException_to_FailedPrecondition()
    {
        var bridge = new FakeSessionBridge { ThrowAmbiguous = true };
        await using var host = await SessionServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Session.SessionClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.KickUserAsync(
                new KickUserRequest { Target = new UserTarget { UserName = "Guest" } }
            )
        );

        Assert.Equal(StatusCode.FailedPrecondition, ex.StatusCode);
    }

    [Fact]
    public async Task SetUserRole_translates_SessionRoleNotFoundException_to_NotFound()
    {
        var bridge = new FakeSessionBridge { ThrowRoleNotFound = true };
        await using var host = await SessionServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Session.SessionClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.SetUserRoleAsync(
                new SetUserRoleRequest
                {
                    Target = new UserTarget { UserId = "U-guest" },
                    RoleName = "Ghost",
                }
            )
        );

        Assert.Equal(StatusCode.NotFound, ex.StatusCode);
    }

    // ===================================================================
    //  Permissions tab — ListRoles / GetUserRoleOverrides round-trip
    // ===================================================================

    [Fact]
    public async Task ListRoles_round_trips_roles_with_highest_lowest_flags_and_default_names()
    {
        var bridge = new FakeSessionBridge();
        await using var host = await SessionServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Session.SessionClient(channel);

        var response = await client.ListRolesAsync(new ListRolesRequest());

        var admin = Assert.Single(response.Roles, r => r.RoleName == "Admin");
        Assert.Equal("full control", admin.RoleDescription);
        Assert.True(admin.IsHighest);
        Assert.False(admin.IsLowest);

        var guest = Assert.Single(response.Roles, r => r.RoleName == "Guest");
        Assert.False(guest.IsHighest);
        Assert.True(guest.IsLowest);

        Assert.Equal("Guest", response.DefaultAnonymousRole);
        Assert.Equal("Guest", response.DefaultVisitorRole);
        Assert.Equal("Builder", response.DefaultContactRole);
        Assert.Equal("Admin", response.DefaultHostRole);
        Assert.Equal("Admin", response.DefaultOwnerRole);
    }

    [Fact]
    public async Task GetUserRoleOverrides_round_trips_overrides()
    {
        var bridge = new FakeSessionBridge();
        await using var host = await SessionServiceHost.StartAsync(bridge);
        using var channel = host.CreateChannel();
        var client = new V1.Session.SessionClient(channel);

        var response = await client.GetUserRoleOverridesAsync(new GetUserRoleOverridesRequest());

        var entry = Assert.Single(response.Overrides);
        Assert.Equal("U-friend", entry.UserId);
        Assert.Equal("Builder", entry.RoleName);
    }

    // ===================================================================
    //  bridge == null -> Unavailable (representative RPCs)
    // ===================================================================

    [Fact]
    public async Task GetSettings_without_bridge_returns_Unavailable()
    {
        await using var host = await SessionServiceHost.StartAsync(bridge: null);
        using var channel = host.CreateChannel();
        var client = new V1.Session.SessionClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.GetSettingsAsync(new GetSettingsRequest())
        );

        Assert.Equal(StatusCode.Unavailable, ex.StatusCode);
    }

    [Fact]
    public async Task ListUsers_without_bridge_returns_Unavailable()
    {
        await using var host = await SessionServiceHost.StartAsync(bridge: null);
        using var channel = host.CreateChannel();
        var client = new V1.Session.SessionClient(channel);

        var ex = await Assert.ThrowsAsync<RpcException>(async () =>
            await client.ListUsersAsync(new ListUsersRequest())
        );

        Assert.Equal(StatusCode.Unavailable, ex.StatusCode);
    }
}
