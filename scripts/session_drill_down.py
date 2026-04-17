#!/usr/bin/env python3
"""
Session Drill-Down — token_usage_report.py 的補強

對單一 session（或某日所有 session）做更細的拆解：
- Per-session cost / messages / 起訖時間
- Agent 派送 by subagent_type
- Bash 命令前 N 重複統計
- Tool call 計數（Bash / Agent / Read / Edit / Write / Grep / Glob / Skill）

用法：
    uv run python scripts/session_drill_down.py                         # 今天 top sessions
    uv run python scripts/session_drill_down.py --date 2026-04-17       # 指定日
    uv run python scripts/session_drill_down.py --session a10f7b0f      # 單一 session
    uv run python scripts/session_drill_down.py --top 5 --commands 20   # 顯示前 5 個 session、前 20 個重複命令
"""

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_DIR_SLUG = "-Users-yhlai0911-Desktop-volpred-research"
CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects" / PROJECT_DIR_SLUG

PRICING = {
    "claude-opus-4-7": {"input": 15.0, "output": 75.0, "cw": 18.75, "cr": 1.50},
    "claude-opus-4-6": {"input": 15.0, "output": 75.0, "cw": 18.75, "cr": 1.50},
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0, "cw": 3.75, "cr": 0.30},
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.0, "cw": 1.0, "cr": 0.08},
}


def cost_of(usage, model):
    p = PRICING.get(model, PRICING["claude-opus-4-7"])
    return (
        usage.get("input_tokens", 0) / 1e6 * p["input"]
        + usage.get("output_tokens", 0) / 1e6 * p["output"]
        + usage.get("cache_creation_input_tokens", 0) / 1e6 * p["cw"]
        + usage.get("cache_read_input_tokens", 0) / 1e6 * p["cr"]
    )


def bash_cmd_signature(cmd: str) -> str:
    """把 bash 命令簡化為「特徵簽名」，用於統計重複類型。

    - 取第一個詞（程式名）
    - 對 git / uv / python3 等多 token 命令，取前 2-3 個 token
    """
    cmd = cmd.strip()
    if not cmd:
        return "(empty)"
    # heredoc / multi-line script
    if cmd.startswith("cat <<") or "<<EOF" in cmd[:80] or "<<'EOF'" in cmd[:80]:
        return "(heredoc script)"
    # shebang or python inline
    first_line = cmd.split("\n", 1)[0].strip()
    tokens = first_line.split()
    if not tokens:
        return "(empty)"
    head = tokens[0]
    if head in {"git", "uv", "python3", "python", "npm", "bun", "jq", "gh", "bash", "sh", "ls", "cat", "tail", "head", "cd", "find", "grep", "rg", "wc", "awk", "sed"}:
        # take up to 3 tokens
        sig = " ".join(tokens[:3])
        return sig[:80]
    return head[:80]


