---
name: pressure-vessel-shared-paths
description: Steam Linux Runtime (pressure-vessel) で host と sandbox の filesystem を共有する経路。`/home/$USER` は通る、`/run/user/<UID>` と `/tmp` は通らない。
metadata:
  type: reference
---

Steam で Resonite を起動した際、Resonite (BepInEx + Renderite.Host) は
**Proton + pressure-vessel (bubblewrap)** で sandbox 化される。host と sandbox
の filesystem 共有経路は以下:

## 通る (pass-through)

- `/home/$USER/` 以下: bind-mount で host と共有。**UDS socket / 設定ファイルの
  共有先として唯一実用的**。
- `/media/`, `/mnt/`: 同様に共有 (外付け media 用)。

## 通らない (sandbox 内で別 tmpfs)

- `/run/user/<UID>/` 配下: **sandbox 内の fresh tmpfs に overlay**。
  host の `/run/user/<UID>/foo` に書いても sandbox 内からは見えず、
  sandbox 内の `/run/user/<UID>/foo` は host から見えない。
  `XDG_RUNTIME_DIR` を頼った IPC は **本ランタイムでは動作しない**。
- `/tmp/`: 同様に sandbox 内別 tmpfs。
- `/var/tmp/`: 同様。
- `/run/host/`: pressure-vessel 内に存在するが、本実装で書き込みテストした
  限り host の実 root へは届かない (sandbox 内の fakefs 扱い)。

## 環境変数の伝播 (経路で挙動が違う)

- **container の直接 umu-run 経路では `PRESSURE_VESSEL_FILESYSTEMS_RW` は効く**
  (2026-06-19 実機確認)。`scripts/resonite-run.sh` が `export PRESSURE_VESSEL_FILESYSTEMS_RW="$GALE_DIR"` してから `exec umu-run` すると、
  `$GALE_DIR` (= `/workspace/gale`、`$HOME` 配下ではない) が sandbox に bind され、
  BepisLoader が `/workspace/gale/BepInEx/core/*.dll` を読めるようになる。これが
  無いと sandbox は既定で `$HOME` と game dir (`/opt/resonite`) しか bind せず、
  engine が `FileNotFoundException: .../BepInEx.NET.CoreCLR.dll` で即死する。
- **host Steam 経由 (旧 host-agent / gale --launch) では env が strip された**:
  Steam の Launch Options / `subprocess env=...` で渡しても sanitize され、sandbox
  側で読めなかった (旧 Step 2 Phase 4 の所見)。host 経路と container 経路で挙動が
  異なる点に注意 (env を効かせたいなら container の umu-run を直接叩く)。

## 採用方針

resonite-io は **`$HOME/.resonite-io/`** を本番 gRPC UDS の socket dir として
採用 (Mod / Python とも)。Resonite は devcontainer 内で起動し
(`just resonite-start`)、mod (GrpcHost) は同 container 内 `/home/dev/.resonite-io/`
に `resonite-{pid}.sock` を作る (bind 前に dir も自分で mkdir する)。同 container
内の Python client が同じ `/home/dev/.resonite-io/` を見て connect する。**host とは
共有しない** — Resonite を container 内で動かすので、host shell ↔ container の
bind 共有は不要になった。container 内では engine の pressure-vessel sandbox と
Python が同じ `$HOME` (= `/home/dev`) namespace を共有するので、pressure-vessel が
通す `$HOME` 配下に socket を置けば双方が同じ inode に到達する。`XDG_RUNTIME_DIR`
は (依然 pressure-vessel を通らないため) 使わない。

ただし **Gale プロファイル (`/workspace/gale`) は `$HOME` 配下ではない**ため、
sandbox の既定 bind には含まれない。`scripts/resonite-run.sh` が mod 起動時に
`PRESSURE_VESSEL_FILESYSTEMS_RW="$GALE_DIR"` を export して sandbox に bind する
(上記「環境変数の伝播」参照)。socket dir は `$HOME` 配下なので追加 bind 不要、
gale profile だけ明示 bind が要る、という非対称になっている。

## 参考

- Steam Linux Runtime: https://gitlab.steamos.cloud/steamrt/steam-runtime-tools
- pressure-vessel filesystem 共有設定:
  https://gitlab.steamos.cloud/steamrt/steam-runtime-tools/-/blob/main/pressure-vessel/wrap.md
