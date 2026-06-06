using Grpc.Core;
using ResoniteIO.Core.Logging;

#pragma warning disable CA1031 // catch (Exception) は Bridge 側の任意例外を gRPC Status に翻訳するために必要

namespace ResoniteIO.Core.Inventory;

/// <summary><c>resonite_io.v1.Inventory</c> サービスの Core 実装。</summary>
/// <remarks>
/// <see cref="IInventoryBridge"/> は optional DI: null なら <c>Unavailable</c> を返し、
/// Core 単体テストや inventory 非対応 engine 構成も成立させる (ContextMenuService と同 pattern)。
/// 各 RPC は engine を知らず、解決済み絶対パスを bridge に渡すだけ。例外翻訳は
/// <see cref="InventoryNotReadyException"/> / <see cref="InventoryRecursionRequiredException"/>
/// → <c>FailedPrecondition</c>、<see cref="InventoryNotFoundException"/> → <c>NotFound</c>、
/// <see cref="InventoryConflictException"/> → <c>AlreadyExists</c>、<see cref="ArgumentException"/>
/// (不正パス) → <c>InvalidArgument</c>、<see cref="InventoryCloudException"/> → <c>Unavailable</c>、
/// その他 → <c>Internal</c>。
/// </remarks>
public sealed class InventoryService : V1.Inventory.InventoryBase
{
    private readonly IInventoryBridge? _bridge;
    private readonly ILogSink _log;

    public InventoryService(ILogSink log, IInventoryBridge? bridge = null)
    {
        _log = log;
        _bridge = bridge;
    }

    public override async Task<V1.InventoryListing> List(
        V1.InventoryListRequest request,
        ServerCallContext context
    )
    {
        var bridge = RequireBridge("List");
        var snapshot = await InvokeBridge(
                "List",
                ct => bridge.ListAsync(request.Path, ct),
                context.CancellationToken
            )
            .ConfigureAwait(false);
        return ToProto(snapshot);
    }

    public override async Task<V1.InventoryMutationResult> MakeDir(
        V1.InventoryMakeDirRequest request,
        ServerCallContext context
    )
    {
        var bridge = RequireBridge("MakeDir");
        var snapshot = await InvokeBridge(
                "MakeDir",
                ct => bridge.MakeDirAsync(request.Path, ct),
                context.CancellationToken
            )
            .ConfigureAwait(false);
        return ToProto(snapshot);
    }

    public override async Task<V1.InventoryMutationResult> Copy(
        V1.InventoryCopyRequest request,
        ServerCallContext context
    )
    {
        var bridge = RequireBridge("Copy");
        var snapshot = await InvokeBridge(
                "Copy",
                ct =>
                    bridge.CopyAsync(
                        request.SourcePath,
                        request.DestinationPath,
                        request.Recursive,
                        ct
                    ),
                context.CancellationToken
            )
            .ConfigureAwait(false);
        return ToProto(snapshot);
    }

    public override async Task<V1.InventoryMutationResult> Move(
        V1.InventoryMoveRequest request,
        ServerCallContext context
    )
    {
        var bridge = RequireBridge("Move");
        var snapshot = await InvokeBridge(
                "Move",
                ct => bridge.MoveAsync(request.SourcePath, request.DestinationPath, ct),
                context.CancellationToken
            )
            .ConfigureAwait(false);
        return ToProto(snapshot);
    }

    public override async Task<V1.InventoryMutationResult> Remove(
        V1.InventoryRemoveRequest request,
        ServerCallContext context
    )
    {
        var bridge = RequireBridge("Remove");
        var snapshot = await InvokeBridge(
                "Remove",
                ct => bridge.RemoveAsync(request.Path, request.Recursive, ct),
                context.CancellationToken
            )
            .ConfigureAwait(false);
        return ToProto(snapshot);
    }

    public override async Task<V1.InventorySpawnResult> Spawn(
        V1.InventorySpawnRequest request,
        ServerCallContext context
    )
    {
        var bridge = RequireBridge("Spawn");
        var snapshot = await InvokeBridge(
                "Spawn",
                ct => bridge.SpawnAsync(request.Path, ct),
                context.CancellationToken
            )
            .ConfigureAwait(false);
        return ToProto(snapshot);
    }

