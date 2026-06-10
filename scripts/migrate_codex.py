#!/usr/bin/env python3
"""Migrate Claude project assets into Codex project assets.

Claude remains the editable source of truth for this repository's agent
material. This script produces the Codex-facing mirrors that Codex can load:

- .claude/skills/* -> .agents/skills/*
- .claude/agents/*.md -> .codex/agents/*.toml
- .claude/settings*.json -> .codex/rules/default.rules
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLAUDE_ONLY_SKILLS = {"edit-dot-claude"}
KNOWN_AGENT_DESCRIPTIONS = {
    "code-quality-reviewer": "Refactoring specialist that improves internal code quality without changing public API or tests.",
    "docstring-author": "Documentation polish specialist that writes concise docstrings and comments without changing logic.",
    "spec-driven-implementer": "Implementation-only engineer that writes production code from a defined spec and never edits tests.",
    "spec-planner": "Planning-only architect that turns ambiguous requests into concrete specs without writing code.",
    "spec-test-author": "Test-only engineer that turns specs into executable behavior tests and never edits production code.",
}


@dataclass
class Migration:
    check: bool
    changed: list[Path] = field(default_factory=list)
    unchanged: int = 0
    skipped: list[str] = field(default_factory=list)

    def write_text(self, path: Path, content: str) -> None:
        if not content.endswith("\n"):
            content += "\n"
        old = path.read_text(encoding="utf-8") if path.exists() else None
        if old == content:
            self.unchanged += 1
            return
        self.changed.append(path)
        if not self.check:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

    def write_bytes(self, path: Path, content: bytes) -> None:
        old = path.read_bytes() if path.exists() else None
        if old == content:
            self.unchanged += 1
            return
        self.changed.append(path)
        if not self.check:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text
    raw = text[4:end]
    body = text[end + len("\n---\n") :]
    frontmatter: dict[str, str] = {}
    for line in raw.splitlines():
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        frontmatter[key.strip()] = parse_scalar(value.strip())
    return frontmatter, body


def parse_scalar(value: str) -> str:
    if not value:
        return ""
    if value[0] in {"'", '"'}:
        try:
            parsed = ast.literal_eval(value)
        except (SyntaxError, ValueError):
            parsed = value.strip("'\"")
        return str(parsed)
    return value


def toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def toml_multiline_literal(value: str) -> str:
    value = value.rstrip()
    if "'''" not in value:
        return "'''\n" + value + "\n'''"
    return toml_string(value)


def summarize_description(description: str) -> str:
    description = description.replace("\\n", "\n")
    description = description.split("\n\n<example>", 1)[0]
    description = description.split("Examples:", 1)[0]
    description = re.sub(r"\s+", " ", description).strip()
    if len(description) <= 280:
        return description
    return description[:277].rsplit(" ", 1)[0].rstrip() + "..."


def rewrite_codex_common(text: str) -> str:
    replacements = [
        ("CLAUDE.md", "AGENTS.md"),
        ("Claude Code", "Codex"),
        ("Claude harness", "Codex"),
        ("Claude が", "Codex が"),
        ("Claude を", "Codex を"),
        ("Claude は", "Codex は"),
        ("Claude で", "Codex で"),
        ("Claude 側", "Codex 側"),
        ("親 Claude", "親 Codex"),
    ]
    for old, new in replacements:
        text = text.replace(old, new)
    return text


def rewrite_skill_text(text: str) -> str:
    text = rewrite_codex_common(text)
    text = text.replace(
        "[`.claude/settings.container.json`](../../settings.container.json)",
        "[`.codex/rules/default.rules`](../../../.codex/rules/default.rules)",
    )
    text = text.replace(".claude/skills/", ".agents/skills/")
    text = text.replace(".claude/skills", ".agents/skills")
    text = text.replace(".claude/commands/", ".codex/commands/")
    text = re.sub(
        r"\.claude/agents/([A-Za-z0-9_-]+)\.md",
        r".codex/agents/\1.toml",
        text,
    )
    text = re.sub(
        r"\]\(\.\./\.\./agents/([A-Za-z0-9_-]+)\.md\)",
        r"](../../../.codex/agents/\1.toml)",
        text,
    )
    text = text.replace("(../../memory/", "(../../../memory/")
    text = text.replace(
        "`.claude/settings.container.json`",
        "`.codex/rules/default.rules`",
    )
    text = text.replace(
        "[`.codex/rules/default.rules`](../../settings.container.json)",
        "[`.codex/rules/default.rules`](../../../.codex/rules/default.rules)",
    )
    text = text.replace("Claude", "Codex")
    text = normalize_markdown_tables(text)
    text = re.sub(
        r"## 7\. `\.claude/` ファイルを触るとき\n\n.*\Z",
        "## 7. Codex 設定ファイルを触るとき\n\n"
        "Codex 向けの永続指示は root `AGENTS.md`、repo skills は `.agents/skills/`、\n"
        "custom subagents は `.codex/agents/*.toml` に置く。これらを編集するときは通常の\n"
        "repo ファイルとして扱い、独立した複数ファイルの読み取り・編集は\n"
        "[`maximize-parallels`](../maximize-parallels/SKILL.md) に従って並列化する。",
        text,
        flags=re.S,
    )
    return text


def normalize_markdown_tables(text: str) -> str:
    """Match mdformat's table alignment for known generated skill content."""
    replacements = [
        (
            "| 区分                       | 配置                                                                                     | 検証対象                                                                                                                    | モック許容                                                                             |",
            "| 区分                       | 配置                                                                                     | 検証対象                                                                                                                   | モック許容                                                                             |",
        ),
        (
            "| -------------------------- | ---------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- |",
            "| -------------------------- | ---------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- |",
        ),
        (
            "| **unit**                   | `python/tests/resoio/test_<file>.py`、`mod/tests/ResoniteIO.Core.Tests/<File>Tests.cs`   | 純粋ロジック (proto encoding、timestamp 計算、UDS path 解決、UnixNanosClock の単調性等)                                     | なし                                                                                   |",
            "| **unit**                   | `python/tests/resoio/test_<file>.py`、`mod/tests/ResoniteIO.Core.Tests/<File>Tests.cs`   | 純粋ロジック (proto encoding、timestamp 計算、UDS path 解決、UnixNanosClock の単調性等)                                    | なし                                                                                   |",
        ),
        (
            "| **integration-with-fakes** | 同上、`python/tests/fakes/` / `mod/tests/ResoniteIO.Core.Tests/Common/` から fake import | モジュール間結合 (`I<Modality>Bridge` 越し、`<Modality>Service` ↔ Bridge IF の契約)                                         | **自前 ABC のみ** (`FakeCameraBridge`, `FakeSpeakerBridge`, `FakeMicrophoneBridge` 等) |",
            "| **integration-with-fakes** | 同上、`python/tests/fakes/` / `mod/tests/ResoniteIO.Core.Tests/Common/` から fake import | モジュール間結合 (`I<Modality>Bridge` 越し、`<Modality>Service` ↔ Bridge IF の契約)                                        | **自前 ABC のみ** (`FakeCameraBridge`, `FakeSpeakerBridge`, `FakeMicrophoneBridge` 等) |",
        ),
        (
            "| **integration-real**       | 同上                                                                                     | adapter / proto wire / Kestrel + grpclib 結合点 (実 in-process server、実 UDS、実時刻)                                      | 原則なし。Kestrel `WebApplication.CreateBuilder` + `IServer` を実 socket で立てる      |",
            "| **integration-real**       | 同上                                                                                     | adapter / proto wire / Kestrel + grpclib 結合点 (実 in-process server、実 UDS、実時刻)                                     | 原則なし。Kestrel `WebApplication.CreateBuilder` + `IServer` を実 socket で立てる      |",
        ),
        (
            "| **e2e (Codex 自動)**      | `python/tests/e2e/`                                                                      | end-to-end (実 Resonite、`just deploy-mod` 後の FrooxEngine + BepInEx + ResoniteIO loaded、Codex が host-agent 経由で駆動) | なし                                                                                   |",
            "| **e2e (Codex 自動)**       | `python/tests/e2e/`                                                                      | end-to-end (実 Resonite、`just deploy-mod` 後の FrooxEngine + BepInEx + ResoniteIO loaded、Codex が host-agent 経由で駆動) | なし                                                                                   |",
        ),
        (
            "| **manual (人間のみ)**      | `mod/tests/manual/`                                                                      | 本質的に人間しかできない確認のみ (UI 手動切替、別アカウントでの voice 受信確認 等)                                          | なし                                                                                   |",
            "| **manual (人間のみ)**      | `mod/tests/manual/`                                                                      | 本質的に人間しかできない確認のみ (UI 手動切替、別アカウントでの voice 受信確認 等)                                         | なし                                                                                   |",
        ),
    ]
    for old, new in replacements:
        text = text.replace(old, new)
    return text


