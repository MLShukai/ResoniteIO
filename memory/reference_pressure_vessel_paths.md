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

## 環境変数の伝播

`PRESSURE_VESSEL_FILESYSTEMS_RW` 等は Steam launch chain
(Steam → Proton → pressure-vessel) で **strip される**。`scripts/host_agent.py`
の `subprocess.Popen(env=...)` で渡しても sandbox 側で読み取れない
(Step 2 Phase 4 で実験的に確認)。env を介して sandbox 設定をいじる手は
基本的に使えない。

## 採用方針

resonite-io は **`$HOME/.resonite-io/`** を本番 gRPC UDS の socket dir として
採用 (Mod / Python / Docker container すべて)。container は username が
`dev` 固定なので、docker-compose.yml で `${HOST_HOME}/.resonite-io` を
`/home/dev/.resonite-io` に bind して 3 つの mount namespace
(host shell / pressure-vessel / container) が同じ inode に到達するように
する。`XDG_RUNTIME_DIR` は使わない。

## 参考

- Steam Linux Runtime: https://gitlab.steamos.cloud/steamrt/steam-runtime-tools
- pressure-vessel filesystem 共有設定:
  https://gitlab.steamos.cloud/steamrt/steam-runtime-tools/-/blob/main/pressure-vessel/wrap.md
