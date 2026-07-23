#!/usr/bin/env python3
"""
Token Usage Report — 從 Claude Code 實際 JSONL session 記錄讀取真實 token 用量

主要數據源：~/.claude/projects/<project>/*.jsonl 中的 message.usage 欄位
（每個 assistant message 有真實的 input/output/cache tokens）

次要：git commits 分類（僅供參考，不作為 token 估算依據）

用法：
    python scripts/token_usage_report.py                  # 今日報告
    python scripts/token_usage_report.py --weekly         # 本週摘要
    python scripts/token_usage_report.py --date 2026-04-05
    python scripts/token_usage_report.py --week-start 2026-03-28
"""

import json
import subprocess
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections import Counter, defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _claude_project_dir import (  # noqa: E402
    detect_claude_projects_dir as _detect_claude_projects_dir,
)

CLAUDE_PROJECTS_DIR = _detect_claude_projects_dir()
PROJECT_DIR_SLUG = CLAUDE_PROJECTS_DIR.name  # 實際使用中的目錄名稱（可能是 fallback，非推導 slug）
STORAGE_DIR = Path(__file__).parent.parent / "storage" / "reports" / "token_usage"

# Task categories with emoji + description
CATEGORY_META = {
    "experiment": ("🔬", "研究實驗（Agent 派送 K\\d+ / experiments/ 編輯）"),
    "paper_work": ("📝", "論文撰寫/審查（paper/ *.tex 編輯）"),
    "article_writing": ("✍️", "文章撰寫/發佈（publish-milestone / mile_*）"),
    "knowledge_recording": ("📚", "知識記錄（knowledge.json / thinking_journal）"),
    "research_planning": ("📋", "研究計劃（research_program.md / CLAUDE.md）"),
    "chart_generation": ("📊", "圖表生成（matplotlib / upload_chart）"),
    "script_dev": ("💻", "腳本開發（scripts/ *.py）"),
    "worktree_merge": ("🔀", "Worktree 合併與分支管理"),
    "member_qa": ("❓", "會員問答研究"),
    "platform_ops": ("🛡️", "平台運維（Supabase sync / daily_update）"),
    "skill_invoke": ("⚡", "Skill 呼叫"),
    "skill_edit": ("🔧", "Skill 編輯"),
    "git_sync": ("🔄", "Git commit / pull / push"),
    "knowledge_index": ("📇", "知識索引更新"),
    "token_report": ("📈", "Token 用量報告"),
    "web_research": ("🌐", "WebSearch / WebFetch"),
    "investigation": ("🔍", "閱讀 / 搜尋檔案"),
    "task_management": ("📌", "任務管理（TaskCreate/Update）"),
    "scheduling": ("⏰", "Cron / Monitor 排程"),
    "tool_setup": ("🛠️", "ToolSearch 載入工具"),
    "bash_other": ("💭", "其他 Bash 操作"),
    "file_edit": ("📄", "其他檔案編輯"),
    "agent_delegation": ("🤖", "Agent 派送（非實驗）"),
    "text_only": ("💬", "純文字回覆（無工具）"),
    "other": ("❔", "其他"),
}


def classify_message(content):
    """從 assistant message 的 content 分類此 message 在做的任務"""
    if not isinstance(content, list):
        return "text_only"

    categories = []
    for item in content:
        if not isinstance(item, dict) or item.get("type") != "tool_use":
            continue
        name = item.get("name", "")
        inp = item.get("input", {}) if isinstance(item.get("input"), dict) else {}

        if name == "Agent":
            prompt = str(inp.get("prompt", ""))
            if re.search(r"\bK\d{3,4}\b", prompt):
                categories.append("experiment")
            else:
                categories.append("agent_delegation")

        elif name in ("Edit", "Write"):
            path = str(inp.get("file_path", ""))
            if "paper/" in path and path.endswith((".tex", ".bib")):
                categories.append("paper_work")
            elif "experiments/" in path:
                categories.append("experiment")
            elif "knowledge.json" in path or "thinking_journal" in path or "experiment_experiences" in path:
                categories.append("knowledge_recording")
            elif "research_program.md" in path or "CLAUDE.md" in path:
                categories.append("research_planning")
            elif ".claude/skills" in path:
                categories.append("skill_edit")
            elif "scripts/" in path:
                categories.append("script_dev")
            elif "next_tasks.json" in path:
                categories.append("task_management")
            elif "/memory/" in path and path.endswith(".md"):
                categories.append("knowledge_recording")
            elif "storage/reports/mile_" in path or "feed.json" in path:
                categories.append("article_writing")
            else:
                categories.append("file_edit")

        elif name == "Bash":
            cmd = str(inp.get("command", ""))
            if "publish-milestone" in cmd or "release-pool" in cmd and "release-pool" not in cmd:
                categories.append("article_writing")
            elif "publish-milestone" in cmd:
                categories.append("article_writing")
            elif "git commit" in cmd or "git push" in cmd or "git pull" in cmd:
                categories.append("git_sync")
            elif "git add" in cmd:
                categories.append("git_sync")
            elif "merge_worktree" in cmd or "git worktree" in cmd or "git branch" in cmd or "git merge" in cmd:
                categories.append("worktree_merge")
            elif "supabase_sync" in cmd or "daily_update" in cmd:
                categories.append("platform_ops")
            elif "release-pool" in cmd:
                categories.append("platform_ops")
            elif "build_knowledge_index" in cmd:
                categories.append("knowledge_index")
            elif "question-" in cmd:
                categories.append("member_qa")
            elif "token_usage_report" in cmd:
                categories.append("token_report")
            elif "matplotlib" in cmd or "upload_chart" in cmd or "generate_bar_chart" in cmd or "savefig" in cmd:
                categories.append("chart_generation")
            elif cmd.startswith("grep") or cmd.startswith("rg ") or cmd.startswith("ls ") or cmd.startswith("wc ") or "find " in cmd[:20]:
                categories.append("investigation")
            else:
                categories.append("bash_other")

        elif name in ("Read", "Grep", "Glob"):
            categories.append("investigation")

        elif name in ("CronCreate", "CronDelete", "CronList", "Monitor", "ScheduleWakeup"):
            categories.append("scheduling")

        elif name in ("TaskCreate", "TaskUpdate", "TaskList", "TaskGet", "TaskStop"):
            categories.append("task_management")

        elif name == "Skill":
            categories.append("skill_invoke")

        elif name in ("WebSearch", "WebFetch"):
            categories.append("web_research")

        elif name == "RemoteTrigger":
            categories.append("scheduling")

        elif name == "ToolSearch":
            categories.append("tool_setup")

    if not categories:
        return "text_only"

    # Priority: heaviest work first
    priority = [
        "experiment", "paper_work", "article_writing", "knowledge_recording",
        "research_planning", "script_dev", "chart_generation", "worktree_merge",
        "skill_edit", "member_qa", "platform_ops", "skill_invoke", "git_sync",
        "knowledge_index", "token_report", "web_research",
        "investigation", "task_management", "scheduling", "tool_setup",
        "bash_other", "file_edit", "agent_delegation",
    ]
    for p in priority:
        if p in categories:
            return p
    return categories[0]


