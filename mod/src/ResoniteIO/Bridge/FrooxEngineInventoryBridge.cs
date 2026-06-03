using System;
using System.Collections.Generic;
using System.Linq;
using System.Net;
using System.Threading;
using System.Threading.Tasks;
using Elements.Core;
using FrooxEngine;
using ResoniteIO.Core.Inventory;
using ResoniteIO.Core.Logging;
using SkyFrost.Base;
using Record = FrooxEngine.Store.Record;

namespace ResoniteIO.Bridge;

/// <summary>
/// ローカルユーザの個人インベントリを操作する <see cref="IInventoryBridge"/> 実装。
/// </summary>
/// <remarks>
/// <para>
/// インベントリは Resonite の cloud record として表現される。ls/mkdir/cp/mv/rm は
/// <see cref="Engine.Cloud"/> (<c>Records</c>) と <see cref="Engine.RecordManager"/> の
/// 非同期 REST API を任意スレッドで呼ぶ。spawn のみ component graph を触るため
/// <see cref="World.RunSynchronously(System.Action)"/> + <c>Slot.StartTask</c> で
/// engine thread に marshal する。
/// </para>
/// <para>
/// パスはクライアントの絶対パス (<c>/Inventory/Foo</c>) を engine 内部表現
/// (<c>Inventory\Foo</c>、record の <c>Path</c> はバックスラッシュ区切り) に変換して扱う。
/// ルートは <c>Inventory</c>。未ログイン (<see cref="EngineSkyFrostInterface.CurrentUserID"/> 空) や
/// world 未準備は <see cref="InventoryNotReadyException"/> として Service 層で FailedPrecondition に翻訳する。
/// directory の cp/rm は recursive 必須 (<see cref="InventoryRecursionRequiredException"/>)。
/// </para>
/// </remarks>
internal sealed class FrooxEngineInventoryBridge : IInventoryBridge
{
    private const string InventoryRoot = "Inventory";

    private readonly Engine _engine;
    private readonly ILogSink _log;

    public FrooxEngineInventoryBridge(Engine engine, ILogSink log)
    {
        ArgumentNullException.ThrowIfNull(engine);
        ArgumentNullException.ThrowIfNull(log);
        _engine = engine;
        _log = log;
    }

    /// <inheritdoc/>
    public async Task<InventoryListingSnapshot> ListAsync(string path, CancellationToken ct)
    {
        ct.ThrowIfCancellationRequested();
        var ownerId = RequireOwnerId();
        var enginePath = ToEnginePath(path);

        // 非ルートは directory record の存在を確認 (GetRecords は欠落パスでも空を返すため)。
        if (!IsRoot(enginePath))
        {
            var dir = await ResolveRecordAsync(ownerId, enginePath, path, ct).ConfigureAwait(false);
            if (!IsDirectory(dir))
            {
                throw new InventoryNotFoundException($"{path} is not a directory.");
            }
        }

        var children = await GetChildrenAsync(ownerId, enginePath, ct).ConfigureAwait(false);
        var entries = children.Select(MapEntry).ToList();
        return new InventoryListingSnapshot(ToClientPath(enginePath), entries);
    }

    /// <inheritdoc/>
    public async Task<InventoryMutationSnapshot> MakeDirAsync(string path, CancellationToken ct)
    {
        ct.ThrowIfCancellationRequested();
        var ownerId = RequireOwnerId();
        var enginePath = ToEnginePath(path);
        var (parent, name) = SplitEnginePath(enginePath);

        if (await TryResolveAsync(ownerId, enginePath, ct).ConfigureAwait(false) is not null)
        {
            throw new InventoryConflictException($"{path} already exists.");
        }

        var record = RecordHelper.CreateForDirectory<Record>(ownerId, parent, name);
        await SaveAsync(record, ct).ConfigureAwait(false);
        _log.LogInfo($"[ResoniteIO] Inventory.MakeDir: {path}");
        return new InventoryMutationSnapshot(path, record.RecordId ?? string.Empty);
    }

