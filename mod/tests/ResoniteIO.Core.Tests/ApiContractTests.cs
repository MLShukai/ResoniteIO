using System.Reflection;
using ResoniteIO.Core.Camera;
using ResoniteIO.Core.ContextMenu;
using ResoniteIO.Core.Cursor;
using ResoniteIO.Core.Dash;
using ResoniteIO.Core.Display;
using ResoniteIO.Core.Inventory;
using ResoniteIO.Core.Locomotion;
using ResoniteIO.Core.Logging;
using ResoniteIO.Core.Manipulation;
using ResoniteIO.Core.Microphone;
using ResoniteIO.Core.Session;
using ResoniteIO.Core.Speaker;
using ResoniteIO.Core.World;
using Xunit;

namespace ResoniteIO.Core.Tests;

/// <summary>
/// <c>ResoniteIO.Core</c> アセンブリの public surface に対する契約ピン。
/// </summary>
/// <remarks>
/// <para>
/// <b>これは契約ピンであり振る舞いテストではない。</b> 外部利用者
/// (<c>ResoniteIO</c> mod、将来の SDK 等) が依存する公開 API 名・基底クラス・
/// 主要 method signature を Hyrum's law mitigation の観点で明示的に固定する。
/// </para>
/// <para>
/// public surface を意図的に変更したい場合は、その変更と同じ commit でこの
/// テストを更新すること。CI で気付かれないリネーム / 削除 / signature 変更を
/// 検出するための「人間が意図的に approve するゲート」である。
/// </para>
/// <para>
/// 振る舞い (Service の RPC 翻訳、Bridge の latest-wins 等) は modality 配下の
/// round-trip / unit テストでカバーしている。本ファイルは
/// <c>[Trait("Category", "ApiContract")]</c> で全件マークされ、
/// <c>just mod-test --filter "Category=ApiContract"</c> で単独実行できる。
/// </para>
/// </remarks>
public sealed class ApiContractTests
{
    /// <summary>
    /// <c>ResoniteIO.Core</c> アセンブリが export する <c>ResoniteIO.Core.*</c> 名前空間の
    /// public 型一覧 (FullName) を snapshot として固定する。
    /// </summary>
    /// <remarks>
    /// Grpc.Tools の build-time 生成で <c>ResoniteIO.V1.*</c> の proto-generated 型も
    /// 同アセンブリに embed されるが、それらは
    /// <see cref="ResoniteIOV1_GeneratedProtoTypes_MatchSnapshot"/> 側で pin する。
    /// 本テストは Core 層で手書きされた API のみを対象にする。
    /// </remarks>
    [Fact]
    [Trait("Category", "ApiContract")]
    public void ResoniteIOCore_ExportedTypes_MatchSnapshot()
    {
        var actual = typeof(SessionHost)
            .Assembly.GetExportedTypes()
            .Select(t => t.FullName ?? t.Name)
            .Where(name => name.StartsWith("ResoniteIO.Core.", StringComparison.Ordinal))
            .OrderBy(name => name, StringComparer.Ordinal)
            .ToArray();

        var expected = new[]
        {
            "ResoniteIO.Core.Camera.CameraFrame",
            "ResoniteIO.Core.Camera.CameraFrameFormat",
            "ResoniteIO.Core.Camera.CameraNotReadyException",
            "ResoniteIO.Core.Camera.CameraService",
            "ResoniteIO.Core.Camera.ICameraBridge",
            "ResoniteIO.Core.Camera.PushedFrameCameraBridge",
            "ResoniteIO.Core.ContextMenu.ContextMenuHandSelector",
            "ResoniteIO.Core.ContextMenu.ContextMenuItemSnapshot",
            "ResoniteIO.Core.ContextMenu.ContextMenuNotReadyException",
            "ResoniteIO.Core.ContextMenu.ContextMenuService",
            "ResoniteIO.Core.ContextMenu.ContextMenuStateSnapshot",
            "ResoniteIO.Core.ContextMenu.IContextMenuBridge",
            "ResoniteIO.Core.Cursor.CursorNotReadyException",
            "ResoniteIO.Core.Cursor.CursorService",
            "ResoniteIO.Core.Cursor.CursorStateSnapshot",
            "ResoniteIO.Core.Cursor.ICursorBridge",
            "ResoniteIO.Core.Dash.DashActionResultSnapshot",
            "ResoniteIO.Core.Dash.DashElementSnapshot",
            "ResoniteIO.Core.Dash.DashNotReadyException",
            "ResoniteIO.Core.Dash.DashRectSnapshot",
            "ResoniteIO.Core.Dash.DashScreenListSnapshot",
            "ResoniteIO.Core.Dash.DashScreenSnapshot",
            "ResoniteIO.Core.Dash.DashService",
            "ResoniteIO.Core.Dash.DashStateSnapshot",
            "ResoniteIO.Core.Dash.DashTreeSnapshot",
            "ResoniteIO.Core.Dash.IDashBridge",
            "ResoniteIO.Core.Display.DisplayConfigSnapshot",
            "ResoniteIO.Core.Display.DisplayNotReadyException",
            "ResoniteIO.Core.Display.DisplayService",
            "ResoniteIO.Core.Display.IDisplayBridge",
            "ResoniteIO.Core.Inventory.IInventoryBridge",
            "ResoniteIO.Core.Inventory.InventoryCloudException",
            "ResoniteIO.Core.Inventory.InventoryConflictException",
            "ResoniteIO.Core.Inventory.InventoryEntryKind",
            "ResoniteIO.Core.Inventory.InventoryEntrySnapshot",
            "ResoniteIO.Core.Inventory.InventoryListingSnapshot",
            "ResoniteIO.Core.Inventory.InventoryMutationSnapshot",
            "ResoniteIO.Core.Inventory.InventoryNotFoundException",
            "ResoniteIO.Core.Inventory.InventoryNotReadyException",
            "ResoniteIO.Core.Inventory.InventoryRecursionRequiredException",
            "ResoniteIO.Core.Inventory.InventoryService",
            "ResoniteIO.Core.Inventory.InventorySpawnSnapshot",
            "ResoniteIO.Core.Locomotion.ILocomotionBridge",
            "ResoniteIO.Core.Locomotion.LocomotionDisconnectReason",
            "ResoniteIO.Core.Locomotion.LocomotionInput",
            "ResoniteIO.Core.Locomotion.LocomotionResetFlags",
            "ResoniteIO.Core.Locomotion.LocomotionService",
            "ResoniteIO.Core.Logging.ILogSink",
            "ResoniteIO.Core.Manipulation.GrabOutcome",
            "ResoniteIO.Core.Manipulation.GrabSnapshot",
            "ResoniteIO.Core.Manipulation.IManipulationBridge",
            "ResoniteIO.Core.Manipulation.ManipulationHandSelector",
            "ResoniteIO.Core.Manipulation.ManipulationNotReadyException",
            "ResoniteIO.Core.Manipulation.ManipulationPoint",
            "ResoniteIO.Core.Manipulation.ManipulationService",
            "ResoniteIO.Core.Microphone.IMicrophoneBridge",
            "ResoniteIO.Core.Microphone.MicrophoneDisconnectReason",
            "ResoniteIO.Core.Microphone.MicrophoneFrame",
            "ResoniteIO.Core.Microphone.MicrophoneNotReadyException",
            "ResoniteIO.Core.Microphone.MicrophoneService",
            "ResoniteIO.Core.Session.ISessionBridge",
            "ResoniteIO.Core.Session.SessionHost",
            "ResoniteIO.Core.Session.SessionService",
            "ResoniteIO.Core.Speaker.AudioFrame",
            "ResoniteIO.Core.Speaker.ISpeakerBridge",
            "ResoniteIO.Core.Speaker.PushedAudioFrameSpeakerBridge",
            "ResoniteIO.Core.Speaker.SpeakerNotReadyException",
            "ResoniteIO.Core.Speaker.SpeakerService",
            "ResoniteIO.Core.UnixNanosClock",
            "ResoniteIO.Core.World.IWorldBridge",
            "ResoniteIO.Core.World.JoinTarget",
            "ResoniteIO.Core.World.OpenWorldSnapshot",
            "ResoniteIO.Core.World.RecordListQuery",
            "ResoniteIO.Core.World.RecordPage",
            "ResoniteIO.Core.World.RecordSort",
            "ResoniteIO.Core.World.RecordSortDirection",
            "ResoniteIO.Core.World.RecordSource",
            "ResoniteIO.Core.World.SessionFilter",
            "ResoniteIO.Core.World.SessionListQuery",
            "ResoniteIO.Core.World.StartWorldTarget",
            "ResoniteIO.Core.World.ThumbnailBytesSnapshot",
            "ResoniteIO.Core.World.WorldNotFoundException",
            "ResoniteIO.Core.World.WorldNotReadyException",
            "ResoniteIO.Core.World.WorldRecordSnapshot",
            "ResoniteIO.Core.World.WorldService",
            "ResoniteIO.Core.World.WorldSessionSnapshot",
        };

        Assert.Equal(expected, actual);
    }

