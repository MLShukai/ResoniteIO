---
name: record-save-await-upload-task
description: RecordManager.SaveRecord は upload task を recordsToSync キューに enqueue して即座に返すだけで cloud には反映されない。返り値 RecordSaveResult.task の `.Task` (RecordUploadTaskBase.Task) を await しないと直後の GetRecordAtPath / GetRecords で record が見えない
metadata:
  type: feedback
---

`Engine.RecordManager.SaveRecord(record)` を `await` しても **cloud には反映されていない**。
decompiled `RecordManager.cs` の `SaveRecord` 状態機械は `EngineRecordUploadTask` を
生成して `recordsToSync` (SpinQueue) に **enqueue して返すだけ**で、実際の cloud upload は
背景の sync ループが後でキューを drain して行う。`RecordDirectory.AddSubdirectory` 等の
engine UI 経路は SaveRecord を fire-and-forget で呼び、in-memory の RecordDirectory モデルを
**楽観的に更新**して即座に folder を表示する (cloud 反映を待たない)。

ResoniteIO の Inventory bridge は stateless で毎回 cloud を再 query するため、この遅延に
直撃する: mkdir 直後の `GetRecordAtPath` / `GetRecords` が作成した record を見つけられない
(`InventoryNotFoundException`)。**e2e でのみ顕在化** (Kestrel/in-process テストは Fake bridge で
cloud を介さないため緑のまま)。

**対策**: SaveRecord の返り値 `RecordSaveResult.task` (`EngineRecordUploadTask`、null のこともある)
の `.Task` を await して upload 完了を待つ。engine 自身も `EngineSkyFrostExtensions` で
`saveResult.task.Task` を await している。

```csharp
var result = await engine.RecordManager.SaveRecord(record).ConfigureAwait(false);
if (result.task is not null)
{
    await result.task.Task.ConfigureAwait(false); // RecordUploadTaskBase.Task = upload 完了
}
```

`RecordUploadTaskBase.Task` (`SkyFrost.Base`) は `_completionSource.Task` を返し、upload 成功時に
`SetResult(IsFinished)` / 失敗時に `SetException` する。

対になる `RecordManager.DeleteRecord(Record)` (awaitable overload) は逆に、内部で
`LocalDB.DeleteRecordAsync` と `Cloud.Records.DeleteRecord` を await するので **durable**
(キュー経由ではない)。`DeleteRecord(Uri)` / `DeleteRecord(string,string)` は `void` の
fire-and-forget なので使わない。

関連: \[\[feedback_bridge_engine_thread_dispatch\]\] (cloud record CRUD は engine thread 不要、spawn のみ marshal)。
