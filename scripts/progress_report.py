#!/usr/bin/env python3
"""Structured per-procedure progress report to the boss (Telegram).

Boss pain point (Telegram msg 796, 2026-07-15): the ops manager keeps reporting
"發現問題 → 設計任務 → 下輪解決" and the boss cannot tell whether anything was
actually finished and verified. He asked for a per-procedure structured report
(msg 798 範例) and an optimized version (msg 800/802).

The optimization over his template is the mandatory 驗證 field: a claim of "done"
must carry a real command + result, otherwise this script refuses to emit. That
turns "說做完了" into "證明做完了" mechanically instead of by prose discipline.

Refined by msg 808/810 (boss approved the direction, added two requirements):
  - msg 808「排版要更有架構一點」→ emoji-headed fields + indented values, not a
    wall of text.
  - msg 810「但要說明清楚」→ 驗證 carries a plain-language reading FIRST and the
    raw command second. A bare `exit 0` explains nothing to a non-engineer.

Emitted block (fixed — never hand-type it, this script is the only owner):

  【VolPred 運營回報】
  🕘 <台北時間>｜程序：<程序名>

  ✅ 結論
  　做完 — <一句話，先講結果>

  🔍 驗證
  　白話：<這代表什麼，非工程背景也看得懂>
  　實測：<指令 → 結果/exit code>

  📦 產物
  　<檔案/commit/msg id，可點可查>

  🚧 阻塞
  　<無 / 具體阻塞 + 需老闆決策的點>

  ⏭ 下一步
  　<下一程序@時間>

  📗 已完成（本班）
  　<task_id — 一句話，≤5 條，多的收成「+N 件」>

  🗓 已排程
  　<未來 24h 的 cron job + pending P1-P2 及預計時間，≤5 條>

The last two fields (msg 973, 2026-07-18) have no CLI flags on purpose: they are
derived from storage/next_tasks.json + config/runtime_schedules.json by
volpred.ops.report_sections. A hand-typed「已完成」list is precisely the claim the
驗證 field exists to stop. 已完成 is attributed by --actor (the fire owner token),
so a sibling slot's work never gets credited to this shift.

Strict rules (exit 1 on violation — this is the checker, not a reminder):
  - --status done  REQUIRES --verified (cannot claim done without a measurement)
  - --status done  REQUIRES --verified-cmd (the plain reading needs real evidence)
  - --status done  REQUIRES --artifacts (done with nothing to point at is a smell)
  - exactly one of --verified / --unverified
  - --verified must be plain language, not a pasted command (msg 810)
  - --blocked REQUIRES --blockers
  - 結論 is one line, <= CONCLUSION_MAX chars (short, conclusion-first)

Status vocabulary answers msg 796 directly — 「已修並驗證」vs「已建任務待下輪」
are different statuses, not different phrasings of "done":
  done     已做完且已實測驗證
  queued   已建任務 / 已入 queue，本輪未完成（不得稱做完）
  blocked  卡住，需老闆決策或外部輸入
  failed   做了但失敗

Timestamp comes from the real clock (Asia/Taipei) — per CLAUDE.md, time is data
and must never be fabricated.

Run:
  uv run python scripts/progress_report.py \
    --procedure "PHASE A compute followup" \
    --status done \
    --conclusion "K1426 shard_b 收下了，但照規矩不能合併半套結果，等最後一段跑完" \
    --verified "待辦清單已清空，這批不會再被重複派工" \
    --verified-cmd "compute_queue.py list --pending-followup → [] (exit 0)" \
    --artifacts "job compute-k1426-...-shard-b (followup_dispatched=true)" \
    --next "PHASE B 派工 @19:20" --send
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

TAIPEI = ZoneInfo("Asia/Taipei")
LOG_PATH = PROJECT_ROOT / "storage" / "ops" / "progress_reports.jsonl"
CONCLUSION_MAX = 120

STATUS_LABEL = {
    "done": ("✅", "做完，且已實測驗證"),
    "queued": ("📋", "未完成 — 已建任務／已入 queue，下輪接手"),
    "blocked": ("🚧", "卡住 — 需要外部輸入或老闆決策"),
    "failed": ("❌", "做了但失敗"),
}

# msg 810「要說明清楚」— 白話欄被貼成指令是最常見的退化，機械擋掉。
COMMAND_HEAD = ("uv ", "python", "git ", "curl", "pytest", "bash", "jq ", "npm ", "ls ", "grep")
IND = "　"  # 全形空格：Telegram 不吃 markdown 縮排，用全形空格做視覺層次


def build(args) -> tuple[str, dict]:
    """Return (rendered_block, record). Raises ValueError on contract violation."""
    conclusion = " ".join(args.conclusion.split())
    if len(conclusion) > CONCLUSION_MAX:
        raise ValueError(
            f"結論 {len(conclusion)} 字 > {CONCLUSION_MAX}：一句話講完，細節放產物"
        )
    if args.status == "done" and not args.verified:
        raise ValueError(
            "--status done 必須帶 --verified（白話：實測結果代表什麼）。"
            "只建了任務／還沒實測 → 用 --status queued，不要稱做完（msg 796 痛點）"
        )
    if args.status == "done" and not args.verified_cmd:
        raise ValueError(
            "--status done 必須帶 --verified-cmd（實測指令 + 結果/exit code）—"
            "白話解讀要有證據撐，不能只是宣稱"
        )
    if args.verified and args.verified.strip().startswith(COMMAND_HEAD):
        raise ValueError(
            "--verified 要寫白話（非工程背景也看得懂這代表什麼），指令請放 --verified-cmd（msg 810）"
        )
    if args.status == "done" and not args.artifacts:
        raise ValueError("--status done 必須帶 --artifacts（可點可查的檔案/commit/msg id）")
    if args.status == "blocked" and not args.blockers:
        raise ValueError("--status blocked 必須帶 --blockers（具體阻塞 + 需老闆決策的點）")

    now = datetime.now(TAIPEI)
    icon, label = STATUS_LABEL[args.status]
    lines = [
        "【VolPred 運營回報】",
        f"🕘 {now:%Y-%m-%d %H:%M} 台北時間｜程序：{args.procedure}",
        "",
        f"{icon} 結論",
        f"{IND}{label}",
        f"{IND}{conclusion}",
        "",
        "🔍 驗證",
    ]
    if args.verified:
        lines.append(f"{IND}白話：{args.verified}")
        if args.verified_cmd:
            lines.append(f"{IND}實測：{args.verified_cmd}")
    else:
        lines.append(f"{IND}未驗證：{args.unverified}")
    lines += [
        "",
        "📦 產物",
        f"{IND}{args.artifacts or '無'}",
        "",
        "🚧 阻塞",
        f"{IND}{args.blockers or '無'}",
        "",
        "⏭ 下一步",
        f"{IND}{args.next}",
    ]
    # msg 973：進度可視性兩欄，程式生成不可手打（沒有對應的 CLI 旗標就是刻意的）
    from volpred.ops.report_sections import render_sections

    lines += render_sections(args.actor, indent=IND)
    record = {
        "ts_taipei": now.isoformat(),
        "procedure": args.procedure,
        "status": args.status,
        "conclusion": conclusion,
        "verified": args.verified,
        "verified_cmd": args.verified_cmd,
        "unverified": args.unverified,
        "artifacts": args.artifacts,
        "blockers": args.blockers,
        "next": args.next,
        "actor": args.actor,
    }
    return "\n".join(lines), record


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--procedure", required=True, help="程序名，例如 'PHASE B 派工'")
    ap.add_argument("--status", required=True, choices=sorted(STATUS_LABEL))
    ap.add_argument("--conclusion", required=True, help=f"一句話結論，<= {CONCLUSION_MAX} 字")
    ap.add_argument("--verified", metavar="白話", help="實測結果代表什麼（白話，非工程背景看得懂）")
    ap.add_argument("--verified-cmd", metavar="指令→結果", help="實測指令 + 結果/exit code")
    ap.add_argument("--unverified", metavar="REASON", help="沒驗證的原因（不得留白）")
    ap.add_argument("--artifacts", help="檔案/commit/msg id")
    ap.add_argument("--blockers", help="具體阻塞 + 需老闆決策的點")
    ap.add_argument("--next", required=True, help="下一程序@時間")
    ap.add_argument(
        "--actor",
        default="ops-manager",
        help="回報者；務必傳 $VOLPRED_TASK_CLAIM_OWNER —「已完成（本班）」是按此 token 歸屬，"
        "傳錯這欄會是空的（別班的工也不會被誤算進來）",
    )
    ap.add_argument("--send", action="store_true", help="送到老闆 Telegram 並記 message id")
    args = ap.parse_args()

    if bool(args.verified) == bool(args.unverified):
        print("error: --verified / --unverified 恰好擇一（驗證欄強制，不得留白）", file=sys.stderr)
        return 1

    try:
        block, record = build(args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(block)
    if not args.send:
        return 0

    from volpred.ops.telegram import send_telegram

    resp = send_telegram(block)
    record["sent"] = resp.get("sent", False)
    record["message_ids"] = resp.get("message_ids")
    record["send_reason"] = resp.get("reason")
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    if not record["sent"]:
        print(f"error: telegram 未送出 — {record['send_reason']}", file=sys.stderr)
        return 1
    print(f"[progress-report] sent message_ids={record['message_ids']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