    /// <summary>
    /// proto から build-time 生成され <c>ResoniteIO.Core</c> アセンブリに embed される
    /// <c>ResoniteIO.V1.*</c> 型一覧 (FullName) を snapshot として固定する。
    /// </summary>
    /// <remarks>
    /// 各 proto file は対応する <c>&lt;Service&gt;Base</c> nested type (gRPC server stub)
    /// と <c>&lt;Modality&gt;Reflection</c> (descriptor singleton) を生成する。
    /// proto field 番号や enum 値そのものの wire 互換は scope 外 (将来 Python 側で別途 pin)。
    /// 本テストは型レベルで wire surface が消失 / リネームされていないことを検出する。
    /// </remarks>
    [Fact]
    [Trait("Category", "ApiContract")]
    public void ResoniteIOV1_GeneratedProtoTypes_MatchSnapshot()
    {
        var actual = typeof(SessionHost)
            .Assembly.GetExportedTypes()
            .Select(t => t.FullName ?? t.Name)
            .Where(name => name.StartsWith("ResoniteIO.V1.", StringComparison.Ordinal))
            .OrderBy(name => name, StringComparer.Ordinal)
            .ToArray();

        var expected = new[]
        {
            "ResoniteIO.V1.AudioFrame",
            "ResoniteIO.V1.Camera",
            "ResoniteIO.V1.Camera+CameraBase",
            "ResoniteIO.V1.CameraFrame",
            "ResoniteIO.V1.CameraFrameFormat",
            "ResoniteIO.V1.CameraReflection",
            "ResoniteIO.V1.CameraStreamRequest",
            "ResoniteIO.V1.ContextMenu",
            "ResoniteIO.V1.ContextMenu+ContextMenuBase",
            "ResoniteIO.V1.ContextMenuCloseRequest",
            "ResoniteIO.V1.ContextMenuGetStateRequest",
            "ResoniteIO.V1.ContextMenuHand",
            "ResoniteIO.V1.ContextMenuHighlightRequest",
            "ResoniteIO.V1.ContextMenuInvokeRequest",
            "ResoniteIO.V1.ContextMenuItem",
            "ResoniteIO.V1.ContextMenuOpenRequest",
            "ResoniteIO.V1.ContextMenuReflection",
            "ResoniteIO.V1.ContextMenuState",
            "ResoniteIO.V1.Cursor",
            "ResoniteIO.V1.Cursor+CursorBase",
            "ResoniteIO.V1.CursorGetPositionRequest",
            "ResoniteIO.V1.CursorReflection",
            "ResoniteIO.V1.CursorSetPositionRequest",
            "ResoniteIO.V1.CursorState",
            "ResoniteIO.V1.Dash",
            "ResoniteIO.V1.Dash+DashBase",
            "ResoniteIO.V1.DashActionResult",
            "ResoniteIO.V1.DashCloseRequest",
            "ResoniteIO.V1.DashElement",
            "ResoniteIO.V1.DashGetStateRequest",
            "ResoniteIO.V1.DashGetTreeRequest",
            "ResoniteIO.V1.DashHighlightRequest",
            "ResoniteIO.V1.DashInvokeRequest",
            "ResoniteIO.V1.DashListScreensRequest",
            "ResoniteIO.V1.DashOpenRequest",
            "ResoniteIO.V1.DashRect",
            "ResoniteIO.V1.DashReflection",
            "ResoniteIO.V1.DashScreen",
            "ResoniteIO.V1.DashScreenList",
            "ResoniteIO.V1.DashScrollRequest",
            "ResoniteIO.V1.DashSetScreenRequest",
            "ResoniteIO.V1.DashState",
            "ResoniteIO.V1.DashTree",
            "ResoniteIO.V1.Display",
            "ResoniteIO.V1.Display+DisplayBase",
            "ResoniteIO.V1.DisplayApplyResponse",
            "ResoniteIO.V1.DisplayConfig",
            "ResoniteIO.V1.DisplayGetRequest",
            "ResoniteIO.V1.DisplayReflection",
            "ResoniteIO.V1.DisplayState",
            "ResoniteIO.V1.FetchThumbnailRequest",
            "ResoniteIO.V1.FetchThumbnailResponse",
            "ResoniteIO.V1.FocusRequest",
            "ResoniteIO.V1.FocusResponse",
            "ResoniteIO.V1.GetCurrentRequest",
            "ResoniteIO.V1.GetCurrentResponse",
            "ResoniteIO.V1.Inventory",
            "ResoniteIO.V1.Inventory+InventoryBase",
            "ResoniteIO.V1.InventoryCopyRequest",
            "ResoniteIO.V1.InventoryEntry",
            "ResoniteIO.V1.InventoryEntryKind",
            "ResoniteIO.V1.InventoryListRequest",
            "ResoniteIO.V1.InventoryListing",
            "ResoniteIO.V1.InventoryMakeDirRequest",
            "ResoniteIO.V1.InventoryMoveRequest",
            "ResoniteIO.V1.InventoryMutationResult",
            "ResoniteIO.V1.InventoryReflection",
            "ResoniteIO.V1.InventoryRemoveRequest",
            "ResoniteIO.V1.InventorySpawnRequest",
            "ResoniteIO.V1.InventorySpawnResult",
            "ResoniteIO.V1.JoinRequest",
            "ResoniteIO.V1.JoinResponse",
            "ResoniteIO.V1.LeaveRequest",
            "ResoniteIO.V1.LeaveResponse",
            "ResoniteIO.V1.ListOpenWorldsRequest",
            "ResoniteIO.V1.ListOpenWorldsResponse",
            "ResoniteIO.V1.ListRecordsRequest",
            "ResoniteIO.V1.ListRecordsResponse",
            "ResoniteIO.V1.ListSessionsRequest",
            "ResoniteIO.V1.ListSessionsResponse",
            "ResoniteIO.V1.Locomotion",
            "ResoniteIO.V1.Locomotion+LocomotionBase",
            "ResoniteIO.V1.LocomotionCommand",
            "ResoniteIO.V1.LocomotionDriveSummary",
            "ResoniteIO.V1.LocomotionReflection",
            "ResoniteIO.V1.LocomotionResetRequest",
            "ResoniteIO.V1.LocomotionResetSummary",
            "ResoniteIO.V1.Manipulation",
            "ResoniteIO.V1.Manipulation+ManipulationBase",
            "ResoniteIO.V1.ManipulationGetStateRequest",
            "ResoniteIO.V1.ManipulationGrabRequest",
            "ResoniteIO.V1.ManipulationGrabResult",
            "ResoniteIO.V1.ManipulationGrabState",
            "ResoniteIO.V1.ManipulationHand",
            "ResoniteIO.V1.ManipulationReflection",
            "ResoniteIO.V1.ManipulationReleaseRequest",
            "ResoniteIO.V1.Microphone",
            "ResoniteIO.V1.Microphone+MicrophoneBase",
            "ResoniteIO.V1.MicrophoneAudioFrame",
            "ResoniteIO.V1.MicrophoneReflection",
            "ResoniteIO.V1.MicrophoneStreamSummary",
            "ResoniteIO.V1.OpenWorld",
            "ResoniteIO.V1.PingRequest",
            "ResoniteIO.V1.PingResponse",
            "ResoniteIO.V1.RecordSort",
            "ResoniteIO.V1.RecordSortDirection",
            "ResoniteIO.V1.RecordSource",
            "ResoniteIO.V1.Session",
            "ResoniteIO.V1.Session+SessionBase",
            "ResoniteIO.V1.SessionFilter",
            "ResoniteIO.V1.SessionReflection",
            "ResoniteIO.V1.Speaker",
            "ResoniteIO.V1.Speaker+SpeakerBase",
            "ResoniteIO.V1.SpeakerReflection",
            "ResoniteIO.V1.SpeakerStreamRequest",
            "ResoniteIO.V1.StartWorldRequest",
            "ResoniteIO.V1.StartWorldResponse",
            "ResoniteIO.V1.World",
            "ResoniteIO.V1.World+WorldBase",
            "ResoniteIO.V1.WorldPoint",
            "ResoniteIO.V1.WorldRecord",
            "ResoniteIO.V1.WorldReflection",
            "ResoniteIO.V1.WorldSession",
        };

        Assert.Equal(expected, actual);
    }