def rewrite_agent_body(name: str, body: str) -> str:
    body = body.split("\n# Persistent Agent Memory\n", 1)[0].rstrip()
    body = rewrite_codex_common(body)
    body = body.replace("(../skills/", "(../../.agents/skills/")
    body = body.replace("[/testing-strategy skill]", "[testing-strategy skill]")
    body = body.replace("[/add-new-modality skill]", "[add-new-modality skill]")
    body = body.replace("[/debug-resonite-mod skill]", "[debug-resonite-mod skill]")
    body = body.replace("Claude", "Codex")
    body += (
        "\n## Codex memory handoff\n\n"
        "When durable, agent-specific knowledge is worth preserving, use "
        f"`memory/agents/{name}/` and keep `memory/agents/{name}/MEMORY.md` "
        "as the index. Do not store transient task state there."
    )
    return body


def sync_skills(migration: Migration, include_claude_only: bool) -> None:
    source_root = ROOT / ".claude" / "skills"
    dest_root = ROOT / ".agents" / "skills"
    if not source_root.exists():
        migration.skipped.append(f"{source_root} does not exist")
        return
    for source_skill in sorted(path for path in source_root.iterdir() if path.is_dir()):
        if source_skill.name in CLAUDE_ONLY_SKILLS and not include_claude_only:
            migration.skipped.append(f"Claude-only skill skipped: {source_skill.name}")
            continue
        for source in sorted(
            path for path in source_skill.rglob("*") if path.is_file()
        ):
            rel = source.relative_to(source_skill)
            dest = dest_root / source_skill.name / rel
            if rel == Path("SKILL.md"):
                text = source.read_text(encoding="utf-8")
                migration.write_text(dest, rewrite_skill_text(text))
            else:
                migration.write_bytes(dest, source.read_bytes())