# Anthropic pricing (Opus 4.x as of 2026-04，USD per million tokens)
PRICING = {
    "claude-opus-4-8": {  # current opus (2026-07-01)
        "input": 15.00,
        "output": 75.00,
        "cache_write": 18.75,
        "cache_read": 1.50,
    },
    "claude-opus-4-7": {  # prior opus (still in this week's data)
        "input": 15.00,
        "output": 75.00,
        "cache_write": 18.75,
        "cache_read": 1.50,
    },
    "claude-sonnet-5": {  # current sonnet (2026-07-01)
        "input": 3.00,
        "output": 15.00,
        "cache_write": 3.75,
        "cache_read": 0.30,
    },
    "claude-opus-4-6": {
        "input": 15.00,
        "output": 75.00,
        "cache_write": 18.75,  # 1.25x input
        "cache_read": 1.50,    # 0.1x input
    },
    "claude-sonnet-4-6": {
        "input": 3.00,
        "output": 15.00,
        "cache_write": 3.75,
        "cache_read": 0.30,
    },
    "claude-haiku-4-5-20251001": {
        "input": 0.80,
        "output": 4.00,
        "cache_write": 1.00,
        "cache_read": 0.08,
    },
}


def _empty_bucket():
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_create_tokens": 0,
        "messages": 0,
    }


def _usage_breakdown(usage):
    return {
        "input_tokens": usage.get("input_tokens", 0) or 0,
        "output_tokens": usage.get("output_tokens", 0) or 0,
        "cache_read_tokens": usage.get("cache_read_input_tokens", 0) or 0,
        "cache_create_tokens": usage.get("cache_creation_input_tokens", 0) or 0,
    }


def _billable_total(usage_or_bucket):
    return (
        (usage_or_bucket.get("input_tokens", 0) or 0)
        + (usage_or_bucket.get("output_tokens", 0) or 0)
        + (usage_or_bucket.get("cache_create_tokens", 0) or 0)
    )


def _extract_text_content(content):
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    texts = []
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") in {"text", "output_text"}:
            text = item.get("text") or item.get("content") or ""
            if isinstance(text, str) and text.strip():
                texts.append(text.strip())
    return "\n".join(texts)


def _normalize_text_signature(text, limit=160):
    cleaned = " ".join(text.split())
    if not cleaned:
        return "(empty)"
    return cleaned[:limit]


def _text_length_bucket(text):
    length = len(text)
    if length < 200:
        return "<200 chars"
    if length < 800:
        return "200-800 chars"
    if length < 2000:
        return "800-2000 chars"
    return "2000+ chars"


def _classify_text_only_reason(text):
    low = text.lower()
    if not low.strip():
        return "non-text assistant message"
    if "/compact" in low or "context 已滿" in text or "precompact" in low or "context full" in low:
        return "context/compact"
    if (
        "rate limit" in low
        or "quota" in low
        or "spending cap" in low
        or "api key" in low
        or "額度" in text
        or "重設" in text
        or "reset" in low
        or "429" in low
    ):
        return "quota/rate-limit"
    if "review" in low or "finding" in low or "審查" in text or "回歸" in text or "風險" in text:
        return "reviews/findings"
    if "下一步" in text or "follow-up" in low or "next step" in low or "接下來" in text:
        return "planning/follow-up"
    if "summary" in low or "總結" in text or "摘要" in text or "待辦" in text or "backlog" in low or "狀態" in text:
        return "status/summary"
    if "paper" in low or "論文" in text:
        return "paper prose"
    if "setup" in low or "auth" in low or "登入" in text or "就緒" in text:
        return "setup/auth"
    if "experiment" in low or re.search(r"\bK\d{3,4}\b", text):
        return "experiment/result narration"
    return "other"


def _content_signature(content):
    if isinstance(content, list):
        content_types = sorted({
            str(item.get("type"))
            for item in content
            if isinstance(item, dict) and item.get("type")
        })
        if content_types:
            return f"(content types: {', '.join(content_types)})"
    return "(empty)"


def _bash_signature(cmd):
    cmd = cmd.strip()
    if not cmd:
        return "(empty)"
    first_line = cmd.splitlines()[0].strip()
    if not first_line:
        return "(empty)"
    tokens = first_line.split()
    if not tokens:
        return "(empty)"
    head = tokens[0]
    if head in {
        "git", "uv", "python3", "python", "npm", "npx", "jq", "gh", "bash",
        "sh", "ls", "cat", "tail", "head", "cd", "find", "grep", "rg", "wc",
        "awk", "sed", "echo", "date", "test", "cp", "mv",
    }:
        return " ".join(tokens[:3])[:100]
    return head[:100]


def _bash_first_line(cmd, limit=180):
    first_line = cmd.strip().splitlines()[0] if cmd.strip() else ""
    return first_line[:limit] or "(empty)"


def _classify_bash_family(cmd):
    line = _bash_first_line(cmd)
    low = cmd.lower()
    if line.startswith("cd "):
        return "repo navigation"
    if line.startswith("git status") or line.startswith("git log") or line.startswith("git diff") or line.startswith("git rev-parse"):
        return "git inspection"
    if (
        "next_tasks.json" in cmd
        or "storage/ops/tasks" in cmd
        or "scheduler_state" in cmd
        or line.startswith("jq ")
        or line.startswith("python3 -c ")
        or line.startswith("uv run python -c ")
        or line.startswith("python3 <<")
        or line.startswith("python3 <<'")
    ):
        return "inline parsing/json inspection"
    if "crontab" in line or "scheduler.log" in cmd or "check_alerts" in low or line.startswith("date "):
        return "scheduler/cron inspection"
    if line.startswith("tail ") or ".output" in low or "/tmp/" in low or "run.log" in low:
        return "log tailing"
    if line.startswith("cat "):
        return "file dumps"
    if line.startswith("echo ") or line.startswith("test ") or line.startswith("cp "):
        return "shell glue"
    if "npx tsc" in low or "npm run" in low or "deploy" in low or "uv run volpred ops" in low:
        return "ops/build runners"
    return "other bash"