    /// <summary>
    /// <c>FetchThumbnail</c> RPC が <c>World</c> service descriptor に存在することを固定する。
    /// RPC のリネーム / 削除を wire 契約破壊として検出する。
    /// </summary>
    [Fact]
    [Trait("Category", "ApiContract")]
    public void World_Service_DeclaresFetchThumbnailRpc()
    {
        var methodNames = ResoniteIO
            .V1.WorldReflection.Descriptor.Services.Single(s => s.Name == "World")
            .Methods.Select(m => m.Name)
            .OrderBy(n => n, StringComparer.Ordinal)
            .ToArray();

        Assert.Contains("FetchThumbnail", methodNames);
    }

    /// <summary>
    /// <c>FetchThumbnailRequest</c> / <c>FetchThumbnailResponse</c> の proto field 番号を
    /// 固定する。wire 互換を Hyrum's law mitigation の観点で明示 pin する
    /// (番号変更は Python 側 betterproto2 デコードを静かに壊す)。
    /// </summary>
    [Fact]
    [Trait("Category", "ApiContract")]
    public void FetchThumbnailMessages_FieldNumbers_MatchSnapshot()
    {
        var requestFields = ResoniteIO
            .V1.FetchThumbnailRequest.Descriptor.Fields.InFieldNumberOrder()
            .Select(f => $"{f.FieldNumber}:{f.Name}")
            .ToArray();
        Assert.Equal(new[] { "1:uri" }, requestFields);

        var responseFields = ResoniteIO
            .V1.FetchThumbnailResponse.Descriptor.Fields.InFieldNumberOrder()
            .Select(f => $"{f.FieldNumber}:{f.Name}")
            .ToArray();
        Assert.Equal(new[] { "1:data", "2:content_type" }, responseFields);
    }