def sync_agents(migration: Migration) -> None:
    source_root = ROOT / ".claude" / "agents"
    dest_root = ROOT / ".codex" / "agents"
    if not source_root.exists():
        migration.skipped.append(f"{source_root} does not exist")
        return
    for source in sorted(source_root.glob("*.md")):
        text = source.read_text(encoding="utf-8")
        frontmatter, body = parse_frontmatter(text)
        body = body.lstrip("\n")
        name = frontmatter.get("name") or source.stem
        description = KNOWN_AGENT_DESCRIPTIONS.get(
            name,
            summarize_description(frontmatter.get("description", name)),
        )
        instructions = rewrite_agent_body(name, body)
        lines = [
            f"name = {toml_string(name)}",
            f"description = {toml_string(description)}",
            f"developer_instructions = {toml_multiline_literal(instructions)}",
        ]
        if "一切のコードを書いてはいけません" in body:
            lines.append('sandbox_mode = "read-only"')
        migration.write_text(dest_root / f"{name}.toml", "\n".join(lines))


def load_claude_settings() -> tuple[list[str], list[str], list[str]]:
    allow: list[str] = []
    deny: list[str] = []
    non_shell: list[str] = []
    for path in [
        ROOT / ".claude" / "settings.json",
        ROOT / ".claude" / "settings.container.json",
    ]:
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        permissions = data.get("permissions", {})
        for value in permissions.get("allow", []):
            if isinstance(value, str) and value.startswith("Bash("):
                allow.append(value)
            elif isinstance(value, str):
                non_shell.append(value)
        for value in permissions.get("deny", []):
            if isinstance(value, str) and value.startswith("Bash("):
                deny.append(value)
            elif isinstance(value, str):
                non_shell.append(value)
    return sorted(set(allow)), sorted(set(deny)), sorted(set(non_shell))