# ---------------------------------------------------------------------------
# Bash 指令大類（owner 2026-07-20：日報最大項 Bash 再拆成指令大類）
#
# 單一分類表：段首指令詞 -> 大類。要調整分類只改這個 dict。
# 取詞規則（_bash_effective_command）：
#   - 只看第一行（heredoc body 不參與判斷）
#   - 以 && / || / ; / | 切段，取第一個有效段；純 cd 段視為導航 glue，改取下一段
#   - 跳過 env 前綴（TZ=... 等）與 wrapper（time / nohup / timeout N / sudo / env ...）
#   - python / python3 / uv run python / uv run <entrypoint> 歸 "uv run python"，
#     另記 scripts/ 檔名（或 entrypoint 名）供 top-N 細分
BASH_BUCKET_PYTHON = "uv run python"
BASH_BUCKET_OTHER = "其他"
BASH_COMMAND_BUCKETS = {
    # git / GitHub
    "git": "git", "gh": "git",
    # 測試
    "pytest": "pytest/測試",
    # 查詢 / 文字處理
    "jq": "jq/grep/查詢", "grep": "jq/grep/查詢", "rg": "jq/grep/查詢",
    "awk": "jq/grep/查詢", "sed": "jq/grep/查詢", "sort": "jq/grep/查詢",
    "uniq": "jq/grep/查詢", "cut": "jq/grep/查詢", "diff": "jq/grep/查詢",
    "xargs": "jq/grep/查詢",
    # Python 執行（uv run python / python3 直呼都歸此類；再細分 scripts/ 名）
    "python": BASH_BUCKET_PYTHON, "python3": BASH_BUCKET_PYTHON,
    # 網路
    "curl": "curl/網路", "wget": "curl/網路", "ping": "curl/網路",
    "dig": "curl/網路", "ssh": "curl/網路", "scp": "curl/網路",
    "rsync": "curl/網路",
    # 檔案系統
    "ls": "ls/檔案系統", "find": "ls/檔案系統", "cat": "ls/檔案系統",
    "head": "ls/檔案系統", "tail": "ls/檔案系統", "wc": "ls/檔案系統",
    "stat": "ls/檔案系統", "du": "ls/檔案系統", "df": "ls/檔案系統",
    "mkdir": "ls/檔案系統", "rm": "ls/檔案系統", "cp": "ls/檔案系統",
    "mv": "ls/檔案系統", "touch": "ls/檔案系統", "chmod": "ls/檔案系統",
    "ln": "ls/檔案系統", "tree": "ls/檔案系統", "cd": "ls/檔案系統",
    "pwd": "ls/檔案系統", "open": "ls/檔案系統",
    # shell glue / 輸出（真實資料中「其他」的最大宗，2026-07-20 dry-run）
    "echo": "echo/shell glue", "printf": "echo/shell glue",
    "date": "echo/shell glue", "sleep": "echo/shell glue",
    "export": "echo/shell glue", "true": "echo/shell glue",
    # 子 shell / .sh 腳本執行
    "bash": "bash/.sh 腳本", "sh": "bash/.sh 腳本", "zsh": "bash/.sh 腳本",
}
_BASH_SEGMENT_SPLIT_RE = re.compile(r"\s*(?:&&|\|\||;|\|)\s*")
_BASH_ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_BASH_WRAPPER_WORDS = {"time", "nohup", "command", "builtin", "exec", "sudo", "caffeinate", "env"}
_UV_VALUE_FLAGS = {"--extra", "--with", "--python", "-p", "--project", "--directory", "--group", "--index"}


def _bash_effective_command(cmd):
    """取第一個有效段的 (指令詞, 該段 tokens)。空 command 回 ("", [])。"""
    stripped = cmd.strip()
    first_line = stripped.splitlines()[0].strip() if stripped else ""
    if not first_line:
        return "", []
    fallback = ("", [])
    for seg in _BASH_SEGMENT_SPLIT_RE.split(first_line):
        tokens = seg.split()
        while tokens:
            head = tokens[0]
            if _BASH_ENV_ASSIGN_RE.match(head) or head in _BASH_WRAPPER_WORDS:
                tokens = tokens[1:]
                continue
            if head == "timeout":
                # timeout DURATION cmd... — 丟掉 timeout 與 duration
                tokens = tokens[1:]
                if tokens and re.match(r"^\d", tokens[0]):
                    tokens = tokens[1:]
                continue
            break
        if not tokens:
            continue
        word = tokens[0].rsplit("/", 1)[-1]  # ./scripts/foo.sh -> foo.sh
        if fallback == ("", []):
            fallback = (word, tokens)
        if word == "cd":
            continue  # 導航 glue：優先用下一段的主指令
        return word, tokens
    return fallback


def _python_script_detail(tokens):
    """從 python 執行的 args 找 script 識別名（供 uv run python 大類的 top-N 細分）。"""
    seen_module_flag = False
    for tok in tokens:
        if tok == "-c":
            return "(inline -c)"
        if tok == "-m":
            seen_module_flag = True
            continue
        if tok.startswith("<<") or tok == "-":
            return "(heredoc/stdin)"
        if tok.startswith("-"):
            continue
        if seen_module_flag:
            return f"(-m {tok})"
        if tok.endswith(".py"):
            idx = tok.find("scripts/")
            return tok[idx:] if idx >= 0 else tok.rsplit("/", 1)[-1]
        # 第一個非 flag arg 不是 .py（如直接跑 console entrypoint）
        return tok.rsplit("/", 1)[-1]
    return "(no script arg)"


def _bash_command_bucket(cmd):
    """一條 Bash command -> (大類, python 細分名或 None)。"""
    word, tokens = _bash_effective_command(cmd)
    if not word:
        return BASH_BUCKET_OTHER, None
    if word == "uv":
        rest = tokens[1:]
        if rest and rest[0] == "run":
            i = 1
            while i < len(rest):
                tok = rest[i]
                if tok in _UV_VALUE_FLAGS:
                    i += 2
                    continue
                if tok.startswith("-"):
                    i += 1
                    continue
                break
            sub = rest[i] if i < len(rest) else ""
            sub_base = sub.rsplit("/", 1)[-1]
            if sub_base in ("python", "python3"):
                return BASH_BUCKET_PYTHON, _python_script_detail(rest[i + 1:])
            mapped = BASH_COMMAND_BUCKETS.get(sub_base)
            if mapped and mapped != BASH_BUCKET_PYTHON:
                return mapped, None
            # uv run volpred / 其他 entrypoint -> 歸 python 類，以 entrypoint 名細分
            return BASH_BUCKET_PYTHON, (sub_base or "(uv run)")
        return BASH_BUCKET_PYTHON, "(uv non-run)"
    bucket = BASH_COMMAND_BUCKETS.get(word)
    if bucket == BASH_BUCKET_PYTHON:
        return bucket, _python_script_detail(tokens[1:])
    if bucket:
        return bucket, None
    return BASH_BUCKET_OTHER, None


def _extract_bash_commands(content):
    """從 assistant content blocks 取出所有 Bash tool_use 的 command 字串。"""
    commands = []
    if not isinstance(content, list):
        return commands
    for item in content:
        if not isinstance(item, dict) or item.get("type") != "tool_use" or item.get("name") != "Bash":
            continue
        inp = item.get("input", {}) if isinstance(item.get("input"), dict) else {}
        cmd = str(inp.get("command", "")).strip()
        if cmd:
            commands.append(cmd)
    return commands