    /// <inheritdoc/>
    public async Task<InventoryMutationSnapshot> CopyAsync(
        string sourcePath,
        string destinationPath,
        bool recursive,
        CancellationToken ct
    )
    {
        ct.ThrowIfCancellationRequested();
        var ownerId = RequireOwnerId();
        var srcEngine = ToEnginePath(sourcePath);
        var dstEngine = ToEnginePath(destinationPath);
        var src = await ResolveRecordAsync(ownerId, srcEngine, sourcePath, ct)
            .ConfigureAwait(false);
        var (dstParent, dstName) = SplitEnginePath(dstEngine);

        var rootCopy = CloneRecord(ownerId, src, dstParent, dstName);
        await SaveAsync(rootCopy, ct).ConfigureAwait(false);

        if (IsDirectory(src))
        {
            if (!recursive)
            {
                throw new InventoryRecursionRequiredException(
                    $"{sourcePath} is a directory; pass recursive (cp -r)."
                );
            }

            var oldFull = FullPath(src);
            foreach (var rec in await CollectSubtreeAsync(ownerId, src, ct).ConfigureAwait(false))
            {
                ct.ThrowIfCancellationRequested();
                var newParent = dstEngine + rec.Path.Substring(oldFull.Length);
                await SaveAsync(CloneRecord(ownerId, rec, newParent, rec.Name), ct)
                    .ConfigureAwait(false);
            }
        }

        _log.LogInfo($"[ResoniteIO] Inventory.Copy: {sourcePath} -> {destinationPath}");
        return new InventoryMutationSnapshot(destinationPath, rootCopy.RecordId ?? string.Empty);
    }

    /// <inheritdoc/>
    public async Task<InventoryMutationSnapshot> MoveAsync(
        string sourcePath,
        string destinationPath,
        CancellationToken ct
    )
    {
        ct.ThrowIfCancellationRequested();
        var ownerId = RequireOwnerId();
        var srcEngine = ToEnginePath(sourcePath);
        var dstEngine = ToEnginePath(destinationPath);
        var src = await ResolveRecordAsync(ownerId, srcEngine, sourcePath, ct)
            .ConfigureAwait(false);
        var (dstParent, dstName) = SplitEnginePath(dstEngine);

        if (IsDirectory(src))
        {
            // 子孫の Path prefix を old→new に書き換えて再保存 (RecordId 維持 = 移動)。
            var oldFull = FullPath(src);
            foreach (var rec in await CollectSubtreeAsync(ownerId, src, ct).ConfigureAwait(false))
            {
                ct.ThrowIfCancellationRequested();
                rec.Path = dstEngine + rec.Path.Substring(oldFull.Length);
                rec.LastModificationTime = DateTime.UtcNow;
                await SaveAsync(rec, ct).ConfigureAwait(false);
            }
        }

        src.Path = dstParent;
        src.Name = dstName;
        src.LastModificationTime = DateTime.UtcNow;
        await SaveAsync(src, ct).ConfigureAwait(false);

        _log.LogInfo($"[ResoniteIO] Inventory.Move: {sourcePath} -> {destinationPath}");
        return new InventoryMutationSnapshot(destinationPath, src.RecordId ?? string.Empty);
    }

    /// <inheritdoc/>
    public async Task<InventoryMutationSnapshot> RemoveAsync(
        string path,
        bool recursive,
        CancellationToken ct
    )
    {
        ct.ThrowIfCancellationRequested();
        var ownerId = RequireOwnerId();
        var enginePath = ToEnginePath(path);
        var record = await ResolveRecordAsync(ownerId, enginePath, path, ct).ConfigureAwait(false);

        if (IsDirectory(record))
        {
            if (!recursive)
            {
                throw new InventoryRecursionRequiredException(
                    $"{path} is a directory; pass recursive (rm -r)."
                );
            }

            foreach (
                var rec in await CollectSubtreeAsync(ownerId, record, ct).ConfigureAwait(false)
            )
            {
                ct.ThrowIfCancellationRequested();
                await DeleteAsync(rec, ct).ConfigureAwait(false);
            }
        }

        await DeleteAsync(record, ct).ConfigureAwait(false);
        _log.LogInfo($"[ResoniteIO] Inventory.Remove: {path} (recursive={recursive})");
        return new InventoryMutationSnapshot(path, record.RecordId ?? string.Empty);
    }