    private IInventoryBridge RequireBridge(string rpc)
    {
        if (_bridge is null)
        {
            _log.LogWarning(
                $"Inventory.{rpc} called but no IInventoryBridge is registered; returning Unavailable."
            );
            throw new RpcException(
                new Status(StatusCode.Unavailable, "Inventory bridge is not configured.")
            );
        }

        return _bridge;
    }

    /// <summary>
    /// 全 RPC 共通の例外翻訳。Inventory は 3 種の戻り型 (listing/mutation/spawn) を返すため generic 化。
    /// </summary>
    private async Task<T> InvokeBridge<T>(
        string rpc,
        Func<CancellationToken, Task<T>> call,
        CancellationToken ct
    )
    {
        try
        {
            return await call(ct).ConfigureAwait(false);
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (InventoryNotReadyException ex)
        {
            _log.LogInfo($"Inventory.{rpc}: bridge not ready: {ex.Message}");
            throw new RpcException(new Status(StatusCode.FailedPrecondition, ex.Message));
        }
        catch (InventoryRecursionRequiredException ex)
        {
            _log.LogInfo($"Inventory.{rpc}: recursion required: {ex.Message}");
            throw new RpcException(new Status(StatusCode.FailedPrecondition, ex.Message));
        }
        catch (InventoryNotFoundException ex)
        {
            _log.LogInfo($"Inventory.{rpc}: not found: {ex.Message}");
            throw new RpcException(new Status(StatusCode.NotFound, ex.Message));
        }
        catch (InventoryConflictException ex)
        {
            _log.LogInfo($"Inventory.{rpc}: conflict: {ex.Message}");
            throw new RpcException(new Status(StatusCode.AlreadyExists, ex.Message));
        }
        catch (ArgumentException ex)
        {
            _log.LogInfo($"Inventory.{rpc}: invalid argument: {ex.Message}");
            throw new RpcException(new Status(StatusCode.InvalidArgument, ex.Message));
        }
        catch (InventoryCloudException ex)
        {
            _log.LogError($"Inventory.{rpc}: cloud failure: {ex}");
            throw new RpcException(new Status(StatusCode.Unavailable, ex.Message));
        }
        catch (Exception ex)
        {
            _log.LogError($"Inventory.{rpc}: bridge faulted: {ex}");
            throw new RpcException(
                new Status(StatusCode.Internal, $"Inventory bridge faulted: {ex.Message}")
            );
        }
    }

    private static V1.InventoryListing ToProto(InventoryListingSnapshot snapshot)
    {
        var listing = new V1.InventoryListing { Path = snapshot.Path };
        foreach (var entry in snapshot.Entries)
        {
            listing.Entries.Add(ToProto(entry));
        }

        return listing;
    }

    private static V1.InventoryEntry ToProto(InventoryEntrySnapshot entry) =>
        new()
        {
            Name = entry.Name,
            Path = entry.Path,
            Kind = ToProtoKind(entry.Kind),
            RecordId = entry.RecordId,
            AssetUri = entry.AssetUri,
            IsPublic = entry.IsPublic,
            LastModifiedUnixNanos = entry.LastModifiedUnixNanos,
        };

    private static V1.InventoryMutationResult ToProto(InventoryMutationSnapshot snapshot) =>
        new() { Path = snapshot.Path, RecordId = snapshot.RecordId };

    private static V1.InventorySpawnResult ToProto(InventorySpawnSnapshot snapshot) =>
        new()
        {
            SourcePath = snapshot.SourcePath,
            SpawnedSlotId = snapshot.SpawnedSlotId,
            SpawnedSlotName = snapshot.SpawnedSlotName,
        };

    private static V1.InventoryEntryKind ToProtoKind(InventoryEntryKind kind) =>
        kind switch
        {
            InventoryEntryKind.Directory => V1.InventoryEntryKind.Directory,
            InventoryEntryKind.Object => V1.InventoryEntryKind.Object,
            InventoryEntryKind.World => V1.InventoryEntryKind.World,
            InventoryEntryKind.Link => V1.InventoryEntryKind.Link,
            _ => V1.InventoryEntryKind.Unknown,
        };
}