def _warn_token_usage(message: str, path: Path, exc: Exception | None = None, *, line_no: int | None = None) -> None:
    loc = f"{path}"
    if line_no is not None:
        loc = f"{loc}:{line_no}"
    detail = f" error={type(exc).__name__}: {exc}" if exc is not None else ""
    print(f"[token_usage_report] WARN {message} path={loc}{detail}", file=sys.stderr)


def _scan_jsonl(jsonl_path, session_id, is_subagent, target_date_start, target_date_end):
    """Scan a single JSONL file and yield assistant message records."""
    warned_bad_json = False
    warned_bad_timestamp = False
    warned_missing_timestamp = False
    try:
        with open(jsonl_path, "r") as f:
            for line_no, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError as exc:
                    if not warned_bad_json:
                        _warn_token_usage("JSONL line parse failed; skipping", jsonl_path, exc, line_no=line_no)
                        warned_bad_json = True
                    continue

                if obj.get("type") != "assistant":
                    continue

                msg = obj.get("message", {})
                usage = msg.get("usage")
                if not usage:
                    continue

                ts_str = obj.get("timestamp")
                if not ts_str:
                    if not warned_missing_timestamp:
                        _warn_token_usage("assistant usage missing timestamp; skipping", jsonl_path, line_no=line_no)
                        warned_missing_timestamp = True
                    continue

                try:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                except ValueError as exc:
                    if not warned_bad_timestamp:
                        _warn_token_usage("assistant timestamp parse failed; skipping", jsonl_path, exc, line_no=line_no)
                        warned_bad_timestamp = True
                    continue

                ts_date = ts.date()

                if target_date_start and ts_date < target_date_start:
                    continue
                if target_date_end and ts_date >= target_date_end:
                    continue

                model = msg.get("model", "unknown")
                category = classify_message(msg.get("content", []))
                # Subagents: mark as delegated work but keep category for what they do
                if is_subagent and category == "text_only":
                    category = "agent_delegation"
                yield {
                    "timestamp": ts,
                    "date": ts_date,
                    "session_id": session_id,
                    "model": model,
                    "usage": usage,
                    "category": category,
                    "is_subagent": is_subagent,
                    "content": msg.get("content", []),
                    "text_content": _extract_text_content(msg.get("content", [])),
                    # Claude Code writes ONE record per content block, each carrying the
                    # SAME turn-total usage. dedupe by msg_id so usage counts once/turn.
                    "msg_id": msg.get("id"),
                }
    except OSError as exc:
        _warn_token_usage("JSONL file read failed; returning no records", jsonl_path, exc)
        return


def iter_session_records(target_date_start=None, target_date_end=None):
    """遍歷所有 assistant message records（主 session + subagents）。"""
    if not CLAUDE_PROJECTS_DIR.exists():
        return

    # Main session files
    for jsonl_path in sorted(CLAUDE_PROJECTS_DIR.glob("*.jsonl")):
        yield from _scan_jsonl(
            jsonl_path, jsonl_path.stem, False,
            target_date_start, target_date_end,
        )

    # Subagent JSONL files (in <session>/subagents/*.jsonl)
    for sub_path in sorted(CLAUDE_PROJECTS_DIR.glob("*/subagents/*.jsonl")):
        # session_id is the parent dir of subagents/
        session_id = sub_path.parent.parent.name + "/" + sub_path.stem
        yield from _scan_jsonl(
            sub_path, session_id, True,
            target_date_start, target_date_end,
        )


_GENERIC_CATS = {"text_only", "agent_delegation", "cache_diagnostics"}


def _primary_category(cats, is_subagent):
    """A turn's block-records span several categories (thinking/text -> text_only,
    tool_use -> the tool). Attribute the turn to its ACTION category: prefer a
    tool/action category over generic text_only / agent_delegation."""
    for c in cats:
        if c not in _GENERIC_CATS:
            return c
    if is_subagent and "text_only" in cats:
        return "agent_delegation"
    return cats[0] if cats else "text_only"


def aggregate_usage(date_start, date_end):
    """聚合指定日期區間的 token 用量。

    DEDUPE by message.id: Claude Code writes ONE JSONL record per content block
    (thinking / text / tool_use), and EVERY block-record carries the SAME
    turn-total usage. Summing per-record over-counts ~3-4x (verified 2026-07-01:
    a turn's block-records all show identical output_tokens/cache_create). We
    count each message.id's usage ONCE and attribute it to the turn's primary
    (action) category so by_category / by_model sum back to the total."""
    totals = {**_empty_bucket(), "unique_sessions": set(), "subagent_messages": 0, "main_messages": 0}
    by_model = defaultdict(_empty_bucket)
    by_date = defaultdict(_empty_bucket)
    by_category = defaultdict(_empty_bucket)

    turns = {}
    for record in iter_session_records(date_start, date_end):
        mid = record.get("msg_id")
        if not mid:  # no id -> synthetic unique key so it is still counted once
            mid = f"_noid::{record['session_id']}::{record['timestamp'].isoformat()}"
        t = turns.get(mid)
        if t is None:
            t = {"usage": record["usage"], "model": record["model"], "date": record["date"],
                 "session_id": record["session_id"], "is_subagent": record["is_subagent"],
                 "categories": []}
            turns[mid] = t
        t["categories"].append(record["category"])

    for t in turns.values():
        usage = _usage_breakdown(t["usage"])
        cat = _primary_category(t["categories"], t["is_subagent"])
        inp = usage["input_tokens"]
        out = usage["output_tokens"]
        cr = usage["cache_read_tokens"]
        cc = usage["cache_create_tokens"]
        for bucket in (totals, by_model[t["model"]], by_date[t["date"].isoformat()], by_category[cat]):
            bucket["input_tokens"] += inp
            bucket["output_tokens"] += out
            bucket["cache_read_tokens"] += cr
            bucket["cache_create_tokens"] += cc
            bucket["messages"] += 1
        totals["unique_sessions"].add(t["session_id"])
        if t["is_subagent"]:
            totals["subagent_messages"] += 1
        else:
            totals["main_messages"] += 1

    totals["unique_sessions"] = len(totals["unique_sessions"])

    return totals, dict(by_model), dict(by_date), dict(by_category)


