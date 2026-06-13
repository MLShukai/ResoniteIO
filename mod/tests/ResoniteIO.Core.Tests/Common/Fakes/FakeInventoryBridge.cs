using ResoniteIO.Core.Inventory;

namespace ResoniteIO.Core.Tests.Common.Fakes;

/// <summary>テスト用 <see cref="IInventoryBridge"/>。絶対パスをキーにした in-memory ツリーを保持し、
/// recursive 操作 (cp -r / rm -r / dir mv) をツリーに反映する。</summary>
/// <remarks>
/// <see cref="Calls"/> に各操作 (recursive フラグ込み) を記録するので、Service の引数転送を検証できる。
/// <see cref="ThrowOnNextCall"/> をセットすると次の呼び出しで任意例外を投げる (Status 翻訳テスト用、one-shot)。
/// 既定で <c>/Inventory</c> 配下に数件の seed を持つ。
/// </remarks>
internal sealed class FakeInventoryBridge : IInventoryBridge
{
    private sealed record Node(
        InventoryEntryKind Kind,
        string RecordId,
        string AssetUri,
        bool IsPublic,
        long LastModifiedUnixNanos
    );

    private readonly Dictionary<string, Node> _nodes = new(StringComparer.Ordinal);
    private int _recordSeq;

    public List<string> Calls { get; } = new();

    public Exception? ThrowOnNextCall { get; set; }

    /// <summary>FetchThumbnail が返す解決済みサムネ bytes + content-type。</summary>
    public InventoryThumbnailSnapshot NextThumbnail { get; set; } = new(Array.Empty<byte>(), "");

    /// <summary>最後に FetchThumbnail に渡された path。未呼び出しなら null。</summary>
    public string? LastFetchPath { get; private set; }

    public FakeInventoryBridge()
    {
        _nodes["/Inventory"] = Dir("R-inv-root");
        _nodes["/Inventory/Avatars"] = Dir("R-avatars");
        _nodes["/Inventory/MyAvatar"] = new Node(
            InventoryEntryKind.Object,
            "R-myavatar",
            "resrec:///U-test/R-myavatar",
            IsPublic: true,
            LastModifiedUnixNanos: 1_700_000_000_000_000_000L
        );
        _nodes["/Inventory/Avatars/Robot"] = new Node(
            InventoryEntryKind.Object,
            "R-robot",
            "resrec:///U-test/R-robot",
            IsPublic: false,
            LastModifiedUnixNanos: 1_700_000_001_000_000_000L
        );
    }

    public Task<InventoryListingSnapshot> ListAsync(string path, CancellationToken ct)
    {
        TripIfArmed();
        Calls.Add($"List {path}");
        RequireDirectory(path);

        var entries = _nodes
            .Where(kv => Parent(kv.Key) == path)
            .OrderBy(kv => kv.Key, StringComparer.Ordinal)
            .Select(kv => new InventoryEntrySnapshot(
                Name(kv.Key),
                kv.Key,
                kv.Value.Kind,
                kv.Value.RecordId,
                kv.Value.AssetUri,
                kv.Value.IsPublic,
                kv.Value.LastModifiedUnixNanos
            ))
            .ToList();

        return Task.FromResult(new InventoryListingSnapshot(path, entries));
    }

    public Task<InventoryMutationSnapshot> MakeDirAsync(string path, CancellationToken ct)
    {
        TripIfArmed();
        Calls.Add($"MakeDir {path}");
        if (_nodes.ContainsKey(path))
        {
            throw new InventoryConflictException($"already exists: {path}");
        }
        RequireDirectory(Parent(path));

        var node = Dir($"R-dir-{++_recordSeq}");
        _nodes[path] = node;
        return Task.FromResult(new InventoryMutationSnapshot(path, node.RecordId));
    }

    public Task<InventoryMutationSnapshot> CopyAsync(
        string sourcePath,
        string destinationPath,
        bool recursive,
        CancellationToken ct
    )
    {
        TripIfArmed();
        Calls.Add($"Copy {sourcePath} -> {destinationPath} recursive={recursive}");
        var source = Require(sourcePath);

        if (source.Kind == InventoryEntryKind.Directory)
        {
            if (!recursive)
            {
                throw new InventoryRecursionRequiredException(
                    $"{sourcePath} is a directory (use cp -r)"
                );
            }
            CopySubtree(sourcePath, destinationPath);
        }
        else
        {
            _nodes[destinationPath] = source with { RecordId = $"R-copy-{++_recordSeq}" };
        }

        return Task.FromResult(
            new InventoryMutationSnapshot(destinationPath, _nodes[destinationPath].RecordId)
        );
    }

