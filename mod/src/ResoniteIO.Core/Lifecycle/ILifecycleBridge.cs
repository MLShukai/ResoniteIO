namespace ResoniteIO.Core.Lifecycle;

/// <summary>
/// グレースフル終了スケジュール要求の結果 (proto <c>ShutdownResponse</c> から独立した Core 層 POCO)。
/// </summary>
/// <param name="Accepted">
/// 終了がスケジュールされたら <c>true</c>。engine が既に終了処理を開始済みで no-op だったら <c>false</c>。
/// </param>
public sealed record ShutdownOutcome(bool Accepted);

/// <summary>Mod 側 (FrooxEngine) が実装し DI で注入する engine グレースフル終了の抽象。</summary>
/// <remarks>
/// 実装は終了を engine update tick 上に fire-and-forget で enqueue し、<b>ブロックせず即座に</b>
/// <see cref="ShutdownOutcome"/> を返さなければならない (gRPC ハンドラが応答を flush してから
/// プロセスが畳まれる契約)。任意スレッドから呼んでよい。
/// </remarks>
public interface ILifecycleBridge
{
    /// <summary>engine のグレースフル終了をスケジュールする (非ブロッキング)。</summary>
    ShutdownOutcome RequestShutdown();
}