    /// <summary>
    /// <c>ListRecordsRequest</c> の proto field 番号を固定する。とくに
    /// <c>search = 8</c> (フリーテキスト検索) の wire 番号を Hyrum's law mitigation の
    /// 観点で明示 pin する (番号変更は Python 側 betterproto2 デコードを静かに壊す)。
    /// </summary>
    [Fact]
    [Trait("Category", "ApiContract")]
    public void ListRecordsRequest_FieldNumbers_MatchSnapshot()
    {
        var requestFields = ResoniteIO
            .V1.ListRecordsRequest.Descriptor.Fields.InFieldNumberOrder()
            .Select(f => $"{f.FieldNumber}:{f.Name}")
            .ToArray();
        Assert.Equal(
            new[]
            {
                "1:source",
                "2:required_tags",
                "3:owner_id",
                "4:offset",
                "5:count",
                "6:sort",
                "7:sort_direction",
                "8:search",
            },
            requestFields
        );
    }

    /// <summary>
    /// public 例外型が <see cref="Exception"/> 直系に保たれていることを固定する。
    /// 基底クラスを変えるとユーザー側 <c>catch</c> 句が静かに壊れるため、
    /// 階層変更は契約破壊として扱う。
    /// </summary>
    [Theory]
    [InlineData(typeof(CameraNotReadyException))]
    [InlineData(typeof(SpeakerNotReadyException))]
    [InlineData(typeof(MicrophoneNotReadyException))]
    [InlineData(typeof(DisplayNotReadyException))]
    [InlineData(typeof(ContextMenuNotReadyException))]
    [InlineData(typeof(CursorNotReadyException))]
    [InlineData(typeof(DashNotReadyException))]
    [InlineData(typeof(InventoryNotReadyException))]
    [InlineData(typeof(ManipulationNotReadyException))]
    [InlineData(typeof(WorldNotReadyException))]
    [InlineData(typeof(WorldNotFoundException))]
    [Trait("Category", "ApiContract")]
    public void PublicNotReadyException_DerivesDirectlyFromException(Type exceptionType)
    {
        Assert.Equal(typeof(Exception), exceptionType.BaseType);
    }