    public Task<InventoryMutationSnapshot> MoveAsync(
        string sourcePath,
        string destinationPath,
        CancellationToken ct
    )
    {
        TripIfArmed();
        Calls.Add($"Move {sourcePath} -> {destinationPath}");
        var source = Require(sourcePath);

        if (source.Kind == InventoryEntryKind.Directory)
        {
            CopySubtree(sourcePath, destinationPath);
            RemoveSubtree(sourcePath);
        }
        else
        {
            _nodes[destinationPath] = source;
            _nodes.Remove(sourcePath);
        }

        return Task.FromResult(
            new InventoryMutationSnapshot(destinationPath, _nodes[destinationPath].RecordId)
        );
    }

    public Task<InventoryMutationSnapshot> RemoveAsync(
        string path,
        bool recursive,
        CancellationToken ct
    )
    {
        TripIfArmed();
        Calls.Add($"Remove {path} recursive={recursive}");
        var node = Require(path);

        if (node.Kind == InventoryEntryKind.Directory)
        {
            if (!recursive)
            {
                throw new InventoryRecursionRequiredException($"{path} is a directory (use rm -r)");
            }
            RemoveSubtree(path);
        }
        else
        {
            _nodes.Remove(path);
        }

        return Task.FromResult(new InventoryMutationSnapshot(path, node.RecordId));
    }

    public Task<InventorySpawnSnapshot> SpawnAsync(string path, CancellationToken ct)
    {
        TripIfArmed();
        Calls.Add($"Spawn {path}");
        Require(path);
        var name = Name(path);
        return Task.FromResult(new InventorySpawnSnapshot(path, $"ID-{name}", name));
    }

    public Task<InventoryThumbnailSnapshot> FetchThumbnailAsync(string path, CancellationToken ct)
    {
        ct.ThrowIfCancellationRequested();
        TripIfArmed();
        Calls.Add($"FetchThumbnail {path}");
        LastFetchPath = path;
        return Task.FromResult(NextThumbnail);
    }

    /// <summary>テスト補助: パスが存在するか。</summary>
    public bool Contains(string path) => _nodes.ContainsKey(path);

    private void CopySubtree(string sourcePath, string destinationPath)
    {
        var prefix = sourcePath + "/";
        var subtree = _nodes
            .Where(kv =>
                kv.Key == sourcePath || kv.Key.StartsWith(prefix, StringComparison.Ordinal)
            )
            .ToList();
        foreach (var (key, node) in subtree)
        {
            var newKey =
                key == sourcePath
                    ? destinationPath
                    : destinationPath + key.Substring(sourcePath.Length);
            _nodes[newKey] = node with { RecordId = $"R-copy-{++_recordSeq}" };
        }
    }

    private void RemoveSubtree(string path)
    {
        var prefix = path + "/";
        var keys = _nodes
            .Keys.Where(k => k == path || k.StartsWith(prefix, StringComparison.Ordinal))
            .ToList();
        foreach (var key in keys)
        {
            _nodes.Remove(key);
        }
    }

    private Node Require(string path)
    {
        if (!_nodes.TryGetValue(path, out var node))
        {
            throw new InventoryNotFoundException($"not found: {path}");
        }
        return node;
    }

    private void RequireDirectory(string path)
    {
        var node = Require(path);
        if (node.Kind != InventoryEntryKind.Directory)
        {
            throw new InventoryNotFoundException($"not a directory: {path}");
        }
    }

    private void TripIfArmed()
    {
        var ex = ThrowOnNextCall;
        if (ex is not null)
        {
            ThrowOnNextCall = null;
            throw ex;
        }
    }

    private static Node Dir(string recordId) =>
        new(InventoryEntryKind.Directory, recordId, AssetUri: "", IsPublic: false, 0L);

    private static string Parent(string path)
    {
        var idx = path.LastIndexOf('/');
        return idx <= 0 ? "/" : path.Substring(0, idx);
    }

    private static string Name(string path)
    {
        var idx = path.LastIndexOf('/');
        return idx < 0 ? path : path.Substring(idx + 1);
    }
}