def generate_rules() -> str:
    allow, deny, non_shell = load_claude_settings()
    non_shell_comment = ", ".join(non_shell) if non_shell else "none"
    allow_count = len(allow)
    deny_count = len(deny)
    return f"""# Generated by scripts/migrate_codex.py from .claude/settings*.json.
#
# Source summary: {allow_count} shell allow rule(s), {deny_count} shell deny rule(s).
# Non-shell Claude permissions are handled by Codex tools/sandbox instead:
# {non_shell_comment}

prefix_rule(
    pattern = [
        [
            "awk",
            "cat",
            "cd",
            "command",
            "echo",
            "file",
            "find",
            "grep",
            "head",
            "ls",
            "rg",
            "shfmt",
            "shellcheck",
            "stat",
            "strings",
            "tail",
            "tree",
            "unzip",
            "wc",
        ],
    ],
    decision = "allow",
    justification = "Repository inspection and formatting helper commands migrated from Claude allow rules.",
    match = ["rg AGENTS.md", "find . -maxdepth 2 -type f", "shellcheck scripts/container-init.sh"],
    not_match = ["sudo rg AGENTS.md"],
)

prefix_rule(
    pattern = ["git", "-C"],
    decision = "forbidden",
    justification = "Use the current working directory instead of git -C so repository scope stays explicit.",
    match = ["git -C /tmp status"],
    not_match = ["git status"],
)

prefix_rule(
    pattern = ["sudo"],
    decision = "forbidden",
    justification = "Do not use sudo from Codex-managed project workflows.",
    match = ["sudo apt update"],
    not_match = ["apt update"],
)

prefix_rule(
    pattern = ["rm", "-rf", "/"],
    decision = "forbidden",
    justification = "Never remove the filesystem root.",
    match = ["rm -rf /"],
    not_match = ["rm -rf .pytest_cache"],
)

prefix_rule(
    pattern = [
        "git",
        [
            "add",
            "blame",
            "branch",
            "check-ignore",
            "checkout",
            "commit",
            "diff",
            "fetch",
            "log",
            "merge",
            "mv",
            "pull",
            "push",
            "remote",
            "restore",
            "rev-parse",
            "rm",
            "show",
            "stash",
            "status",
            "switch",
            "tag",
        ],
    ],
    decision = "allow",
    justification = "Git operations allowed by the previous Claude project settings and repo merge-main workflow.",
    match = ["git status --short", "git merge origin/main", "git push origin HEAD"],
    not_match = ["git -C /tmp status", "git reset --hard"],
)

prefix_rule(
    pattern = ["just"],
    decision = "allow",
    justification = "The project wraps build, test, proto generation, docs, migration, and Resonite control commands in just recipes.",
    match = ["just run", "just gen-proto", "just migrate-codex"],
)

prefix_rule(
    pattern = ["uv", ["add", "build", "lock", "pip", "python", "python3", "sync", "venv"]],
    decision = "allow",
    justification = "Python environment and packaging commands allowed by the previous Claude project settings.",
    match = ["uv sync --all-extras", "uv pip show grpclib", "uv lock"],
)

prefix_rule(
    pattern = ["uv", "run", ["pre-commit", "pyright", "pytest", "python", "python3", "resoio", "ruff"]],
    decision = "allow",
    justification = "Project Python commands run through uv-managed environments.",
    match = ["uv run pytest", "uv run python -m pytest", "uv run ruff check"],
)

prefix_rule(
    pattern = ["uvx"],
    decision = "allow",
    justification = "Ad-hoc uvx helper execution was allowed in the previous Claude project settings.",
    match = ["uvx pyright --version"],
)

prefix_rule(
    pattern = ["pre-commit", "run"],
    decision = "allow",
    justification = "Pre-commit checks are part of the repository quality gate.",
    match = ["pre-commit run --all-files", "pre-commit run --files AGENTS.md"],
)

prefix_rule(
    pattern = [
        "dotnet",
        [
            "--info",
            "--version",
            "add",
            "build",
            "csharpier",
            "format",
            "ilspycmd",
            "new",
            "remove",
            "restore",
            "sln",
            "test",
            "tool",
        ],
    ],
    decision = "allow",
    justification = ".NET build, test, local-tool, and decompile commands allowed by the previous Claude project settings.",
    match = ["dotnet build", "dotnet tool restore", "dotnet ilspycmd --version"],
)

prefix_rule(
    pattern = ["csharpier"],
    decision = "allow",
    justification = "C# formatting helper allowed by the previous Claude project settings.",
    match = ["csharpier format mod/src"],
)

prefix_rule(
    pattern = ["protoc"],
    decision = "allow",
    justification = "Proto tooling is part of the repository generation workflow.",
    match = ["protoc --version"],
)

prefix_rule(
    pattern = [["./scripts/gen_proto.sh", "scripts/gen_proto.sh"]],
    decision = "allow",
    justification = "Repository proto generation script.",
    match = ["scripts/gen_proto.sh", "./scripts/gen_proto.sh"],
)

prefix_rule(
    pattern = [
        "bash",
        [
            "scripts/container-init.sh",
            "scripts/decompile.sh",
            "scripts/gen_proto.sh",
            "scripts/lib.sh",
            "scripts/renderer-prebuilt-hash.sh",
        ],
    ],
    decision = "allow",
    justification = "Repository scripts under scripts/ were allowed by the previous Claude project settings.",
    match = ["bash scripts/gen_proto.sh", "bash scripts/renderer-prebuilt-hash.sh"],
)

prefix_rule(
    pattern = ["docker", "compose"],
    decision = "allow",
    justification = "Devcontainer and host-agent workflows use docker compose.",
    match = ["docker compose ps", "docker compose -f compose.yml build"],
)

prefix_rule(
    pattern = ["gh"],
    decision = "allow",
    justification = "GitHub CLI operations were allowed in the previous container Claude settings.",
    match = ["gh pr status", "gh pr create --fill"],
)
"""


def sync_rules(migration: Migration) -> None:
    migration.write_text(ROOT / ".codex" / "rules" / "default.rules", generate_rules())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Migrate .claude project assets into Codex mirrors.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if generated Codex assets are stale.",
    )
    parser.add_argument(
        "--include-claude-only",
        action="store_true",
        help="Also copy Claude-only operational skills such as edit-dot-claude.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    migration = Migration(check=args.check)
    sync_skills(migration, include_claude_only=args.include_claude_only)
    sync_agents(migration)
    sync_rules(migration)

    for message in migration.skipped:
        print(f"skip: {message}")
    if migration.changed:
        action = "would update" if args.check else "updated"
        for path in migration.changed:
            print(f"{action}: {path.relative_to(ROOT)}")
        return 1 if args.check else 0
    print(f"Codex migration is up to date ({migration.unchanged} file(s) checked).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