    /// <summary>
    /// <see cref="ILogSink"/> の method signature を固定する (名前 + パラメータ型一覧)。
    /// メソッド追加 / 削除 / 引数型変更で fail する。
    /// </summary>
    [Fact]
    [Trait("Category", "ApiContract")]
    public void ILogSink_MethodSignatures_MatchSnapshot()
    {
        AssertMethodSignatures(
            typeof(ILogSink),
            ("LogDebug", new[] { typeof(string) }),
            ("LogError", new[] { typeof(string) }),
            ("LogInfo", new[] { typeof(string) }),
            ("LogWarning", new[] { typeof(string) })
        );
    }

    /// <summary>
    /// <see cref="ISessionBridge"/> の public property シグネチャを固定する。
    /// </summary>
    [Fact]
    [Trait("Category", "ApiContract")]
    public void ISessionBridge_Properties_MatchSnapshot()
    {
        var properties = typeof(ISessionBridge)
            .GetProperties(BindingFlags.Instance | BindingFlags.Public)
            .Select(p => $"{p.PropertyType.FullName} {p.Name}")
            .OrderBy(s => s, StringComparer.Ordinal)
            .ToArray();

        Assert.Equal(
            new[] { "System.String FocusedWorldName", "System.String LocalUserName" },
            properties
        );
    }

