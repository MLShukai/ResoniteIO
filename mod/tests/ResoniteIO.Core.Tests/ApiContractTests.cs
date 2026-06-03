using System.Reflection;
using ResoniteIO.Core.Camera;
using ResoniteIO.Core.ContextMenu;
using ResoniteIO.Core.Display;
using ResoniteIO.Core.Inventory;
using ResoniteIO.Core.Locomotion;
using ResoniteIO.Core.Logging;
using ResoniteIO.Core.Microphone;
using ResoniteIO.Core.Session;
using ResoniteIO.Core.Speaker;
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
            "ResoniteIO.V1.Display",
            "ResoniteIO.V1.Display+DisplayBase",
            "ResoniteIO.V1.DisplayApplyResponse",
            "ResoniteIO.V1.DisplayConfig",
            "ResoniteIO.V1.DisplayGetRequest",
            "ResoniteIO.V1.DisplayReflection",
            "ResoniteIO.V1.DisplayState",
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
            "ResoniteIO.V1.Locomotion",
            "ResoniteIO.V1.Locomotion+LocomotionBase",
            "ResoniteIO.V1.LocomotionCommand",
            "ResoniteIO.V1.LocomotionDriveSummary",
            "ResoniteIO.V1.LocomotionReflection",
            "ResoniteIO.V1.LocomotionResetRequest",
            "ResoniteIO.V1.LocomotionResetSummary",
            "ResoniteIO.V1.Microphone",
            "ResoniteIO.V1.Microphone+MicrophoneBase",
            "ResoniteIO.V1.MicrophoneAudioFrame",
            "ResoniteIO.V1.MicrophoneReflection",
            "ResoniteIO.V1.MicrophoneStreamSummary",
            "ResoniteIO.V1.PingRequest",
            "ResoniteIO.V1.PingResponse",
            "ResoniteIO.V1.Session",
            "ResoniteIO.V1.Session+SessionBase",
            "ResoniteIO.V1.SessionReflection",
            "ResoniteIO.V1.Speaker",
            "ResoniteIO.V1.Speaker+SpeakerBase",
            "ResoniteIO.V1.SpeakerReflection",
            "ResoniteIO.V1.SpeakerStreamRequest",
        };

        Assert.Equal(expected, actual);
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
    [InlineData(typeof(InventoryNotReadyException))]
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
