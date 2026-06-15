---
name: auth-login-api
description: Auth modality (Resonite cloud login/logout/status) の engine 経路と機微情報の扱い — Engine.Cloud.Session.Login(new PasswordLogin)、CloudResult.Content=="TOTP" が 2FA signal、CurrentSession で状態読み、Cloud REST は thread-agnostic、password 非保存・非ログ・例外メッセージ generic のセキュリティ設計、SessionExpire→nanos と raw 例外漏洩の hardening。
metadata:
  type: feedback
---

# Auth modality の engine 経路とセキュリティ設計

2026-06-15 追加 (当初 8-step 計画外の userspace modality)。Resonite cloud への
**login / logout / 認証状態取得** を `Engine.Cloud.Session` 直叩きで行う unary 3 RPC
(`Login` / `Logout` / `Status`、いずれも統一 `AuthStatus` を返す)。方向は Python → Resonite。
全 engine 知見は decompiled (`SkyFrost.Base` / `FrooxEngine`) の精読 + 敵対的検証で確定した。

**既存 `Session` modality とは別物**: `Session` は接続中ワールド/インスタンスの admin
(Settings/Users/Permissions) で、`Auth` は cloud 認証。名前は紛らわしいが proto/型名は
`Auth*` 接頭辞で分離。

## engine 経路 (FEASIBLE、全 high-confidence)

- `Engine.Cloud` は `EngineSkyFrostInterface : SkyFrostInterface` (`FrooxEngine`)。`.Session` は
  `SkyFrost.Base.SessionManager`。
- **login**: `Engine.Cloud.Session.Login(string credential, LoginAuthentication authentication, string secretMachineId, bool rememberMe, string totp)` → `Task<CloudResult<UserSessionResult<UserSession>>>` (`SessionManager.cs:1574`)。
  - `credential` は username / email / user ID (`U-xxx`) のいずれか (engine が解決)。
  - `authentication` は `new SkyFrost.Base.PasswordLogin(password)` (`LoginAuthentication` 抽象の派生。他に `SessionTokenLogin`)。`PasswordLogin(string)` ctor あり。
  - `secretMachineId` は `Engine.LocalDB.SecretMachineID` (string、machine-bound persistence の鍵)。
  - `rememberMe=true` で engine 自身が LocalDB にセッションを machine-bound + 暗号化保存し再ログインを延長。
- **成否判定 (load-bearing)**: 戻り値 `CloudResult` を見る。
  - `result.IsOK` → 成功。UserSession は `result.Entity.Entity`。engine が `ActivateSession` して `CurrentSession`/`CurrentUser` を populate。
  - `result.Content == "TOTP"` (完全一致の文字列リテラル) → **2FA 要求**。`LoginDialog.cs:924` も同一判定で TwoFactorCodeDialog を出し、totp 付きで Login を再呼び出しする。
  - それ以外で `IsError` → 認証失敗 (wrong password 等)。`result.State` が `HttpStatusCode`。
- **logout**: `Engine.Cloud.Session.Logout(bool isManual)` → `Task` (手動は `isManual: true`)。
- **状態読み**: `Cloud.Session.CurrentSession` (`UserSession?`、null = 未ログイン)、`Cloud.CurrentUserID` (`CurrentUser?.Id`)、`Cloud.CurrentUsername`、`CurrentSession.SessionExpire` (`DateTime`、UTC、`IsExpired` computed)。

## Cloud REST は thread-agnostic — engine dispatch 不要

Login / Logout / status read はいずれも **Cloud REST 呼び出し + lock 保護された property
read** のみで component graph を触らない。よって `World.RunSynchronously` /
\[\[feedback_bridge_engine_thread_dispatch\]\] の engine-thread marshal は **不要**で、gRPC handler
スレッドから `await ... .ConfigureAwait(false)` で直接呼べる (検証で「engine thread 必須」説は
refuted)。`FrooxEngineInventoryBridge` の cloud-REST-は任意スレッド慣習と同じ。Bridge は engine
状態を持たず **非 IDisposable**、`SafeShutdown` は参照 null 化のみ。

## セキュリティ設計 (本 modality の主眼)

- **password は平文の機密**。ディスク非保存・ログ非出力・例外メッセージ/`Status.Detail` 非混入・
  `--format json` 非出力。`remember_me=true` で永続化は engine に委譲し、resoio は credential を
  一切保存しない。
- **`--password` CLI flag は作らない** (ps / shell 履歴漏洩防止)。password は `RESONITE_IO_PASSWORD`
  env → piped stdin → `prompt_toolkit` の hidden prompt のみ。credential (username) は機密でないので
  positional / prompt で可。
- Auth 例外 (`AuthNotReadyException` / `AuthFailedException` / `AuthTotpRequiredException`) の Message は
  **generic に保つ**。`BridgeFault.Translate` が `ex.Message` を `Status.Detail` とログに転写するため。
  例外翻訳: TotpRequired / NotReady → `FailedPrecondition`、Failed → `Unauthenticated`。
- **hardening 1 (raw 例外漏洩、review 指摘)**: `await session.Login(...)` を try/catch で囲み、
  非 `OperationCanceledException` は **inner を chain せず** generic `AuthFailedException("Login failed.")`
  に畳む。理由: `ApiClient` は transport 失敗時 (throwOnError=true) に raw 例外を rethrow し、login
  request の entity dict に平文 password が載る (`SessionManager.cs:1610`)。畳まないと `BridgeFault` の
  Internal 経路 (`{ex}` ToString ログ + `ex.Message`→`Status.Detail`) で漏れ得る。defense-in-depth。
- **hardening 2 (SessionExpire→nanos)**: 兄弟 bridge (Inventory/World) と同形の tick ベース
  `ToUnixNanos` を使う (`(utc.Ticks - UnixEpoch.Ticks) * 100L`、`ticks <= 0 ? 0L` クランプ)。
  naive な `ToUnixTimeMilliseconds() * 1_000_000L` は overflow check 無効環境で `default(DateTime)` /
  pre-1970 が int64 wrap して garbage 化する (proto 契約「期限不明なら 0」違反)。

## CLI の 2FA リトライ

server は totp 不足を `FailedPrecondition` (message に "two-factor") で返す。CLI は tty なら
プロンプトで totp を 1 回聞いて再 login、非 tty なら `--totp` を促して exit 1。プロンプト文字列は
**stderr** へ (stdout は `--format json` の 1 ドキュメント専用)。

## e2e は status のみ安全・login/logout は破壊的

- `auth status` は副作用なしで安全に自動駆動できる。
- `auth login` / `logout` は **実認証情報が必要 + 実行中セッションのログイン状態を変える破壊的操作**
  なので、env (`RESONITE_IO_E2E_CREDENTIAL` / `RESONITE_IO_E2E_PASSWORD` + 明示 opt-in) で gate し、
  既定では skip。実機検証は再デプロイ + 再起動 (= ユーザーの現セッションを切る) を要するため、
  実行前にユーザー確認する。連続 sign-in の癖は \[\[feedback_e2e_single_signin_per_boot\]\] 参照。