    /// <summary>
    /// <see cref="ICameraBridge"/> の method signature を固定する。
    /// </summary>
    [Fact]
    [Trait("Category", "ApiContract")]
    public void ICameraBridge_MethodSignatures_MatchSnapshot()
    {
        AssertMethodSignatures(
            typeof(ICameraBridge),
            ("CaptureAsync", new[] { typeof(int), typeof(int), typeof(CancellationToken) })
        );
    }

    /// <summary>
    /// <see cref="ISpeakerBridge"/> の declared method signature と
    /// <see cref="IDisposable"/> extension を固定する。dispose 契約はリソース所有
    /// (channel) の停止に必須なので明示 pin する。
    /// </summary>
    [Fact]
    [Trait("Category", "ApiContract")]
    public void ISpeakerBridge_MethodSignatures_MatchSnapshot()
    {
        AssertMethodSignatures(
            typeof(ISpeakerBridge),
            ("StreamFramesAsync", new[] { typeof(CancellationToken) })
        );
        Assert.Contains(typeof(IDisposable), typeof(ISpeakerBridge).GetInterfaces());
    }

    /// <summary>
    /// <see cref="IMicrophoneBridge"/> の method signature を固定する。
    /// </summary>
    [Fact]
    [Trait("Category", "ApiContract")]
    public void IMicrophoneBridge_MethodSignatures_MatchSnapshot()
    {
        AssertMethodSignatures(
            typeof(IMicrophoneBridge),
            ("NotifyDisconnect", new[] { typeof(MicrophoneDisconnectReason) }),
            ("SubmitFrame", new[] { typeof(MicrophoneFrame) })
        );
    }