def generate_drilldown(date_start, date_end):
    """更細地拆解 text_only / bash_other 與 cache-create 線索。"""
    text_only = {
        "messages": 0,
        "billable_total": 0,
        "length_buckets": defaultdict(lambda: {"messages": 0, "billable_total": 0}),
        "reason_groups": defaultdict(lambda: {"messages": 0, "billable_total": 0}),
        "top_signatures": defaultdict(lambda: {"messages": 0, "billable_total": 0}),
    }
    bash_other = {
        "messages": 0,
        "billable_total": 0,
        "family_breakdown": defaultdict(lambda: {"messages": 0, "billable_total": 0}),
        "prefix_breakdown": defaultdict(lambda: {"messages": 0, "billable_total": 0}),
        "top_first_lines": defaultdict(lambda: {"messages": 0, "billable_total": 0}),
    }
    sessions = {}
    # 全 Bash 呼叫（不限 bash_other 類別）的指令大類拆解；以 msg_id 去重，
    # 因為同一 turn 的每個 content-block record 都帶相同的 turn-total usage。
    bash_turns = {}

    for record in iter_session_records(date_start, date_end):
        usage = _usage_breakdown(record["usage"])
        billable = _billable_total(usage)

        bash_cmds = _extract_bash_commands(record["content"])
        if bash_cmds:
            mid = record.get("msg_id") or f"_noid::{record['session_id']}::{record['timestamp'].isoformat()}"
            bash_turn = bash_turns.setdefault(mid, {"usage": record["usage"], "commands": []})
            bash_turn["commands"].extend(bash_cmds)
        session_bucket = sessions.setdefault(
            record["session_id"],
            {
                "messages": 0,
                "billable_total": 0,
                "cache_create_tokens": 0,
                "cache_read_tokens": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "first_ts": record["timestamp"],
                "last_ts": record["timestamp"],
            },
        )
        session_bucket["messages"] += 1
        session_bucket["billable_total"] += billable
        session_bucket["cache_create_tokens"] += usage["cache_create_tokens"]
        session_bucket["cache_read_tokens"] += usage["cache_read_tokens"]
        session_bucket["input_tokens"] += usage["input_tokens"]
        session_bucket["output_tokens"] += usage["output_tokens"]
        if record["timestamp"] < session_bucket["first_ts"]:
            session_bucket["first_ts"] = record["timestamp"]
        if record["timestamp"] > session_bucket["last_ts"]:
            session_bucket["last_ts"] = record["timestamp"]

        if record["category"] == "text_only":
            text = record["text_content"] or ""
            length_bucket = _text_length_bucket(text)
            reason = _classify_text_only_reason(text)
            signature = _normalize_text_signature(text) if text.strip() else _content_signature(record["content"])

            text_only["messages"] += 1
            text_only["billable_total"] += billable
            text_only["length_buckets"][length_bucket]["messages"] += 1
            text_only["length_buckets"][length_bucket]["billable_total"] += billable
            text_only["reason_groups"][reason]["messages"] += 1
            text_only["reason_groups"][reason]["billable_total"] += billable
            text_only["top_signatures"][signature]["messages"] += 1
            text_only["top_signatures"][signature]["billable_total"] += billable

        elif record["category"] == "bash_other":
            commands = bash_cmds

            if not commands:
                continue

            bash_other["messages"] += 1
            bash_other["billable_total"] += billable
            seen_families = set()
            seen_prefixes = set()
            seen_first_lines = set()
            for cmd in commands:
                family = _classify_bash_family(cmd)
                prefix = _bash_signature(cmd)
                first_line = _bash_first_line(cmd)

                if family not in seen_families:
                    bash_other["family_breakdown"][family]["messages"] += 1
                    seen_families.add(family)
                bash_other["family_breakdown"][family]["billable_total"] += billable

                if prefix not in seen_prefixes:
                    bash_other["prefix_breakdown"][prefix]["messages"] += 1
                    seen_prefixes.add(prefix)
                bash_other["prefix_breakdown"][prefix]["billable_total"] += billable

                if first_line not in seen_first_lines:
                    bash_other["top_first_lines"][first_line]["messages"] += 1
                    seen_first_lines.add(first_line)
                bash_other["top_first_lines"][first_line]["billable_total"] += billable

    # --- Bash 指令大類彙總（token 為該 turn input+output 全額；一 turn 多指令均分） ---
    bucket_stats = defaultdict(lambda: {"commands": 0, "turns": 0, "io": 0.0, "billable": 0.0})
    python_scripts = defaultdict(lambda: {"commands": 0, "io": 0.0})
    bash_total_io = 0
    bash_total_billable = 0
    bash_total_commands = 0
    for bash_turn in bash_turns.values():
        u = _usage_breakdown(bash_turn["usage"])
        io = u["input_tokens"] + u["output_tokens"]
        turn_billable = _billable_total(u)
        cmds = bash_turn["commands"]
        n = len(cmds) or 1
        bash_total_io += io
        bash_total_billable += turn_billable
        bash_total_commands += len(cmds)
        seen_buckets = set()
        for cmd in cmds:
            bucket, script = _bash_command_bucket(cmd)
            st = bucket_stats[bucket]
            st["commands"] += 1
            if bucket not in seen_buckets:
                st["turns"] += 1
                seen_buckets.add(bucket)
            st["io"] += io / n
            st["billable"] += turn_billable / n
            if script:
                ps = python_scripts[script]
                ps["commands"] += 1
                ps["io"] += io / n

    def _bucket_row(name, st):
        return {
            "name": name,
            "commands": st["commands"],
            "turns": st["turns"],
            "input_output_tokens": int(round(st["io"])),
            "billable_total": int(round(st["billable"])),
            "share_pct": round(100 * st["io"] / bash_total_io, 1) if bash_total_io else 0.0,
        }

    sorted_buckets = sorted(
        bucket_stats.items(), key=lambda kv: (-kv[1]["io"], -kv[1]["commands"], kv[0])
    )
    bucket_rows = [_bucket_row(name, st) for name, st in sorted_buckets[:8]]
    rest_buckets = sorted_buckets[8:]
    if rest_buckets:
        rest_agg = {
            "commands": sum(st["commands"] for _, st in rest_buckets),
            "turns": sum(st["turns"] for _, st in rest_buckets),
            "io": sum(st["io"] for _, st in rest_buckets),
            "billable": sum(st["billable"] for _, st in rest_buckets),
        }
        bucket_rows.append(_bucket_row("其餘合計", rest_agg))
    python_scripts_top = [
        {"name": name, "commands": st["commands"], "input_output_tokens": int(round(st["io"]))}
        for name, st in sorted(
            python_scripts.items(), key=lambda kv: (-kv[1]["io"], -kv[1]["commands"], kv[0])
        )[:6]
    ]

    def _sorted_items(mapping, limit=10):
        return [
            {"name": key, **value}
            for key, value in sorted(
                mapping.items(),
                key=lambda item: (-item[1]["billable_total"], -item[1]["messages"], item[0]),
            )[:limit]
        ]

    total_cache_create = sum(bucket["cache_create_tokens"] for bucket in sessions.values())
    total_billable = sum(bucket["billable_total"] for bucket in sessions.values())
    top_sessions = []
    for session_id, bucket in sorted(
        sessions.items(),
        key=lambda item: (-item[1]["cache_create_tokens"], -item[1]["billable_total"], item[0]),
    )[:10]:
        duration_minutes = (bucket["last_ts"] - bucket["first_ts"]).total_seconds() / 60 if bucket["messages"] > 1 else 0.0
        top_sessions.append(
            {
                "session_id": session_id,
                "messages": bucket["messages"],
                "billable_total": bucket["billable_total"],
                "cache_create_tokens": bucket["cache_create_tokens"],
                "cache_read_tokens": bucket["cache_read_tokens"],
                "duration_minutes": round(duration_minutes, 1),
                "cache_create_share_pct": round(
                    100 * bucket["cache_create_tokens"] / bucket["billable_total"], 1
                ) if bucket["billable_total"] else 0.0,
                "first_ts": bucket["first_ts"].isoformat(),
                "last_ts": bucket["last_ts"].isoformat(),
            }
        )

    return {
        "text_only": {
            "messages": text_only["messages"],
            "billable_total": text_only["billable_total"],
            "length_buckets": _sorted_items(text_only["length_buckets"], limit=10),
            "reason_groups": _sorted_items(text_only["reason_groups"], limit=10),
            "top_signatures": _sorted_items(text_only["top_signatures"], limit=12),
        },
        "bash_other": {
            "messages": bash_other["messages"],
            "billable_total": bash_other["billable_total"],
            "family_breakdown": _sorted_items(bash_other["family_breakdown"], limit=10),
            "prefix_breakdown": _sorted_items(bash_other["prefix_breakdown"], limit=12),
            "top_first_lines": _sorted_items(bash_other["top_first_lines"], limit=12),
        },
        "bash_commands": {
            "turns": len(bash_turns),
            "commands": bash_total_commands,
            "input_output_tokens": bash_total_io,
            "billable_total": bash_total_billable,
            "buckets": bucket_rows,
            "python_scripts_top": python_scripts_top,
        },
        "cache_diagnostics": {
            "sessions_in_window": len(sessions),
            "cache_create_tokens": total_cache_create,
            "billable_total": total_billable,
            "cache_create_share_pct": round(100 * total_cache_create / total_billable, 1) if total_billable else 0.0,
            "top_sessions_by_cache_create": top_sessions,
        },
    }


