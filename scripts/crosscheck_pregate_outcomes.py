#!/usr/bin/env python3
"""Retired pregate skip-vs-outcome historical audit.

This tool preserves the evidence that justified H4-4 retirement. Its output
must never authorize an enforce flip or restore dispatch authority; any future
admission heuristic requires a new design, identity, and observation window.

2026-07-10 topology-audit 教訓：當時的 flip criteria 必須連同「歸因儀器」一起設計。
本 script 回答三個問題：

  1. would_skip=true 的班，實際 fire 是否產出實質工作？（誤判率）
     - strict：work_log entry actor 含 'hourly'（該班 fire 自己做的，明確歸因）
     - loose：該小時任何實質 entry（含並行 session — 上界，含歸因雜訊）
     - duration：dispatch_state completions 中對應 fire 的 duration_s >
       --stub-max-s（stub 班應該很短；長 = 疑似有實質工作，不依賴 actor 蓋章）
  2. 歸因儀器健康度：落在 hourly fire active window（dispatch_state completions
     的 [fire_at, fire_at+duration_s]）內的 substantive work_log entries 有 hourly
     蓋章（actor 或 owner）的比例 —— 這是 strict detector 依賴的族群。
     （window-scoped coverage 低 → fire 產出未可靠蓋章 → strict 可能漏判）
     並列 all-population coverage 作資訊性下界：它把 concurrent codex-loop /
     interactive work 也算進分母，故遠低於 window-scoped，不作 gate。
  3. 資料衛生：非 supervisor invoker 的 entries 數（手動/測試污染）

Historical acceptance ceiling（不是復活條件）：
  invoker=supervisor 資料 ≥24h、attribution coverage 高、strict 誤判率 ≤10%。
The final production result was 9/10 false skips, so the gate was retired.

Usage:
    uv run python scripts/crosscheck_pregate_outcomes.py [--since 2026-07-10T00:00:00+00:00]
        [--invoker supervisor] [--window-min 55] [--stub-max-s 900] [--json]
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREGATE_LOG = ROOT / "storage" / "logs" / "hourly_pregate.jsonl"
WORK_LOG = ROOT / "storage" / "work_log.json"
DISPATCH_STATE = ROOT / "storage" / "ops" / "dispatch_state.json"

# Single source (2026-07-10): this file once kept its own copy of the type set
# and drifted from the gate's.  The evaluator is now retired, so the shared
# taxonomy lives in the active domain module rather than under a legacy CLI.
sys.path.insert(0, str(ROOT / "src"))
from volpred.ops.dispatch_outcomes import (
    SUBSTANTIVE_TASK_TYPES as SUBSTANTIVE,
)


def _parse(s) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError as exc:
        logging.debug("crosscheck: unparseable timestamp %r skipped: %s", s, exc)
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _is_hourly_attributed(actor: str, owner: str) -> bool:
    """True when a substantive work_log entry is attributable to an hourly fire.

    A fire stamps its output two ways, so attribution can land in EITHER field:
      - the dispatched agent's work_log convention: actor/owner is the unique
        supervisor-issued ``hourly-slot-<N>-<job_id>`` ownership token.
      - Codex failover uses the equivalent ``codex-failover-slot-<N>-<job_id>``
        token; it still belongs to the same hourly fire.
      - worker._dispatch_actor's VOLPRED_ACTOR default, which reaches shared-state
        writers as "dispatch-worker:volpred-hourly-dispatch:<HHMM>:...". That
        string already carries "hourly" (the schedule id), but the prefix is
        matched explicitly so a future schedule rename can't silently drop it.

    2026-07-14 fix: the old check read `actor` only, so an entry with
    owner="hourly-11" but an empty actor was mis-scored as unstamped. Reading
    both fields makes the numerator match how the agent actually stamps.

    Concurrent codex-loop / interactive work (owner=codex, codex-vscode,
    main-session) is deliberately NOT hourly: it runs independently of the fire
    and must never be counted as the fire's output — doing so would be false
    attribution, not higher coverage.
    """
    values = (str(actor or ""), str(owner or ""))
    return any(
        # ``hourly-<HH>`` is retained for historical rows produced before the
        # slot/job identity fix; new rows use the more specific hourly-slot-*.
        value.startswith("hourly-") or value.startswith("codex-failover-slot-")
        for value in values
    ) or str(actor or "").startswith("dispatch-worker:volpred-hourly-dispatch:")


def _load_pregate(since: datetime | None, invoker: str | None) -> list[dict]:
    out = []
    try:
        lines = PREGATE_LOG.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        print(f"[crosscheck] pregate log missing: {PREGATE_LOG}", file=sys.stderr)
        return out
    for line in lines:
        try:
            e = json.loads(line)
        except json.JSONDecodeError as exc:
            logging.debug("crosscheck: unparseable pregate line skipped: %s | head=%s", exc, line[:60])
            continue
        if "would_skip" not in e and "decision" not in e:
            continue
        ts = _parse(e.get("ts"))
        if ts is None or (since and ts < since):
            continue
        if invoker and e.get("invoker") != invoker:
            continue
        e["_ts"] = ts
        out.append(e)
    return out


def _load_worklog() -> list[tuple[datetime, str, str, str]]:
    """Return (ts, task_type, actor, owner) per work_log entry.

    owner is carried alongside actor because the hourly stamp lands in EITHER
    field in the wild (see _is_hourly_attributed) — an attribution audit that
    read only one of them undercounts.
    """
    try:
        wl = json.loads(WORK_LOG.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"[crosscheck] work_log unreadable ({exc}) — strict/loose 核對不可用", file=sys.stderr)
        return []
    items = wl if isinstance(wl, list) else wl.get("entries", wl.get("log", []))
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        ts = _parse(it.get("ts") or it.get("timestamp"))
        if ts is None:
            continue
        out.append((
            ts,
            str(it.get("task_type") or ""),
            str(it.get("actor") or it.get("claimed_by") or ""),
            str(it.get("owner") or ""),
        ))
    return out


def _load_completions() -> list[tuple[datetime, float]]:
    try:
        st = json.loads(DISPATCH_STATE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"[crosscheck] dispatch_state unreadable ({exc}) — duration 核對不可用", file=sys.stderr)
        return []
    out = []
    for c in st.get("completions") or []:
        ts = _parse(c.get("fire_at"))
        dur = c.get("duration_s")
        if ts is not None and isinstance(dur, (int, float)):
            out.append((ts, float(dur)))
    return out


def _load_fire_windows(since: datetime | None) -> list[tuple[datetime, datetime]]:
    """Active [start, end] intervals of hourly-dispatch fires from dispatch_state.

    A substantive work_log entry that falls inside one of these windows was
    produced WHILE an hourly fire held the slot, so it is attributable to that
    fire and belongs in the coverage denominator. Entries outside every window
    are concurrent non-fire work (codex-loop between fires, interactive
    sessions) that the fire never owned — judging them for an hourly stamp is a
    category error and is exactly what dragged the naive all-population coverage
    to 10% while in-window stamping was ~92% (2026-07-14 topology audit).

    Windows are the fire's [fire_at, fire_at+duration_s]; duration_s is present
    on every completion (task_id is not — completions carry no task link), so
    the window is the only mechanical fire↔work_log join available.
    """
    out = []
    for ts, dur in _load_completions():
        if since is not None and ts < since:
            continue
        out.append((ts, ts + timedelta(seconds=dur)))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default=None, help="ISO timestamp；只看之後的 entries")
    ap.add_argument("--invoker", default=None, help="只採此 invoker 的 entries（flip 重評用 supervisor）")
    ap.add_argument("--window-min", type=int, default=55, help="work_log 歸因窗口（分鐘）")
    ap.add_argument("--stub-max-s", type=float, default=900.0, help="stub 班 duration 上限（秒）；超過視為疑似有實質工作")
    ap.add_argument("--json", action="store_true", help="輸出機器可讀 JSON")
    args = ap.parse_args()

    since = _parse(args.since) if args.since else None
    entries = _load_pregate(since, args.invoker)
    all_entries = _load_pregate(since, None)
    wl = _load_worklog()
    completions = _load_completions()

    # 儀器健康度 — 兩個分母，回答不同問題（2026-07-14 topology audit 修正）：
    #  (all)   每一筆 substantive work_log entry 是否帶 hourly 蓋章？分母被
    #          concurrent codex-loop / interactive work 與 pre-convention 歷史稀釋
    #          （這些本來就不是 hourly fire 的產出），除非把別人的工作假蓋成 hourly，
    #          否則永遠到不了 80% — 只當資訊性下界，不作 gate。
    #  (gate)  落在 hourly fire active window 內的 substantive entries 是否帶 hourly
    #          蓋章？這正是 strict detector 依賴的族群（「fire 真做了工，有沒有蓋章？」），
    #          所以它是 flip gate。
    sub_wl = [w for w in wl if w[1] in SUBSTANTIVE and (since is None or w[0] >= since)]
    stamped_all = [w for w in sub_wl if _is_hourly_attributed(w[2], w[3])]
    coverage_all = (len(stamped_all) / len(sub_wl)) if sub_wl else None

    windows = _load_fire_windows(since)
    in_window = [w for w in sub_wl if any(a <= w[0] <= b for a, b in windows)]
    stamped_win = [w for w in in_window if _is_hourly_attributed(w[2], w[3])]
    coverage = (len(stamped_win) / len(in_window)) if in_window else None

    skips = [e for e in entries if e.get("would_skip") is True or e.get("decision") == "skip"]
    proceeds = [e for e in entries if e.get("would_skip") is False or e.get("decision") == "proceed"]

    strict_mm, loose_mm, dur_mm = [], [], []
    for e in skips:
        ts = e["_ts"]
        end = ts + timedelta(minutes=args.window_min)
        hour_sub = [w for w in wl if ts <= w[0] <= end and w[1] in SUBSTANTIVE]
        if hour_sub:
            loose_mm.append(e["ts"])
        if [w for w in hour_sub if _is_hourly_attributed(w[2], w[3])]:
            strict_mm.append(e["ts"])
        near = [d for (ft, d) in completions if abs((ft - ts).total_seconds()) <= 600]
        if near and max(near) > args.stub_max_s:
            dur_mm.append((e["ts"], max(near)))

    report = {
        "entries_analyzed": len(entries),
        "invoker_filter": args.invoker,
        "pollution_non_supervisor": sum(1 for e in all_entries if e.get("invoker") not in ("supervisor",)),
        "would_skip": len(skips),
        "proceed": len(proceeds),
        "strict_mismatch": len(strict_mm),
        "loose_mismatch": len(loose_mm),
        "duration_mismatch": len(dur_mm),
        "strict_mismatch_rate": (len(strict_mm) / len(skips)) if skips else None,
        "attribution_coverage": coverage,                 # window-scoped = flip gate
        "attribution_window_n": len(in_window),
        "attribution_coverage_all_population": coverage_all,  # informational lower bound
        "attribution_substantive_n": len(sub_wl),
        "verdict_hint": None,
    }
    if skips and coverage is not None:
        if coverage < 0.8:
            report["verdict_hint"] = "attribution coverage 不足（<80%）— strict 數字不可信，先修蓋章再評 flip"
        elif report["strict_mismatch_rate"] is not None and report["strict_mismatch_rate"] <= 0.10 and not dur_mm:
            report["verdict_hint"] = "初步符合 flip 門檻（strict ≤10% 且無 duration 疑似）— 確認資料量 ≥24h 後可評 flip"
        else:
            report["verdict_hint"] = "誤判率或 duration 疑似超標 — 補訊號再觀察，不 flip"

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"[crosscheck] entries={report['entries_analyzed']} (invoker={args.invoker or 'ALL'}) "
              f"skip={report['would_skip']} proceed={report['proceed']}")
        print(f"[crosscheck] mismatch: strict={report['strict_mismatch']} "
              f"loose={report['loose_mismatch']} duration={report['duration_mismatch']}")
        _cov = coverage if coverage is None else f"{coverage:.0%}"
        _cov_all = coverage_all if coverage_all is None else f"{coverage_all:.0%}"
        print(f"[crosscheck] attribution coverage(window-scoped, gate)={_cov} (n={len(in_window)}) | "
              f"all-population={_cov_all} (n={len(sub_wl)}) | "
              f"非 supervisor entries={report['pollution_non_supervisor']}")
        if report["verdict_hint"]:
            print(f"[crosscheck] hint: {report['verdict_hint']}")
        for t, d in dur_mm[:5]:
            print(f"  duration-suspect: {t} fire ran {d:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