    /// <summary>
    /// <see cref="ILocomotionBridge"/> の method signature を固定する。
    /// </summary>
    [Fact]
    [Trait("Category", "ApiContract")]
    public void ILocomotionBridge_MethodSignatures_MatchSnapshot()
    {
        AssertMethodSignatures(
            typeof(ILocomotionBridge),
            ("NotifyDisconnect", new[] { typeof(LocomotionDisconnectReason) }),
            ("Reset", new[] { typeof(LocomotionResetFlags) }),
            ("SetState", new[] { typeof(LocomotionInput) })
        );
    }

    /// <summary>
    /// <see cref="IDisplayBridge"/> の method signature を固定する。
    /// </summary>
    [Fact]
    [Trait("Category", "ApiContract")]
    public void IDisplayBridge_MethodSignatures_MatchSnapshot()
    {
        AssertMethodSignatures(
            typeof(IDisplayBridge),
            ("ApplyAsync", new[] { typeof(DisplayConfigSnapshot), typeof(CancellationToken) }),
            ("GetAsync", new[] { typeof(CancellationToken) })
        );
    }

    /// <summary>
    /// <see cref="IContextMenuBridge"/> の method signature を固定する。
    /// </summary>
    [Fact]
    [Trait("Category", "ApiContract")]
    public void IContextMenuBridge_MethodSignatures_MatchSnapshot()
    {
        AssertMethodSignatures(
            typeof(IContextMenuBridge),
            ("OpenAsync", new[] { typeof(ContextMenuHandSelector), typeof(CancellationToken) }),
            ("CloseAsync", new[] { typeof(ContextMenuHandSelector), typeof(CancellationToken) }),
            ("GetStateAsync", new[] { typeof(ContextMenuHandSelector), typeof(CancellationToken) }),
            (
                "HighlightAsync",
                new[] { typeof(ContextMenuHandSelector), typeof(int), typeof(CancellationToken) }
            ),
            (
                "InvokeAsync",
                new[] { typeof(ContextMenuHandSelector), typeof(int), typeof(CancellationToken) }
            )
        );
    }

    /// <summary>
    /// <see cref="ICursorBridge"/> の method signature を固定する。
    /// </summary>
    [Fact]
    [Trait("Category", "ApiContract")]
    public void ICursorBridge_MethodSignatures_MatchSnapshot()
    {
        AssertMethodSignatures(
            typeof(ICursorBridge),
            ("SetPositionAsync", new[] { typeof(float), typeof(float), typeof(CancellationToken) }),
            ("GetPositionAsync", new[] { typeof(CancellationToken) })
        );
    }

