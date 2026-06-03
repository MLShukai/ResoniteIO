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
        var enginePath = ToEnginePath(path);

        string listOwnerId;
        string listEnginePath;
        if (IsRoot(enginePath))
        {
            listOwnerId = RequireOwnerId();
            listEnginePath = InventoryRoot;
        }
        else
        {
            // 途中のリンクを辿って実体の owner/path を得る。最終要素がリンクなら
            // リンク先の dir を列挙する (Resonite Essentials のような共有フォルダ対応)。
            var resolved = await ResolveLocationAsync(path, ct).ConfigureAwait(false);
            if (
                !IsDirectory(resolved.record)
                && !string.Equals(resolved.record.RecordType, "link", StringComparison.Ordinal)
            )
            {
                throw new InventoryNotFoundException($"{path} is not a directory.");
            }
            listOwnerId = resolved.ownerId;
            listEnginePath = resolved.enginePath;
        }

        var children = await GetChildrenAsync(listOwnerId, listEnginePath, ct)
            .ConfigureAwait(false);
        var entries = children.Select(child => MapEntry(child, path)).ToList();
        return new InventoryListingSnapshot(path, entries);
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

        // 親パスを "Inventory" 配下の相対表現にする (例: Inventory\A\B → "A"、Inventory\X → "")。
        var parentRelative = string.Equals(parent, InventoryRoot, StringComparison.Ordinal)
            ? string.Empty
            : parent.Substring(InventoryRoot.Length + 1);

        var record = await CreateDirectoryRecordAsync(ownerId, parent, name, parentRelative, ct)
            .ConfigureAwait(false);
        _log.LogInfo($"[ResoniteIO] Inventory.MakeDir: {path}");
        return new InventoryMutationSnapshot(path, record.RecordId ?? string.Empty);
    }

    /// <summary>
    /// directory record を作成する。可能なら engine の live model
    /// (<see cref="RecordDirectory.AddSubdirectory(string, bool)"/>) を engine thread で叩いて
    /// 開いている InventoryBrowser に subdirectory として即時反映させる。
    /// live model が使えない / genuine conflict 以外で失敗した場合は、直接 record を作る fallback に落ちる。
    /// どちらの経路でも cloud record の durability (upload 完了待ち) は <see cref="SaveAsync"/> で保証する。
    /// </summary>
    private async Task<Record> CreateDirectoryRecordAsync(
        string ownerId,
        string parent,
        string name,
        string parentRelative,
        CancellationToken ct
    )
    {
        ct.ThrowIfCancellationRequested();
        var rootDir = _engine.Cloud.InventoryRootDirectory;
        if (rootDir is not null)
        {
            try
            {
                var record = await AddSubdirectoryViaLiveModelAsync(
                        rootDir,
                        parentRelative,
                        name,
                        ct
                    )
                    .ConfigureAwait(false);
                // AddSubdirectory 内部の SaveRecord は fire-and-forget。同一 RecordId で
                // upsert し upload 完了を待って durability を担保する。
                await SaveAsync(record, ct).ConfigureAwait(false);
                _log.LogInfo("[ResoniteIO] Inventory.MakeDir via live-model");
                return record;
            }
            catch (InventoryConflictException)
            {
                throw;
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                _log.LogInfo(
                    $"[ResoniteIO] Inventory.MakeDir live-model failed ({ex.Message}); falling back to direct."
                );
            }
        }

        // fallback: 直接 directory record を作って保存する。
        var direct = RecordHelper.CreateForDirectory<Record>(ownerId, parent, name);
        await SaveAsync(direct, ct).ConfigureAwait(false);
        _log.LogInfo("[ResoniteIO] Inventory.MakeDir via direct fallback");
        return direct;
    }

    /// <summary>
    /// engine update thread 上で親 <see cref="RecordDirectory"/> を解決し
    /// <see cref="RecordDirectory.AddSubdirectory(string, bool)"/> を呼ぶ。
    /// 既存名は <see cref="InventoryConflictException"/> に翻訳する。
    /// </summary>
    private Task<Record> AddSubdirectoryViaLiveModelAsync(
        RecordDirectory rootDir,
        string parentRelative,
        string name,
        CancellationToken ct
    )
    {
        var world = ResolveWorld();
        var tcs = new TaskCompletionSource<Record>();

        world.RunSynchronously(() =>
        {
            try
            {
                var slot = world.RootSlot.AddSlot("ResoniteIO MakeDir", persistent: false);
                slot.StartTask(async () =>
                {
                    try
                    {
                        await default(ToWorld);
                        var parentDir =
                            parentRelative.Length == 0
                                ? rootDir
                                : await rootDir.GetSubdirectoryAtPath(
                                    parentRelative.Replace('\\', '/')
                                );
                        if (parentDir is null)
                        {
                            throw new InventoryNotFoundException(
                                $"Parent directory '{parentRelative}' not found in live model."
                            );
                        }
                        await parentDir.EnsureFullyLoaded();
                        var subdir = parentDir.AddSubdirectory(name);
                        tcs.TrySetResult(subdir.DirectoryRecord);
                    }
                    catch (Exception ex) when (ex.Message.Contains("already exists"))
                    {
                        tcs.TrySetException(
                            new InventoryConflictException($"{name} already exists.", ex)
                        );
                    }
                    catch (Exception ex)
                    {
                        tcs.TrySetException(ex);
                    }
                    finally
                    {
                        slot.Destroy();
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
            return tcs.Task;
        }
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
        // 途中のリンクを辿って実体 record を得る (グループ所有でも spawn 可能)。
        var (_, _, record) = await ResolveLocationAsync(path, ct).ConfigureAwait(false);

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
                        // LoadObjectAsync 後の graph mutation を engine update thread に
                        // 載せ替える (InventoryBrowser.SpawnItem と同じ await default(ToWorld))。
                        await default(ToWorld);
                        await slot.LoadObjectAsync(record);
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

    /// <summary>
    /// クライアントパスをセグメント単位で歩き、途中の <c>link</c> record を辿って
    /// 最終的な (ownerId, enginePath, record) を返す。List / Spawn でのみ使う
    /// (mutation はリンクを辿らない)。
    /// </summary>
    private async Task<(string ownerId, string enginePath, Record record)> ResolveLocationAsync(
        string clientPath,
        CancellationToken ct
    )
    {
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

        var ownerId = RequireOwnerId();
        var enginePath = InventoryRoot;
        Record? record = null;

        for (var i = 1; i < segments.Length; i++)
        {
            ct.ThrowIfCancellationRequested();
            enginePath = enginePath + "\\" + segments[i];
            record = await TryResolveAsync(ownerId, enginePath, ct).ConfigureAwait(false);
            if (record is null)
            {
                var prefix = "/" + string.Join("/", segments.Take(i + 1));
                throw new InventoryNotFoundException($"No inventory entry at {prefix}.");
            }

            if (string.Equals(record.RecordType, "link", StringComparison.Ordinal))
            {
                (ownerId, enginePath) = ParseResRec(record.AssetURI);
            }
        }

        if (record is null)
        {
            throw new InventoryNotFoundException($"No inventory entry at {clientPath}.");
        }
        return (ownerId, enginePath, record);
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
            // GetRecordAtPath は path を URL に raw 補間する (URL エンコードしない) ため、
            // 空白などの特殊文字を含むパスでハングする。各セグメントを個別にエンコードして渡す。
            result = await _engine
                .Cloud.Records.GetRecordAtPath<Record>(ownerId, ToCloudPath(enginePath))
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

    /// <summary>
    /// child record を listing entry に変換する。クライアントから見える <c>path</c> は
    /// 要求された親パス (<paramref name="clientPathPrefix"/>) + <c>/</c> + child 名で組む
    /// (child.Path はグループ owner の engine パスになり得るため使わない)。
    /// </summary>
    private static InventoryEntrySnapshot MapEntry(Record record, string clientPathPrefix)
    {
        var name = record.Name ?? string.Empty;
        return new InventoryEntrySnapshot(
            name,
            clientPathPrefix + "/" + name,
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

    /// <summary>
    /// engine 表現 (<c>Inventory\Resonite Essentials</c>) を <c>GetRecordAtPath</c> に渡せる
    /// URL セーフなパスに変換する。各セグメントを <see cref="Uri.EscapeDataString"/> し <c>/</c> で繋ぐ。
    /// (<c>GetRecordAtPath</c> は path を URL に raw 補間するため、自前エンコードが必要。
    /// 一方 <c>GetRecords</c> は内部で <c>Uri.EscapeDataString</c> するので raw な <c>\</c> パスを渡す。)
    /// </summary>
    private static string ToCloudPath(string engineRawPath) =>
        string.Join("/", engineRawPath.Split('\\').Select(Uri.EscapeDataString));

    /// <summary>
    /// <c>resrec:///{ownerId}/{path}</c> 形式のリンク URI を (ownerId, enginePath) に分解する。
    /// 例: <c>resrec:///G-Resonite/Inventory/Resonite Essentials</c> →
    /// (<c>G-Resonite</c>, <c>Inventory\Resonite Essentials</c>)。
    /// </summary>
    private static (string ownerId, string enginePath) ParseResRec(string? assetUri)
    {
        const string prefix = "resrec:///";
        if (
            string.IsNullOrEmpty(assetUri) || !assetUri.StartsWith(prefix, StringComparison.Ordinal)
        )
        {
            throw new InventoryNotFoundException(
                $"Cannot follow link: unsupported asset URI '{assetUri}'."
            );
        }

        var rest = assetUri.Substring(prefix.Length);
        var slash = rest.IndexOf('/');
        if (slash < 0)
        {
            throw new InventoryNotFoundException(
                $"Cannot follow link: malformed asset URI '{assetUri}'."
            );
        }

        var owner = rest.Substring(0, slash);
        var pathPart = rest.Substring(slash + 1);
        return (owner, pathPart.Replace('/', '\\'));
    }

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