    /// <inheritdoc/>
    public async Task<InventorySpawnSnapshot> SpawnAsync(string path, CancellationToken ct)
    {
        ct.ThrowIfCancellationRequested();
        var ownerId = RequireOwnerId();
        var enginePath = ToEnginePath(path);
        var record = await ResolveRecordAsync(ownerId, enginePath, path, ct).ConfigureAwait(false);

        var world = ResolveWorld();
        var tcs = new TaskCompletionSource<InventorySpawnSnapshot>();

        // engine thread で holder slot を作り、async load を Slot.StartTask に乗せる
        // (InventoryBrowser.SpawnItem と同じ経路)。
        world.RunSynchronously(() =>
        {
            try
            {
                if (!world.CanSpawnObjects())
                {
                    throw new InventoryNotReadyException(
                        "Spawning objects is not permitted in the current world."
                    );
                }

                var slot = world.RootSlot.LocalUserSpace.AddSlot("ResoniteIO Inventory Spawn");
                slot.StartTask(async () =>
                {
                    try
                    {
                        await slot.LoadObjectAsync(record).ConfigureAwait(false);
                        slot.PositionInFrontOfUser(null, float3.Down * 0.2f, 0.5f);
                        var spawned = slot.GetComponent<InventoryItem>()?.Unpack(false) ?? slot;
                        tcs.TrySetResult(
                            new InventorySpawnSnapshot(
                                path,
                                spawned.ReferenceID.ToString(),
                                spawned.Name ?? string.Empty
                            )
                        );
                    }
                    catch (Exception ex)
                    {
                        tcs.TrySetException(ex);
                    }
                });
            }
            catch (Exception ex)
            {
                tcs.TrySetException(ex);
            }
        });

        using (ct.Register(() => tcs.TrySetCanceled(ct)))
        {
            var result = await tcs.Task.ConfigureAwait(false);
            _log.LogInfo($"[ResoniteIO] Inventory.Spawn: {path} -> slot {result.SpawnedSlotId}");
            return result;
        }
    }

    // ---- cloud helpers -----------------------------------------------------

    private string RequireOwnerId()
    {
        var ownerId = _engine.Cloud.CurrentUserID;
        if (string.IsNullOrEmpty(ownerId))
        {
            throw new InventoryNotReadyException(
                "Not signed in to a Resonite account; inventory is unavailable."
            );
        }
        return ownerId;
    }

    private World ResolveWorld()
    {
        var world = _engine.WorldManager.FocusedWorld;
        if (world is null || world.IsDisposed)
        {
            throw new InventoryNotReadyException(
                "No focused world is available yet; engine still initializing."
            );
        }
        return world;
    }

    private async Task<Record> ResolveRecordAsync(
        string ownerId,
        string enginePath,
        string clientPath,
        CancellationToken ct
    )
    {
        var record = await TryResolveAsync(ownerId, enginePath, ct).ConfigureAwait(false);
        if (record is null)
        {
            throw new InventoryNotFoundException($"No inventory entry at {clientPath}.");
        }
        return record;
    }

    private async Task<Record?> TryResolveAsync(
        string ownerId,
        string enginePath,
        CancellationToken ct
    )
    {
        ct.ThrowIfCancellationRequested();
        CloudResult<Record> result;
        try
        {
            result = await _engine
                .Cloud.Records.GetRecordAtPath<Record>(ownerId, enginePath)
                .ConfigureAwait(false);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            throw new InventoryCloudException(
                $"Failed to fetch record at {ToClientPath(enginePath)}: {ex.Message}",
                ex
            );
        }

        if (result.State == HttpStatusCode.NotFound || result.Entity is null)
        {
            return null;
        }
        if (!result.IsOK)
        {
            throw new InventoryCloudException(
                $"Cloud error fetching {ToClientPath(enginePath)}: {result.State}."
            );
        }
        return result.Entity;
    }

    private async Task<List<Record>> GetChildrenAsync(
        string ownerId,
        string dirEnginePath,
        CancellationToken ct
    )
    {
        ct.ThrowIfCancellationRequested();
        CloudResult<List<Record>> result;
        try
        {
            result = await _engine
                .Cloud.Records.GetRecords<Record>(ownerId, null, dirEnginePath)
                .ConfigureAwait(false);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            throw new InventoryCloudException(
                $"Failed to list {ToClientPath(dirEnginePath)}: {ex.Message}",
                ex
            );
        }

        if (!result.IsOK)
        {
            throw new InventoryCloudException(
                $"Cloud error listing {ToClientPath(dirEnginePath)}: {result.State}."
            );
        }
        return result.Entity ?? new List<Record>();
    }

    /// <summary>directory record 配下の全 record (子孫) を集める。</summary>
    private async Task<List<Record>> CollectSubtreeAsync(
        string ownerId,
        Record dir,
        CancellationToken ct
    )
    {
        var all = new List<Record>();
        foreach (
            var child in await GetChildrenAsync(ownerId, FullPath(dir), ct).ConfigureAwait(false)
        )
        {
            all.Add(child);
            if (IsDirectory(child))
            {
                all.AddRange(await CollectSubtreeAsync(ownerId, child, ct).ConfigureAwait(false));
            }
        }
        return all;
    }

    private async Task SaveAsync(Record record, CancellationToken ct)
    {
        ct.ThrowIfCancellationRequested();
        try
        {
            // SaveRecord 自体は upload task を recordsToSync キューに enqueue して即座に返す。
            // cloud に反映され後続の List / GetRecordAtPath から見えることを保証するには、
            // 返ってきた upload task の完了 (RecordUploadTaskBase.Task) を待つ必要がある
            // (engine 側も EngineSkyFrostExtensions で saveResult.task.Task を await する)。
            var result = await _engine.RecordManager.SaveRecord(record).ConfigureAwait(false);
            if (result.task is not null)
            {
                await result.task.Task.ConfigureAwait(false);
            }
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            throw new InventoryCloudException(
                $"Failed to save record '{record.Name}': {ex.Message}",
                ex
            );
        }
    }