def compute_cost_usd(usage, model):
    """估算 USD 成本（基於 Anthropic pricing）"""
    if model not in PRICING:
        # Fallback: assume Opus pricing
        pricing = PRICING["claude-opus-4-6"]
    else:
        pricing = PRICING[model]

    return (
        usage["input_tokens"] / 1_000_000 * pricing["input"]
        + usage["output_tokens"] / 1_000_000 * pricing["output"]
        + usage["cache_create_tokens"] / 1_000_000 * pricing["cache_write"]
        + usage["cache_read_tokens"] / 1_000_000 * pricing["cache_read"]
    )


# Claude Max 20x weekly quota 重置：週日 16:00 台灣時間 → 次週日 15:59（boss 2026-06-30
# 確認；dashboard「resets Jul 5」= 週日）。舊版用週五對齊（差 2 天）→ 計到錯期間的 token
# → quota % 失真。aggregation 按 ts_date（date-level），故 16:00 內的 sub-day 精度有限：
# 週選擇 honor 16:00 reset（週日 16:00 前算上一週），但同一 Sunday 00:00–16:00 的 token
# 會計入新週（date-level 限制，估算用途可接受；如需 exact 16:00 須改 _scan_jsonl 為 datetime 過濾）。
_TAIPEI_TZ_QUOTA = timezone(timedelta(hours=8))
QUOTA_RESET_HOUR_TPE = 16


def get_quota_week_range(target=None):
    """Quota week = 週日 16:00 台灣 → 次週日（date-level 區間，供 token 聚合）。"""
    if target is None:
        target = datetime.now(timezone.utc)
    if isinstance(target, datetime):
        tpe = target.astimezone(_TAIPEI_TZ_QUOTA)
    else:  # date → 視為當日 00:00 UTC
        tpe = datetime(target.year, target.month, target.day, tzinfo=timezone.utc).astimezone(_TAIPEI_TZ_QUOTA)
    days_since_sunday = (tpe.weekday() - 6) % 7  # Sunday=6
    reset = (tpe - timedelta(days=days_since_sunday)).replace(
        hour=QUOTA_RESET_HOUR_TPE, minute=0, second=0, microsecond=0
    )
    if reset > tpe:  # 今天是週日但還沒到 16:00 → quota 屬上一週
        reset -= timedelta(days=7)
    week_start = reset.date()
    week_end = week_start + timedelta(days=7)
    return week_start, week_end


# 向後相容 alias（舊呼叫點）
def get_friday_week_range(target_date=None):
    return get_quota_week_range(target_date)


def get_git_commits(since, until):
    """補充：取得該時段的 git commits（僅供 context，不用於估算）"""
    cmd = [
        "git", "log", "--oneline", "--format=%h %ai %s",
        f"--since={since.isoformat()}T00:00:00",
        f"--until={until.isoformat()}T00:00:00",
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True,
        cwd=Path(__file__).parent.parent,
    )
    lines = result.stdout.strip().split("\n") if result.stdout.strip() else []
    commits = []
    for line in lines:
        parts = line.split(" ", 3)
        if len(parts) >= 4:
            sha = parts[0]
            rest = " ".join(parts[1:])
            m = re.match(r"(\d{4}-\d{2}-\d{2}) \d{2}:\d{2}:\d{2} [+-]\d{4} (.+)", rest)
            if m:
                commits.append({"sha": sha, "date": m.group(1), "message": m.group(2)})
    return commits


def generate_daily_report(target_date=None, include_commits=False):
    """產出單日報告（基於真實 JSONL usage）"""
    if target_date is None:
        target_date = datetime.now(timezone.utc).date()

    date_start = target_date
    date_end = target_date + timedelta(days=1)

    totals, by_model, by_date, by_category = aggregate_usage(date_start, date_end)
    drilldown = generate_drilldown(date_start, date_end)

    # 計算各模型成本
    cost_by_model = {}
    total_cost_usd = 0.0
    for model, usage in by_model.items():
        cost = compute_cost_usd(usage, model)
        cost_by_model[model] = cost
        total_cost_usd += cost

    # 各類別成本（按消息比例分配到 Opus，因為幾乎全是 Opus）
    cost_by_category = {}
    for cat, usage in by_category.items():
        # Use the dominant model's pricing
        dominant_model = max(by_model.keys(), key=lambda m: by_model[m]["messages"]) if by_model else "claude-opus-4-6"
        cost_by_category[cat] = compute_cost_usd(usage, dominant_model)

    week_start, week_end = get_friday_week_range(target_date)

    report = {
        "report_type": "daily",
        "source": "claude_code_jsonl",
        "date": target_date.isoformat(),
        "week_range": f"{week_start.isoformat()} → {week_end.isoformat()}",
        "totals": {
            "input_tokens": totals["input_tokens"],
            "output_tokens": totals["output_tokens"],
            "cache_read_tokens": totals["cache_read_tokens"],
            "cache_create_tokens": totals["cache_create_tokens"],
            "billable_total": (
                totals["input_tokens"]
                + totals["output_tokens"]
                + totals["cache_create_tokens"]
            ),
            "assistant_messages": totals["messages"],
            "unique_sessions": totals["unique_sessions"],
            "estimated_cost_usd": round(total_cost_usd, 4),
        },
        "by_model": {
            model: {
                **usage,
                "estimated_cost_usd": round(cost_by_model[model], 4),
            }
            for model, usage in by_model.items()
        },
        "by_category": {
            cat: {
                **usage,
                "billable_total": _billable_total(usage),
                "estimated_cost_usd": round(cost_by_category[cat], 4),
                "emoji": CATEGORY_META.get(cat, ("❔", cat))[0],
                "description": CATEGORY_META.get(cat, ("❔", cat))[1],
            }
            for cat, usage in sorted(by_category.items(), key=lambda x: -cost_by_category.get(x[0], 0))
        },
        "drilldown": drilldown,
    }

    if include_commits:
        commits = get_git_commits(date_start, date_end)
        report["git_commits_context"] = [
            {"sha": c["sha"], "message": c["message"][:80]} for c in commits
        ]

    return report


