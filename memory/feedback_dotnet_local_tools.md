---
name: dotnet-local-tools
description: .NET CLI ツールは `.config/dotnet-tools.json` で管理し、global tool + PATH 操作は避ける。
metadata:
  type: feedback
---

C# 側で必要な .NET CLI ツール (csharpier 等) は **`.config/dotnet-tools.json` の local tool** として固定する。`dotnet tool install -g` + `~/.dotnet/tools` を PATH に通す方式は採らない。

**Why:** global tool 方式は shell rc の整備状況に依存し、`~/.dotnet/tools` が PATH に乗らないと csharpier が動かない事故を起こした。setup.sh が rc に書く PATH 行のシェル変数展開ミスや、新規 shell の起動状態に左右されるため、CI / IDE / pre-commit hook と環境を跨いで再現性が崩れる。local tool なら `dotnet csharpier` が manifest 経由で常に解決されバージョンも repo にピンされる。ユーザーが "csharpier に PATH 通さなくてよい状態にしてほしい" と明示要求したきっかけがこれ。

**How to apply:**

- 新しい .NET CLI ツールを足すときは `dotnet tool install <name>` (global の `-g` 無し) を `.config/dotnet-tools.json` 配下で行う
- `scripts/container-init.sh` の `restore_dotnet_tools` (`just container-init` から呼ばれる) が `dotnet tool restore` で manifest を反映する流れに乗せる
- `.pre-commit-config.yaml` / justfile / README からの呼び出しは **`dotnet csharpier ...` 形式** を使う (`csharpier ...` 直叩きは NG: PATH 依存に戻る)
- global tools (`-g`) を新たに増やしたくなったら、まず local tool 化を検討する