    /// <summary>
    /// <see cref="IDashBridge"/> の method signature を固定する。
    /// </summary>
    [Fact]
    [Trait("Category", "ApiContract")]
    public void IDashBridge_MethodSignatures_MatchSnapshot()
    {
        AssertMethodSignatures(
            typeof(IDashBridge),
            ("OpenAsync", new[] { typeof(CancellationToken) }),
            ("CloseAsync", new[] { typeof(CancellationToken) }),
            ("GetStateAsync", new[] { typeof(CancellationToken) }),
            ("GetTreeAsync", new[] { typeof(bool), typeof(string), typeof(CancellationToken) }),
            ("InvokeAsync", new[] { typeof(string), typeof(CancellationToken) }),
            ("HighlightAsync", new[] { typeof(string), typeof(CancellationToken) }),
            (
                "ScrollAsync",
                new[] { typeof(string), typeof(float), typeof(float), typeof(CancellationToken) }
            ),
            ("ListScreensAsync", new[] { typeof(CancellationToken) }),
            ("SetScreenAsync", new[] { typeof(string), typeof(string), typeof(CancellationToken) })
        );
    }

    /// <summary>
    /// <see cref="IManipulationBridge"/> の method signature を固定する。
    /// </summary>
    [Fact]
    [Trait("Category", "ApiContract")]
    public void IManipulationBridge_MethodSignatures_MatchSnapshot()
    {
        AssertMethodSignatures(
            typeof(IManipulationBridge),
            (
                "GrabAsync",
                new[]
                {
                    typeof(ManipulationHandSelector),
                    typeof(ManipulationPoint?),
                    typeof(float),
                    typeof(CancellationToken),
                }
            ),
            ("ReleaseAsync", new[] { typeof(ManipulationHandSelector), typeof(CancellationToken) }),
            ("GetStateAsync", new[] { typeof(ManipulationHandSelector), typeof(CancellationToken) })
        );
    }

    /// <summary>
    /// <see cref="IWorldBridge"/> の method signature を固定する。
    /// </summary>
    [Fact]
    [Trait("Category", "ApiContract")]
    public void IWorldBridge_MethodSignatures_MatchSnapshot()
    {
        AssertMethodSignatures(
            typeof(IWorldBridge),
            ("ListSessionsAsync", new[] { typeof(SessionListQuery), typeof(CancellationToken) }),
            ("ListRecordsAsync", new[] { typeof(RecordListQuery), typeof(CancellationToken) }),
            ("JoinAsync", new[] { typeof(JoinTarget), typeof(CancellationToken) }),
            ("StartWorldAsync", new[] { typeof(StartWorldTarget), typeof(CancellationToken) }),
            ("ListOpenWorldsAsync", new[] { typeof(CancellationToken) }),
            ("FocusAsync", new[] { typeof(int), typeof(CancellationToken) }),
            ("LeaveAsync", new[] { typeof(int), typeof(CancellationToken) }),
            ("GetCurrentAsync", new[] { typeof(CancellationToken) }),
            ("FetchThumbnailAsync", new[] { typeof(string), typeof(CancellationToken) })
        );
    }

    /// <summary>
    /// 指定 interface の declared methods (property accessor は除く) が、
    /// 期待 (name, paramTypes) 一覧と完全一致することを assert する。
    /// </summary>
    private static void AssertMethodSignatures(
        Type interfaceType,
        params (string Name, Type[] ParamTypes)[] expected
    )
    {
        var actual = interfaceType
            .GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.DeclaredOnly)
            .Where(m => !m.IsSpecialName) // accessor を除外
            .Select(m =>
                $"{m.Name}({string.Join(",", m.GetParameters().Select(p => p.ParameterType.FullName))})"
            )
            .OrderBy(s => s, StringComparer.Ordinal)
            .ToArray();

        var expectedFormatted = expected
            .Select(e => $"{e.Name}({string.Join(",", e.ParamTypes.Select(t => t.FullName))})")
            .OrderBy(s => s, StringComparer.Ordinal)
            .ToArray();

        Assert.Equal(expectedFormatted, actual);
    }
}
