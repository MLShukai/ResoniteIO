namespace ResoniteIO.Core.Inventory;

/// <summary>インベントリエントリの種別 (proto <c>InventoryEntryKind</c> から独立した Core 層 enum)。</summary>
/// <remarks>Resonite の <c>Record.RecordType</c> 文字列に対応する。</remarks>
public enum InventoryEntryKind
{
    Unknown,
    Directory,
    Object,
    World,
    Link,
}

/// <summary>インベントリ 1 エントリの snapshot (proto <c>InventoryEntry</c> から独立した Core 層 POCO)。</summary>
/// <remarks>
/// <paramref name="Path"/> はルートからの絶対パス。<paramref name="RecordId"/> /
/// <paramref name="AssetUri"/> は無い場合空文字、<paramref name="LastModifiedUnixNanos"/> は
/// 不明なら 0。
/// </remarks>
public sealed record InventoryEntrySnapshot(
    string Name,
    string Path,
    InventoryEntryKind Kind,
    string RecordId,
    string AssetUri,
    bool IsPublic,
    long LastModifiedUnixNanos
);

/// <summary>ディレクトリ列挙結果の snapshot (proto <c>InventoryListing</c> から独立した Core 層 POCO)。</summary>
public sealed record InventoryListingSnapshot(
    string Path,
    IReadOnlyList<InventoryEntrySnapshot> Entries
);

/// <summary>変更系 (mkdir/cp/mv/rm) の結果 snapshot (proto <c>InventoryMutationResult</c> 由来)。</summary>
public sealed record InventoryMutationSnapshot(string Path, string RecordId);

/// <summary>spawn 結果の snapshot (proto <c>InventorySpawnResult</c> 由来)。</summary>
public sealed record InventorySpawnSnapshot(
    string SourcePath,
    string SpawnedSlotId,
    string SpawnedSlotName
);

/// <summary>Mod 側 (FrooxEngine) が実装し DI で注入する個人インベントリ操作の抽象。</summary>
/// <remarks>
/// 全メソッドは解決済みの絶対パス (例 <c>/Inventory/Folder</c>) を受け取る (cwd は持たない)。
/// cloud record の CRUD は async REST、spawn のみ engine thread に marshal する。
/// </remarks>
public interface IInventoryBridge
{
    /// <summary><paramref name="path"/> 直下のエントリを列挙する。</summary>
    /// <exception cref="InventoryNotReadyException">未ログイン / engine 未準備。</exception>
    /// <exception cref="InventoryNotFoundException"><paramref name="path"/> が存在しない。</exception>
    Task<InventoryListingSnapshot> ListAsync(string path, CancellationToken ct);

    /// <summary><paramref name="path"/> にフォルダを作成する。</summary>
    /// <exception cref="InventoryNotReadyException">未ログイン / engine 未準備。</exception>
    /// <exception cref="InventoryConflictException">同名が既に存在する。</exception>
    Task<InventoryMutationSnapshot> MakeDirAsync(string path, CancellationToken ct);

    /// <summary><paramref name="sourcePath"/> を <paramref name="destinationPath"/> にコピーする。</summary>
    /// <param name="recursive">directory をコピーする場合は true 必須 (cp -r)。</param>
    /// <exception cref="InventoryNotReadyException">未ログイン / engine 未準備。</exception>
    /// <exception cref="InventoryNotFoundException">source が存在しない。</exception>
    /// <exception cref="InventoryRecursionRequiredException">source が directory で <paramref name="recursive"/> が false。</exception>
    Task<InventoryMutationSnapshot> CopyAsync(
        string sourcePath,
        string destinationPath,
        bool recursive,
        CancellationToken ct
    );

    /// <summary><paramref name="sourcePath"/> を <paramref name="destinationPath"/> に移動する (directory も再帰)。</summary>
    /// <exception cref="InventoryNotReadyException">未ログイン / engine 未準備。</exception>
    /// <exception cref="InventoryNotFoundException">source が存在しない。</exception>
    Task<InventoryMutationSnapshot> MoveAsync(
        string sourcePath,
        string destinationPath,
        CancellationToken ct
    );

    /// <summary><paramref name="path"/> のエントリを削除する。</summary>
    /// <param name="recursive">directory を削除する場合は true 必須 (rm -r)。</param>
    /// <exception cref="InventoryNotReadyException">未ログイン / engine 未準備。</exception>
    /// <exception cref="InventoryNotFoundException"><paramref name="path"/> が存在しない。</exception>
    /// <exception cref="InventoryRecursionRequiredException"><paramref name="path"/> が directory で <paramref name="recursive"/> が false。</exception>
    Task<InventoryMutationSnapshot> RemoveAsync(string path, bool recursive, CancellationToken ct);

    /// <summary><paramref name="path"/> のアイテムを現在のワールドに spawn する。</summary>
    /// <exception cref="InventoryNotReadyException">未ログイン / world 未準備 / spawn 不可。</exception>
    /// <exception cref="InventoryNotFoundException"><paramref name="path"/> が存在しない。</exception>
    Task<InventorySpawnSnapshot> SpawnAsync(string path, CancellationToken ct);
}

/// <summary>
/// Bridge が一時的にインベントリを操作できない状態 (未ログイン / engine 未準備等)。
/// Service 層は <c>FailedPrecondition</c> に翻訳するので Client は時間を置いて retry できる。
/// </summary>
public sealed class InventoryNotReadyException : Exception
{
    public InventoryNotReadyException(string message)
        : base(message) { }

    public InventoryNotReadyException(string message, Exception innerException)
        : base(message, innerException) { }
}

/// <summary>指定パスが存在しない。Service 層は <c>NotFound</c> に翻訳する。</summary>
public sealed class InventoryNotFoundException : Exception
{
    public InventoryNotFoundException(string message)
        : base(message) { }

    public InventoryNotFoundException(string message, Exception innerException)
        : base(message, innerException) { }
}

/// <summary>作成/コピー/移動先が既に存在する。Service 層は <c>AlreadyExists</c> に翻訳する。</summary>
public sealed class InventoryConflictException : Exception
{
    public InventoryConflictException(string message)
        : base(message) { }

    public InventoryConflictException(string message, Exception innerException)
        : base(message, innerException) { }
}

/// <summary>
/// directory を対象にした cp/rm で recursive フラグ (cp -r / rm -r) が指定されていない。
/// Service 層は <c>FailedPrecondition</c> に翻訳する (bash の "is a directory" 相当)。
/// </summary>
public sealed class InventoryRecursionRequiredException : Exception
{
    public InventoryRecursionRequiredException(string message)
        : base(message) { }

    public InventoryRecursionRequiredException(string message, Exception innerException)
        : base(message, innerException) { }
}

/// <summary>cloud 通信 (SkyFrost REST) が失敗した。Service 層は <c>Unavailable</c> に翻訳する。</summary>
public sealed class InventoryCloudException : Exception
{
    public InventoryCloudException(string message)
        : base(message) { }

    public InventoryCloudException(string message, Exception innerException)
        : base(message, innerException) { }
}
