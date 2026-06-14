---
name: bridge-permission-gate-dedup
description: Session (host-write) Bridge の繰り返す host 権限ゲート (if (!CanXxx()) throw SessionPermissionDeniedException) は private static RequirePermission(bool, string) 1 行に畳む
metadata:
  type: project
---

`FrooxEngineSessionBridge` のような host-write を持つ Bridge は、各 write RPC の
engine lambda 内で同形の権限ゲートを繰り返す:
`if (!world.LocalUser.CanXxx()) { throw new SessionPermissionDeniedException("..."); }`
(ApplySettings=IsAuthority / Kick / Ban / Silence / SetUserRole / Respawn の 5〜6 箇所)。

**Refactor:** `private static void RequirePermission(bool allowed, string deniedMessage)`
に畳む。varying part (predicate と message) は呼び出し側に残し、共通の
`if (!allowed) throw ...` 構築だけを集約する。`<modality>` 固有の
`SessionPermissionDeniedException` 型はこの helper にハードコードでよい (1 Bridge 内専用)。

**Why:** throw 構築が 5〜6 回反復 ("3 回以上で抽象化" 閾値超え)。message を verbatim 保持すれば
振る舞い・観測可能 surface 不変。`[[bridgefault-translate-helper]]` (Core Service の翻訳側) とは別レイヤ
— こちらは Bridge が **投げる** 側の dedup。

**De Morgan 注意:** Respawn の `!user.IsLocalUser && !user.CanRespawn()` は
`RequirePermission(user.IsLocalUser || user.CanRespawn(), ...)` に反転する (allowed 視点に揃う)。
"ローカルユーザは自分を常に respawn できる" の WHY コメントは残す。

**How to apply:** 配置は `// ---- resolution helpers ----` セクション先頭 (ResolveWorld の隣)。
XML doc に「前提: engine thread 上で呼ぶ (権限判定が world state を参照)」を明記。
siblings (Grabber/Cursor/ContextMenu/Dash) は host 権限ゲートを持たない or 1 回のみなので
この helper は Session 限定。横展開して「全 Bridge に RequirePermission を」とはしない。
