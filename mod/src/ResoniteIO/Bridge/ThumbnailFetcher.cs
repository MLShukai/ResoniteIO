using System;
using System.IO;
using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;
using FrooxEngine;
using ResoniteIO.Core.Logging;
using SkyFrost.Base;

namespace ResoniteIO.Bridge;

/// <summary>
/// Resonite asset の thumbnail URI (<c>resdb:///</c> / <c>https://</c>) を解決して
/// 画像のバイト列と content-type を取得する Mod 内部の共有ヘルパ。World / Inventory の
/// 両 bridge が使う (どちらも同じ resdb 解決 + HTTP 取得を行うため重複を 1 箇所に集約する)。
/// </summary>
/// <remarks>
/// <para>
/// 失敗 (不正 URI / 未対応 scheme / 解決不能 / ダウンロード失敗) は
/// <see cref="ThumbnailUnavailableException"/> で通知し、呼び出し側の bridge が自モダリティの
/// NotFound 例外 (<c>WorldNotFoundException</c> / <c>InventoryNotFoundException</c>) に翻訳する。
/// </para>
/// <para>
/// resdb 解決に使う <c>Engine.Cloud.Assets.DBToHttp</c> は cache 済み endpoint 文字列への純粋な
/// 文字列変換 (engine graph / focused world を参照しない) なので、engine thread への marshal は
/// 不要で任意スレッドから呼べる。HTTP 取得用の <see cref="HttpClient"/> は per-call 生成だと
/// socket 枯渇を招くため、プロセス全体で 1 つを使い回す。
/// </para>
/// </remarks>
internal sealed class ThumbnailFetcher
{
    private static readonly HttpClient _httpClient = new();

    private readonly Engine _engine;
    private readonly ILogSink _log;

    public ThumbnailFetcher(Engine engine, ILogSink log)
    {
        ArgumentNullException.ThrowIfNull(engine);
        ArgumentNullException.ThrowIfNull(log);
        _engine = engine;
        _log = log;
    }

    /// <summary>
    /// <paramref name="uri"/> を fetch 可能な http(s) URL に解決し、画像バイトと content-type を返す。
    /// </summary>
    /// <exception cref="ThumbnailUnavailableException">
    /// URI が空 / 不正 / 未対応 scheme / 解決不能、または画像をダウンロードできない。
    /// </exception>
    public async Task<(byte[] data, string contentType)> FetchAsync(
        string uri,
        CancellationToken ct
    )
    {
        ct.ThrowIfCancellationRequested();

        if (string.IsNullOrEmpty(uri))
        {
            throw new ThumbnailUnavailableException("Thumbnail uri is empty.");
        }

        var httpUri = ResolveHttpUri(uri);

        try
        {
            using var response = await _httpClient.GetAsync(httpUri, ct).ConfigureAwait(false);
            response.EnsureSuccessStatusCode();

            var bytes = await response.Content.ReadAsByteArrayAsync(ct).ConfigureAwait(false);
            var contentType =
                response.Content.Headers.ContentType?.MediaType ?? InferContentType(httpUri);

            return (bytes, contentType);
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (HttpRequestException ex)
        {
            _log.LogWarning($"ThumbnailFetcher: download failed for '{httpUri}': {ex.Message}");
            throw new ThumbnailUnavailableException(
                $"Thumbnail '{uri}' could not be downloaded.",
                ex
            );
        }
    }

    /// <summary>
    /// thumbnail uri を fetch 可能な http(s) URL に解決する。<c>resdb</c> scheme は
    /// <c>Engine.Cloud.Assets.DBToHttp</c> で CDN URL に変換する。既に http/https ならそのまま使う。
    /// </summary>
    private Uri ResolveHttpUri(string uri)
    {
        if (!Uri.TryCreate(uri, UriKind.Absolute, out var parsed))
        {
            _log.LogWarning($"ThumbnailFetcher: uri '{uri}' is not a valid absolute URI.");
            throw new ThumbnailUnavailableException(
                $"Thumbnail uri '{uri}' is not a valid absolute URI."
            );
        }

        if (
            parsed.Scheme.Equals("http", StringComparison.OrdinalIgnoreCase)
            || parsed.Scheme.Equals("https", StringComparison.OrdinalIgnoreCase)
        )
        {
            return parsed;
        }

        if (parsed.Scheme.Equals("resdb", StringComparison.OrdinalIgnoreCase))
        {
            var resolved = _engine.Cloud.Assets.DBToHttp(parsed, DB_Endpoint.Default);
            if (resolved is null)
            {
                _log.LogWarning($"ThumbnailFetcher: resdb uri '{uri}' resolved to no http URL.");
                throw new ThumbnailUnavailableException(
                    $"Thumbnail uri '{uri}' could not be resolved to a fetchable URL."
                );
            }
            return resolved;
        }

        _log.LogWarning($"ThumbnailFetcher: unsupported thumbnail uri scheme '{parsed.Scheme}'.");
        throw new ThumbnailUnavailableException(
            $"Thumbnail uri '{uri}' has unsupported scheme '{parsed.Scheme}'."
        );
    }

    /// <summary>
    /// Content-Type ヘッダが無い場合に uri 拡張子から MIME を推測する。未知の拡張子は
    /// 空文字を返す (Client 側で扱う)。
    /// </summary>
    private static string InferContentType(Uri uri) =>
        Path.GetExtension(uri.AbsolutePath).ToLowerInvariant() switch
        {
            ".webp" => "image/webp",
            ".png" => "image/png",
            ".jpg" or ".jpeg" => "image/jpeg",
            _ => "",
        };
}

/// <summary>
/// <see cref="ThumbnailFetcher"/> が thumbnail を取得できなかったことを示す Mod 内部例外。
/// 各 bridge が自モダリティの NotFound 例外に翻訳する。
/// </summary>
internal sealed class ThumbnailUnavailableException : Exception
{
    public ThumbnailUnavailableException(string message)
        : base(message) { }

    public ThumbnailUnavailableException(string message, Exception innerException)
        : base(message, innerException) { }
}