    private async Task DeleteAsync(Record record, CancellationToken ct)
    {
        ct.ThrowIfCancellationRequested();
        try
        {
            await _engine.RecordManager.DeleteRecord(record).ConfigureAwait(false);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            throw new InventoryCloudException(
                $"Failed to delete record '{record.Name}': {ex.Message}",
                ex
            );
        }
    }

    private static Record CloneRecord(
        string ownerId,
        Record src,
        string newParentPath,
        string newName
    )
    {
        var now = DateTime.UtcNow;
        return new Record
        {
            OwnerId = ownerId,
            RecordId = RecordHelper.GenerateRecordID(),
            RecordType = src.RecordType,
            Name = newName,
            Path = newParentPath,
            Description = src.Description,
            AssetURI = src.AssetURI,
            ThumbnailURI = src.ThumbnailURI,
            Tags = src.Tags is null ? null : new HashSet<string>(src.Tags),
            IsPublic = src.IsPublic,
            CreationTime = now,
            LastModificationTime = now,
        };
    }

    // ---- mapping & path helpers -------------------------------------------

    private static InventoryEntrySnapshot MapEntry(Record record)
    {
        var full = string.IsNullOrEmpty(record.Path)
            ? record.Name
            : record.Path + "\\" + record.Name;
        return new InventoryEntrySnapshot(
            record.Name ?? string.Empty,
            ToClientPath(full),
            MapKind(record.RecordType),
            record.RecordId ?? string.Empty,
            record.AssetURI ?? string.Empty,
            record.IsPublic,
            ToUnixNanos(record.LastModificationTime)
        );
    }

    private static InventoryEntryKind MapKind(string? recordType) =>
        recordType switch
        {
            "directory" => InventoryEntryKind.Directory,
            "object" => InventoryEntryKind.Object,
            "world" => InventoryEntryKind.World,
            "link" => InventoryEntryKind.Link,
            _ => InventoryEntryKind.Unknown,
        };

    private static bool IsDirectory(Record record) =>
        string.Equals(record.RecordType, "directory", StringComparison.Ordinal);

    private static bool IsRoot(string enginePath) =>
        string.Equals(enginePath, InventoryRoot, StringComparison.Ordinal);

    private static string FullPath(Record record) =>
        string.IsNullOrEmpty(record.Path) ? record.Name : record.Path + "\\" + record.Name;

    /// <summary>クライアント絶対パス <c>/Inventory/A/B</c> を engine 表現 <c>Inventory\A\B</c> に変換する。</summary>
    private static string ToEnginePath(string clientPath)
    {
        if (string.IsNullOrWhiteSpace(clientPath))
        {
            throw new ArgumentException("Inventory path must not be empty.", nameof(clientPath));
        }
        if (!clientPath.StartsWith("/", StringComparison.Ordinal))
        {
            throw new ArgumentException(
                $"Inventory path must be absolute (start with '/'): {clientPath}",
                nameof(clientPath)
            );
        }

        var segments = clientPath.Split('/', StringSplitOptions.RemoveEmptyEntries);
        if (
            segments.Length == 0
            || !string.Equals(segments[0], InventoryRoot, StringComparison.Ordinal)
        )
        {
            throw new ArgumentException(
                $"Inventory path must be under /{InventoryRoot}: {clientPath}",
                nameof(clientPath)
            );
        }
        return string.Join("\\", segments);
    }

    private static string ToClientPath(string enginePath) => "/" + enginePath.Replace('\\', '/');

    private static (string parent, string name) SplitEnginePath(string enginePath)
    {
        var idx = enginePath.LastIndexOf('\\');
        if (idx < 0)
        {
            throw new ArgumentException(
                $"Cannot operate on the inventory root: {ToClientPath(enginePath)}."
            );
        }
        return (enginePath.Substring(0, idx), enginePath.Substring(idx + 1));
    }

    private static long ToUnixNanos(DateTime dt)
    {
        var utc =
            dt.Kind == DateTimeKind.Unspecified
                ? DateTime.SpecifyKind(dt, DateTimeKind.Utc)
                : dt.ToUniversalTime();
        var ticks = utc.Ticks - DateTime.UnixEpoch.Ticks;
        return ticks <= 0 ? 0L : ticks * 100L;
    }
}
