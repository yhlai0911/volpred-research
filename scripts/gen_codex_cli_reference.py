#!/usr/bin/env python3
"""Generate the exhaustive Codex CLI reference from the installed binary.

Why this exists
---------------
The hand-written codex-cli skill drifted from the real CLI and started teaching
commands that fail: `codex exec -a never` (that flag is interactive-only) exits 2
with an empty stdout, which reads like a hang rather than a usage error. A human
cannot keep a 40-command x N-flag surface in sync by hand, so the exhaustive part
is generated from `codex help` and the prose keeps only the judgment.

`codex help <path>` is a pure formatter: it prints and exits, never starting an
agent loop. That is what makes walking the whole tree safe here, and why this
script must never invoke a prompt-bearing subcommand.

Usage:
    uv run python scripts/gen_codex_cli_reference.py            # write reference
    uv run python scripts/gen_codex_cli_reference.py --check    # drift check only
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

from volpred.ops.diagnostics import warn

DEFAULT_OUT = Path.home() / ".claude/skills/codex-cli/references/cli-reference.md"
NPM_LATEST_URL = "https://registry.npmjs.org/@openai/codex/latest"
HELP_TIMEOUT = 20
TAIPEI = timezone(timedelta(hours=8))

# `codex help` on these prints fine, but they are long-running services whose help
# we still want; nothing here ever executes a prompt. Listed for documentation only.
MAX_DEPTH = 2


def run_help(path: list[str]) -> str | None:
    """Return `codex help <path>` output, or None if the node has no help."""
    try:
        proc = subprocess.run(
            ["codex", "help", *path],
            capture_output=True,
            text=True,
            timeout=HELP_TIMEOUT,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        warn("codex-ref", "codex help failed", path=" ".join(path) or "<root>", err=str(e))
        return None
    out = (proc.stdout or "") + (proc.stderr or "")
    return out.strip() or None


def parse_subcommands(help_text: str) -> list[str]:
    """Pull subcommand names out of the `Commands:` block of a help page."""
    lines = help_text.splitlines()
    try:
        start = next(i for i, ln in enumerate(lines) if ln.strip() == "Commands:")
    except StopIteration:
        return []  # silent-ok: leaf command has no `Commands:` block (expected control flow, not an error)
    names: list[str] = []
    for ln in lines[start + 1 :]:
        if not ln.strip():
            continue
        # A new top-level section (e.g. "Options:") ends the block.
        if not ln.startswith(" "):
            break
        if re.match(r"^\s{2,}\S", ln) and not re.match(r"^\s{6,}", ln):
            name = ln.split()[0]
            if name and name != "help" and re.match(r"^[a-z][a-z0-9-]*$", name):
                names.append(name)
    return names


def walk(path: list[str], depth: int, seen: set[str], acc: list[tuple[list[str], str]]) -> None:
    key = " ".join(path)
    if key in seen or depth > MAX_DEPTH:
        return
    seen.add(key)
    help_text = run_help(path)
    if not help_text:
        return
    acc.append((path, help_text))
    for sub in parse_subcommands(help_text):
        walk([*path, sub], depth + 1, seen, acc)


def installed_version() -> str:
    proc = subprocess.run(["codex", "--version"], capture_output=True, text=True, timeout=HELP_TIMEOUT)
    return (proc.stdout or proc.stderr).strip()


def npm_latest() -> str | None:
    try:
        with urllib.request.urlopen(NPM_LATEST_URL, timeout=15) as resp:
            return json.load(resp).get("version")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
        warn("codex-ref", "npm latest lookup failed (drift check skipped)", err=str(e))
        return None


def config_facts() -> list[str]:
    cfg = Path.home() / ".codex/config.toml"
    if not cfg.exists():
        return ["(no ~/.codex/config.toml found)"]
    facts = []
    for ln in cfg.read_text(encoding="utf-8").splitlines():
        s = ln.strip()
        if s.startswith("[") or not s or s.startswith("#"):
            continue
        if any(s.startswith(k) for k in ("model", "sandbox_mode", "approval_policy", "personality")):
            facts.append(s)
    return facts or ["(no scalar keys at top level)"]


def build(version: str, latest: str | None, nodes: list[tuple[list[str], str]]) -> str:
    now = datetime.now(TAIPEI).strftime("%Y-%m-%d %H:%M")
    lines: list[str] = []
    lines.append("# Codex CLI — 完整指令與參數對照（機器產生，勿手改）")
    lines.append("")
    lines.append(f"- **產生時間**：{now} 台灣時間")
    lines.append(f"- **來源**：本機 `codex help` 逐節點輸出（`{version}`）")
    lines.append(f"- **npm `@openai/codex` latest**：{latest or '(查詢失敗)'}")
    lines.append(f"- **重新產生**：`uv run python scripts/gen_codex_cli_reference.py`")
    lines.append("")
    lines.append(
        "> 這份檔是**本機實際安裝的 binary 自己吐的**，不是人寫的摘要。"
        "任何與這裡衝突的說明，以這裡為準；要改內容請改 CLI 版本或重跑產生器，不要手改本檔。"
    )
    lines.append("")
    lines.append(
        "> ⚠️ **但 help 不是全知的**：Codex 有**隱藏 flag**（`codex exec --full-auto` help 裡沒有、"
        "實際吃它且 exit 0），而且 help **完全不列 config.toml 的合法值**"
        "（`model_reasoning_effort` 的 enum 就查不到）。所以本檔窮舉的是「檯面上的 flag」。"
        "**要斷言某個東西不存在，必須實跑，不能只 grep 本檔。**"
    )
    lines.append("")
    lines.append("## 本機 config 實測值（`~/.codex/config.toml`）")
    lines.append("")
    lines.append("```toml")
    lines.extend(config_facts())
    lines.append("```")
    lines.append("")
    lines.append("## 指令樹")
    lines.append("")
    for path, _ in nodes:
        label = " ".join(["codex", *path]) if path else "codex"
        indent = "  " * len(path)
        anchor = "-".join(["codex", *path]).lower()
        lines.append(f"{indent}- [`{label}`](#{anchor})")
    lines.append("")
    for path, help_text in nodes:
        label = " ".join(["codex", *path]) if path else "codex"
        lines.append(f"## {label}")
        lines.append("")
        lines.append("```")
        lines.append(help_text)
        lines.append("```")
        lines.append("")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--check", action="store_true", help="Report drift; do not write")
    args = ap.parse_args()

    if not shutil.which("codex"):
        print("codex binary not found on PATH", file=sys.stderr)
        return 2

    version = installed_version()
    latest = npm_latest()

    if args.check:
        print(f"installed: {version}")
        print(f"npm latest: {latest or '(lookup failed)'}")
        drift = []
        if latest and latest not in version:
            drift.append(f"version drift: installed {version!r} != npm latest {latest!r} → codex update")
        if args.out.exists():
            head = args.out.read_text(encoding="utf-8")[:2000]
            if version not in head:
                drift.append(f"reference stale: {args.out} was generated for a different version")
        else:
            drift.append(f"reference missing: {args.out}")
        for d in drift:
            print(f"DRIFT: {d}")
        return 1 if drift else 0

    nodes: list[tuple[list[str], str]] = []
    walk([], 0, set(), nodes)
    if not nodes:
        print("failed to read any help output", file=sys.stderr)
        return 2

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(build(version, latest, nodes), encoding="utf-8")
    print(f"wrote {args.out} — {len(nodes)} command nodes, version {version}, npm latest {latest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