def generate_weekly_report(week_start=None):
    """產出週報（週五到週五，基於真實 JSONL usage）"""
    if week_start is None:
        today = datetime.now(timezone.utc).date()
        week_start, _ = get_friday_week_range(today)

    week_end = week_start + timedelta(days=7)
    totals, by_model, by_date, by_category = aggregate_usage(week_start, week_end)
    drilldown = generate_drilldown(week_start, week_end)

    cost_by_model = {}
    total_cost_usd = 0.0
    for model, usage in by_model.items():
        cost = compute_cost_usd(usage, model)
        cost_by_model[model] = cost
        total_cost_usd += cost

    # 各類別成本
    cost_by_category = {}
    for cat, usage in by_category.items():
        dominant_model = max(by_model.keys(), key=lambda m: by_model[m]["messages"]) if by_model else "claude-opus-4-6"
        cost_by_category[cat] = compute_cost_usd(usage, dominant_model)

    # Per-day breakdown with cost
    daily_breakdown = {}
    for date_key, usage in sorted(by_date.items()):
        # Approximate per-day cost (can't split by model here, use aggregate)
        # More accurate: re-aggregate by date and model. For simplicity, we estimate proportionally.
        day_total = usage["input_tokens"] + usage["output_tokens"] + usage["cache_create_tokens"]
        total_billable = totals["input_tokens"] + totals["output_tokens"] + totals["cache_create_tokens"]
        day_cost = total_cost_usd * (day_total / total_billable) if total_billable else 0
        daily_breakdown[date_key] = {
            **usage,
            "billable_total": day_total,
            "estimated_cost_usd": round(day_cost, 4),
        }

    report = {
        "report_type": "weekly",
        "source": "claude_code_jsonl",
        "week_range": f"{week_start.isoformat()} → {week_end.isoformat()}",
        "totals": {
            "input_tokens": totals["input_tokens"],
            "output_tokens": totals["output_tokens"],
            "cache_read_tokens": totals["cache_read_tokens"],
            "cache_create_tokens": totals["cache_create_tokens"],
            "billable_total": (
                totals["input_tokens"]
                + totals["output_tokens"]
                + totals["cache_create_tokens"]
            ),
            "assistant_messages": totals["messages"],
            "unique_sessions": totals["unique_sessions"],
            "estimated_cost_usd": round(total_cost_usd, 4),
        },
        "by_model": {
            model: {
                **usage,
                "estimated_cost_usd": round(cost_by_model[model], 4),
            }
            for model, usage in by_model.items()
        },
        "by_category": {
            cat: {
                **usage,
                "billable_total": _billable_total(usage),
                "estimated_cost_usd": round(cost_by_category[cat], 4),
                "emoji": CATEGORY_META.get(cat, ("❔", cat))[0],
                "description": CATEGORY_META.get(cat, ("❔", cat))[1],
            }
            for cat, usage in sorted(by_category.items(), key=lambda x: -cost_by_category.get(x[0], 0))
        },
        "daily_breakdown": daily_breakdown,
        "drilldown": drilldown,
    }

    return report


def format_number(n):
    """Format with thousands separator"""
    return f"{n:,}"