def scan_jsonl(jsonl_path: Path):
    """Return list of (timestamp, role, content_list, usage, model) per assistant message."""
    out = []
    try:
        with open(jsonl_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("type") != "assistant":
                    continue
                msg = obj.get("message", {})
                ts_str = obj.get("timestamp")
                if not ts_str:
                    continue
                try:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                except ValueError:
                    continue
                out.append((ts, msg.get("content", []), msg.get("usage") or {}, msg.get("model", "unknown")))
    except IOError:
        return []
    return out


def analyze_session(jsonl_path: Path, date_filter=None):
    """Aggregate one session's metrics.

    date_filter: 若給定，只統計該日的 messages（lifetime 統計仍會計算）。
    """
    msgs = scan_jsonl(jsonl_path)
    if not msgs:
        return None

    tool_counter = Counter()  # 指定日（or all）
    agent_types = Counter()
    bash_sigs = Counter()
    edit_paths = Counter()

    cost = 0.0  # in date_filter scope
    in_tok = out_tok = cr_tok = cw_tok = 0
    msgs_in_scope = 0

    lifetime_cost = 0.0
    lifetime_msgs = len(msgs)
    lifetime_cr = 0

    first_ts = None
    last_ts = None
    first_ts_in_scope = None
    last_ts_in_scope = None

    for ts, content, usage, model in msgs:
        if first_ts is None or ts < first_ts:
            first_ts = ts
        if last_ts is None or ts > last_ts:
            last_ts = ts
        msg_cost = cost_of(usage, model)
        lifetime_cost += msg_cost
        lifetime_cr += usage.get("cache_read_input_tokens", 0) or 0

        if date_filter is not None and ts.astimezone(timezone.utc).date() != date_filter:
            continue

        msgs_in_scope += 1
        if first_ts_in_scope is None or ts < first_ts_in_scope:
            first_ts_in_scope = ts
        if last_ts_in_scope is None or ts > last_ts_in_scope:
            last_ts_in_scope = ts

        in_tok += usage.get("input_tokens", 0) or 0
        out_tok += usage.get("output_tokens", 0) or 0
        cr_tok += usage.get("cache_read_input_tokens", 0) or 0
        cw_tok += usage.get("cache_creation_input_tokens", 0) or 0
        cost += msg_cost

        if not isinstance(content, list):
            continue
        for item in content:
            if not isinstance(item, dict) or item.get("type") != "tool_use":
                continue
            name = item.get("name", "")
            inp = item.get("input", {}) if isinstance(item.get("input"), dict) else {}
            tool_counter[name] += 1
            if name == "Agent":
                agent_types[inp.get("subagent_type") or "default"] += 1
            elif name == "Bash":
                bash_sigs[bash_cmd_signature(str(inp.get("command", "")))] += 1
            elif name in ("Edit", "Write"):
                path = str(inp.get("file_path", ""))
                parts = path.replace(str(Path.home()), "~").split("/")
                top = "/".join(parts[:5]) if len(parts) > 4 else path
                edit_paths[top] += 1

    if msgs_in_scope == 0 and date_filter is not None:
        return None

    use_first = first_ts_in_scope or first_ts
    use_last = last_ts_in_scope or last_ts
    return {
        "session_id": jsonl_path.stem,
        "path": str(jsonl_path),
        "messages": msgs_in_scope if date_filter else lifetime_msgs,
        "first_ts": use_first,
        "last_ts": use_last,
        "duration_min": (use_last - use_first).total_seconds() / 60 if use_first and use_last else 0,
        "cost_usd": cost if date_filter else lifetime_cost,
        "lifetime_cost_usd": lifetime_cost,
        "lifetime_messages": lifetime_msgs,
        "lifetime_cache_read": lifetime_cr,
        "lifetime_first_ts": first_ts,
        "lifetime_last_ts": last_ts,
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "cache_read_tokens": cr_tok,
        "cache_create_tokens": cw_tok,
        "tools": dict(tool_counter),
        "agent_types": dict(agent_types),
        "top_bash": bash_sigs.most_common(30),
        "top_edits": edit_paths.most_common(10),
        "scoped_to_date": date_filter,
    }


def find_sessions(date, session_prefix):
    """找出 candidate sessions。日期篩選交給 analyze_session 做精確判定。"""
    if not CLAUDE_PROJECTS_DIR.exists():
        return []
    paths = []
    for p in CLAUDE_PROJECTS_DIR.glob("*.jsonl"):
        if session_prefix and not p.stem.startswith(session_prefix):
            continue
        if date:
            # 寬鬆篩選：mtime 在指定日 ±1 天的都掃，跨日 session 才不會漏
            mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).date()
            if abs((mtime - date).days) > 1 and mtime < date:
                continue
        paths.append(p)
    return paths


def fmt_duration(mins: float) -> str:
    if mins < 60:
        return f"{mins:.0f}m"
    return f"{mins/60:.1f}h"


