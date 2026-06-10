---
name: grpchost-register-helper
description: GrpcHost の per-modality DI 登録 + 未設定 WARN は Register<T> local function に統合済み。MapGrpcService は手書き維持。
metadata:
  type: project
---

`mod/src/ResoniteIO.Core/Hosting/GrpcHost.Start` の per-modality 重複は一部のみ畳んである:

- **畳んだ:** AddSingleton 12 連 if + null-check WARN 12 連 if → builder 構築後の
  local function `void Register<T>(T? b, string modality) where T : class` +
  `List<string> missing`。listen 成功後に `foreach (var m in missing) LogWarning(...)`。
  **WARN 文言・出力順 (= 登録順)・タイミング (listen 成功後) は完全保存必須**
  (テストが pin)。`Register` の呼び出し順を変えると WARN 順が変わるので注意。
- **畳まない (手書き 12 行維持):** `app.MapGrpcService<XxxService>()` ×12。
  add-new-modality skill が参照する canonical な「1 行追加箇所」なので
  ループ化・リフレクション化しない。
- `Start` の public シグネチャ (12 個の optional Bridge 引数) は不変。

これは \[\[world-service-translate-pattern\]\] の「GrpcHost に World-only helper を作るな」
への補足: cross-modality に一様な DI/WARN 重複は Register<T> で畳んでよいが、
MapGrpcService の手書き列挙は意図的に残す。