def format_report_text(report):
    """格式化為 Markdown 文字"""
    lines = []
    t = report["totals"]

    if report["report_type"] == "daily":
        lines.append(f"# Token 用量日報 — {report['date']}（Claude Code 真實記錄）")
        lines.append(f"**週期**: {report['week_range']}")
    else:
        lines.append(f"# Token 用量週報（Claude Code 真實記錄）")
        lines.append(f"**週期**: {report['week_range']}")

    lines.append(f"**數據源**: {report['source']}")
    lines.append(f"**Assistant messages**: {t.get('assistant_messages', t.get('messages', 0)):,}")
    lines.append(f"**Sessions**: {t['unique_sessions']}")
    lines.append("")

    # Totals table
    lines.append("## Token 分布")
    lines.append("| 類型 | Tokens | 說明 |")
    lines.append("|------|--------|------|")
    lines.append(f"| Input | {t['input_tokens']:,} | 非快取輸入 |")
    lines.append(f"| Output | {t['output_tokens']:,} | Claude 產生的內容 |")
    lines.append(f"| Cache Read | {t['cache_read_tokens']:,} | 重複讀取（便宜）|")
    lines.append(f"| Cache Create | {t['cache_create_tokens']:,} | 首次寫入快取 |")
    lines.append(f"| **Billable** | **{t['billable_total']:,}** | input + output + cache_create |")
    lines.append(f"| **成本估算** | **${t['estimated_cost_usd']}** | 基於 Anthropic pricing |")
    lines.append("")

    # By model
    if report["by_model"]:
        lines.append("## 按模型分布")
        lines.append("| 模型 | Messages | Input | Output | Cache Read | Cost USD |")
        lines.append("|------|----------|-------|--------|-----------|----------|")
        for model, u in sorted(report["by_model"].items(), key=lambda x: -x[1]["messages"]):
            lines.append(
                f"| {model} | {u['messages']:,} | "
                f"{u['input_tokens']:,} | {u['output_tokens']:,} | "
                f"{u['cache_read_tokens']:,} | ${u['estimated_cost_usd']} |"
            )
        lines.append("")

    # By task category
    if report.get("by_category"):
        lines.append("## 按任務類別分布（依成本排序）")
        lines.append("| 類別 | Messages | Billable | Cost USD | 佔比 |")
        lines.append("|------|----------|----------|----------|------|")
        total_cost = t.get("estimated_cost_usd", 0) or 0.0001
        for cat, u in report["by_category"].items():
            pct = u["estimated_cost_usd"] / total_cost * 100 if total_cost else 0
            bar = "█" * max(1, int(pct / 5))
            lines.append(
                f"| {u['emoji']} {u['description']} | {u['messages']:,} | "
                f"{u['billable_total']:,} | ${u['estimated_cost_usd']} | {pct:.1f}% {bar} |"
            )
        lines.append("")

    drilldown = report.get("drilldown") or {}

    bash_cmd = drilldown.get("bash_commands") or {}
    if bash_cmd.get("buckets"):
        lines.append("## Bash 指令大類（全部 Bash 呼叫）")
        lines.append(
            f"- Turns: {bash_cmd.get('turns', 0):,} | Commands: {bash_cmd.get('commands', 0):,}"
            f" | Input+Output: {format_number(bash_cmd.get('input_output_tokens', 0))}"
            f" | Billable: {format_number(bash_cmd.get('billable_total', 0))}"
        )
        lines.append("| 大類 | 次數 | Input+Output | 佔 Bash 比例 |")
        lines.append("|------|------|--------------|--------------|")
        for row in bash_cmd["buckets"]:
            lines.append(
                f"| {row['name']} | {row['commands']:,} | "
                f"{format_number(row['input_output_tokens'])} | {row['share_pct']:.1f}% |"
            )
        if bash_cmd.get("python_scripts_top"):
            lines.append("- uv run python 細分（top scripts）:")
            for item in bash_cmd["python_scripts_top"]:
                lines.append(
                    f"  - {item['name']}: {item['commands']:,} 次 / "
                    f"{format_number(item['input_output_tokens'])} tokens"
                )
        lines.append("- 註：token 為含該指令之 turn 的 input+output 全額；一 turn 多指令時均分。")
        lines.append("")

    text_only = drilldown.get("text_only") or {}
    if text_only:
        lines.append("## Drilldown: 純文字回覆")
        lines.append(
            f"- Messages: {text_only.get('messages', 0):,}"
            f" | Billable: {format_number(text_only.get('billable_total', 0))}"
        )
        if text_only.get("reason_groups"):
            lines.append("- Top reasons:")
            for item in text_only["reason_groups"][:6]:
                lines.append(
                    f"  - {item['name']}: {item['messages']:,} msgs / "
                    f"{format_number(item['billable_total'])} billable"
                )
        if text_only.get("length_buckets"):
            lines.append("- Length buckets:")
            for item in text_only["length_buckets"][:4]:
                lines.append(
                    f"  - {item['name']}: {item['messages']:,} msgs / "
                    f"{format_number(item['billable_total'])} billable"
                )
        if text_only.get("top_signatures"):
            lines.append("- Top repeated signatures:")
            for item in text_only["top_signatures"][:6]:
                lines.append(
                    f"  - {item['messages']:,} msgs / {format_number(item['billable_total'])} billable"
                    f" — {item['name']}"
                )
        lines.append("")

    bash_other = drilldown.get("bash_other") or {}
    if bash_other:
        lines.append("## Drilldown: 其他 Bash 操作")
        lines.append(
            f"- Messages: {bash_other.get('messages', 0):,}"
            f" | Billable: {format_number(bash_other.get('billable_total', 0))}"
        )
        if bash_other.get("family_breakdown"):
            lines.append("- Top families:")
            for item in bash_other["family_breakdown"][:6]:
                lines.append(
                    f"  - {item['name']}: {item['messages']:,} msgs / "
                    f"{format_number(item['billable_total'])} billable"
                )
        if bash_other.get("prefix_breakdown"):
            lines.append("- Top prefixes:")
            for item in bash_other["prefix_breakdown"][:8]:
                lines.append(
                    f"  - {item['messages']:,} msgs / {format_number(item['billable_total'])} billable"
                    f" — `{item['name']}`"
                )
        lines.append("")

    cache_diag = drilldown.get("cache_diagnostics") or {}
    if cache_diag:
        lines.append("## Cache Diagnostics")
        lines.append(
            f"- Sessions in window: {cache_diag.get('sessions_in_window', 0):,}"
            f" | Cache Create share: {cache_diag.get('cache_create_share_pct', 0):.1f}%"
        )
        if cache_diag.get("top_sessions_by_cache_create"):
            lines.append("- Top sessions by cache create:")
            for item in cache_diag["top_sessions_by_cache_create"][:5]:
                lines.append(
                    f"  - `{item['session_id'][:8]}`: {format_number(item['cache_create_tokens'])} cache_create, "
                    f"{item['messages']:,} msgs, {item['duration_minutes']:.1f}m, "
                    f"{item['cache_create_share_pct']:.1f}% of billable"
                )
        lines.append("")

    # Weekly: daily breakdown
    if report["report_type"] == "weekly" and "daily_breakdown" in report:
        lines.append("## 每日分布")
        lines.append("| 日期 | Messages | Billable Tokens | 成本 USD |")
        lines.append("|------|----------|-----------------|----------|")
        for date_key, d in report["daily_breakdown"].items():
            lines.append(
                f"| {date_key} | {d['messages']:,} | "
                f"{d['billable_total']:,} | ${d['estimated_cost_usd']} |"
            )
        lines.append("")

    # Git commits context (optional)
    if "git_commits_context" in report and report["git_commits_context"]:
        lines.append("## Git Commits（僅供參考）")
        for c in report["git_commits_context"][:20]:
            lines.append(f"- `{c['sha']}` {c['message']}")

    return "\n".join(lines)


def save_report(report, text):
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)

    if report["report_type"] == "daily":
        filename = f"daily_{report['date']}.json"
        text_filename = f"daily_{report['date']}.md"
    else:
        week_start = report["week_range"].split(" → ")[0]
        filename = f"weekly_{week_start}.json"
        text_filename = f"weekly_{week_start}.md"

    json_path = STORAGE_DIR / filename
    text_path = STORAGE_DIR / text_filename

    with open(json_path, "w") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    with open(text_path, "w") as f:
        f.write(text)

    return json_path, text_path


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Token Usage Report (Real from JSONL)")
    parser.add_argument("--date", help="指定日期 (YYYY-MM-DD)")
    parser.add_argument("--weekly", action="store_true", help="產出週報")
    parser.add_argument("--week-start", help="週報起始日 (YYYY-MM-DD)")
    parser.add_argument("--detailed", action="store_true", help="包含 git commits context")
    parser.add_argument("--no-save", action="store_true", help="不儲存檔案")
    parser.add_argument("--json", action="store_true", help="JSON 輸出")
    args = parser.parse_args()

    if args.weekly or args.week_start:
        week_start = None
        if args.week_start:
            week_start = datetime.strptime(args.week_start, "%Y-%m-%d").date()
        report = generate_weekly_report(week_start)
    else:
        target_date = None
        if args.date:
            target_date = datetime.strptime(args.date, "%Y-%m-%d").date()
        report = generate_daily_report(target_date, include_commits=args.detailed)

    text = format_report_text(report)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(text)

    if not args.no_save:
        json_path, text_path = save_report(report, text)
        print(f"\n---\n📁 Saved: {json_path.name}, {text_path.name}")


if __name__ == "__main__":
    main()