def render_session(s: dict, n_commands: int = 15):
    lines = []
    scope_label = f"on {s['scoped_to_date']}" if s.get("scoped_to_date") else "lifetime"
    lines.append(f"## Session `{s['session_id'][:8]}` ({scope_label})")
    lines.append(f"- **Cost ({scope_label})**: ${s['cost_usd']:.2f}")
    lines.append(f"- **Messages**: {s['messages']:,} ({fmt_duration(s['duration_min'])})")
    lines.append(f"- **Span ({scope_label})**: {s['first_ts'].astimezone().isoformat(timespec='minutes')} → {s['last_ts'].astimezone().isoformat(timespec='minutes')}")
    lines.append(f"- **Tokens ({scope_label})**: in={s['input_tokens']:,} out={s['output_tokens']:,} "
                 f"cache_read={s['cache_read_tokens']:,} cache_create={s['cache_create_tokens']:,}")
    if s.get("scoped_to_date") and s.get("lifetime_messages") != s["messages"]:
        lifetime_dur = (s["lifetime_last_ts"] - s["lifetime_first_ts"]).total_seconds() / 3600
        lines.append(
            f"- **Lifetime context**: {s['lifetime_messages']:,} msgs over {lifetime_dur:.1f}h, "
            f"${s['lifetime_cost_usd']:.2f} total, cache_read accumulated {s['lifetime_cache_read']/1e9:.2f}B tokens"
        )
        if lifetime_dur > 24:
            lines.append(f"  ⚠️ **Long-lived session ({lifetime_dur/24:.1f} days)** — consider /clear to reset cache")

    if s["tools"]:
        lines.append("\n**Tool calls**:")
        for name, n in sorted(s["tools"].items(), key=lambda x: -x[1]):
            lines.append(f"  - {name}: {n}")

    if s["agent_types"]:
        lines.append("\n**Agent types**:")
        for t, n in sorted(s["agent_types"].items(), key=lambda x: -x[1]):
            lines.append(f"  - {t}: {n}")

    if s["top_bash"]:
        lines.append(f"\n**Top {min(n_commands, len(s['top_bash']))} Bash signatures**:")
        for sig, n in s["top_bash"][:n_commands]:
            lines.append(f"  - {n:>4}× `{sig}`")

    if s["top_edits"]:
        lines.append("\n**Top Edit/Write targets** (top 10):")
        for path, n in s["top_edits"]:
            lines.append(f"  - {n:>3}× {path}")

    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser(description="Session drill-down for Claude Code JSONL sessions")
    p.add_argument("--date", help="YYYY-MM-DD（預設今天 UTC）")
    p.add_argument("--session", help="Session ID prefix（單 session 模式）")
    p.add_argument("--top", type=int, default=5, help="顯示前 N 個 session（按 cost 排序）")
    p.add_argument("--commands", type=int, default=15, help="顯示每 session 前 N 個 bash 重複命令")
    p.add_argument("--all", action="store_true", help="顯示所有當日 session（不限 top N）")
    args = p.parse_args()

    target_date = None
    if args.date:
        target_date = datetime.strptime(args.date, "%Y-%m-%d").date()
    elif not args.session:
        target_date = datetime.now(timezone.utc).date()

    paths = find_sessions(target_date, args.session)
    if not paths:
        print(f"找不到 sessions（date={target_date}, prefix={args.session}）")
        return

    sessions = []
    for path in paths:
        s = analyze_session(path, date_filter=target_date)
        if s and s["messages"] > 0:
            sessions.append(s)

    sessions.sort(key=lambda s: -s["cost_usd"])

    total_cost = sum(s["cost_usd"] for s in sessions)
    total_msgs = sum(s["messages"] for s in sessions)

    header = f"# Session Drill-Down — {target_date or args.session}"
    print(header)
    print(f"\n**Total**: {len(sessions)} sessions, {total_msgs:,} messages, **${total_cost:.2f}**\n")

    print("## Sessions by cost")
    print("| Session | Cost | Msgs | Duration | Bash | Agent | Read | Edit |")
    print("|---------|------|------|----------|------|-------|------|------|")
    for s in sessions:
        t = s["tools"]
        print(
            f"| `{s['session_id'][:8]}` | ${s['cost_usd']:.2f} | "
            f"{s['messages']:,} | {fmt_duration(s['duration_min'])} | "
            f"{t.get('Bash', 0)} | {t.get('Agent', 0)} | "
            f"{t.get('Read', 0)} | {t.get('Edit', 0) + t.get('Write', 0)} |"
        )
    print()

    show = sessions if args.all else sessions[: args.top]
    for s in show:
        print(render_session(s, n_commands=args.commands))
        print()


if __name__ == "__main__":
    main()
