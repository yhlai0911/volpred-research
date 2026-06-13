"""Multi-source task generator — beyond single-source publication_candidates.

Background: 2026-05-07 audit revealed `refill_task_pool.py` only sources from
`publication_candidates.json` → only emits `daily_article` tasks. Real pool needs
diverse types per `.claude/rules/agent-delegation.md` (10 types). This generator
adds non-article task types from independent signals:

1. **paper_review** — articles published in last 24h without Codex review;
   sampled to control quota (max 3/day per stub).
2. **platform_ops** — cron last-run gap > threshold (stub; reads
   `storage/ops/cron_last_run.json`).
3. **governance** — placeholder for skill-audit cadence (stub).
4. **strategy_lifecycle** — placeholder for STRATEGY_REGISTRY review (stub).

Each generated task has `source='diverse_gen'` so dispatcher / refill can
distinguish from auto_discovered article tasks. Idempotent: rerunning won't
duplicate (checks existing IDs).

Usage:
  uv run python scripts/generate_diverse_tasks.py --apply
  uv run python scripts/generate_diverse_tasks.py --dry-run --json
"""
from __future__ import annotations

import argparse
import fcntl
import json
import random
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NEXT_TASKS = ROOT / "storage" / "next_tasks.json"
FEED = ROOT / "storage" / "reports" / "feed.json"
CRON_LAST_RUN = ROOT / "storage" / "ops" / "cron_last_run.json"
RUNTIME_SCHEDULES = ROOT / "config" / "runtime_schedules.json"
CRON_LOGS = ROOT / "storage" / "logs" / "cron"
SKILLS_DIR = ROOT / ".claude" / "skills"
ERROR_LOG = ROOT / "docs" / "error_log.md"

# Per-source quotas — tune as needed.
QUOTA_PAPER_REVIEW = 3   # max paper_review tasks per generator run
QUOTA_PLATFORM_OPS = 2
QUOTA_GOVERNANCE = 1
QUOTA_EXPERIMENT = 2     # 2026-05-08 v2 extension: backlog scan
PAPER_REVIEW_AGE_HOURS = 24
SKILL_STALE_DAYS = 30
ERROR_LOG_REVIEW_THRESHOLD = 40  # `### ` headings — trigger sweep when accumulated

EXPERIMENTS_DIR = ROOT / "experiments"
RESEARCH_PROGRAM = ROOT / "research_program.md"


def _load_tasks(max_retries: int = 5, sleep_s: float = 0.1) -> tuple[dict | list, list]:
    if not NEXT_TASKS.exists():
        return [], []
    last_err: Exception | None = None
    for attempt in range(max_retries):
        with NEXT_TASKS.open("r", encoding="utf-8") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_SH)
            try:
                data = json.load(fh)
            except json.JSONDecodeError as exc:
                last_err = exc
            else:
                if isinstance(data, dict):
                    return data, data.get("tasks", [])
                return data, data
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        if attempt < max_retries - 1:
            time.sleep(sleep_s)
    raise SystemExit(f"failed to parse {NEXT_TASKS} after {max_retries} retries: {last_err}")


def _save_tasks(payload: dict | list, tasks: list) -> None:
    if isinstance(payload, dict) and "tasks" in payload:
        payload["tasks"] = tasks
        out = payload
    else:
        out = tasks
    NEXT_TASKS.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _existing_ids(tasks: list) -> set[str]:
    return {t.get("id", "") for t in tasks if t.get("id")}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _experiment_dir_covers_kid(dirname: str, kid_lower: str) -> bool:
    """Return True when an experiment directory belongs to a K-id.

    Experiment folders commonly use descriptive suffixes, e.g.
    `k1458_h1_trough_decomposition`; treating only exact `k1458` as present
    causes false scaffold tasks for completed experiments.
    """
    name = dirname.lower()
    return name == kid_lower or name.startswith(f"{kid_lower}_")


def gen_paper_review_tasks(existing: set[str], rng: random.Random) -> list[dict]:
    """Sample articles published in last 24h that lack Codex review tag."""
    if not FEED.exists():
        return []
    feed = json.loads(FEED.read_text(encoding="utf-8"))
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=PAPER_REVIEW_AGE_HOURS)).isoformat()

    candidates = []
    for art in feed:
        if not isinstance(art, dict):
            continue
        if art.get("status") != "published":
            continue
        pub = art.get("published_at") or ""
        if pub < cutoff:
            continue
        tags = art.get("tags") or []
        if any("codex-reviewed" in t.lower() or "post-review" in t.lower() for t in tags):
            continue
        audience = art.get("audience") or (art.get("details") or {}).get("audience") or ""
        if audience == "daily":
            continue
        details = art.get("details") or {}
        experiment_refs = details.get("experiment_refs") or []
        if not experiment_refs:
            continue
        aid = art.get("id")
        if not aid:
            continue
        task_id = f"paper_review_{aid}"
        if task_id in existing:
            continue
        candidates.append((aid, art.get("title", "")[:80]))

    if not candidates:
        return []

    rng.shuffle(candidates)
    sampled = candidates[:QUOTA_PAPER_REVIEW]

    return [{
        "id": f"paper_review_{aid}",
        "title": f"Paper review (Codex 24h-rule): {title}",
        "description": (
            f"Per .claude/rules/agent-delegation.md 2026-05-02 K1018 lesson, "
            f"production article {aid} needs Codex source-code-level review within "
            f"24h of publish. Pipe article description through `codex exec --skip-git-repo-check` "
            f"with prompt requesting algorithm/claim verification, esp. lookahead "
            f"and DM/Harvey overclaims."
        ),
        "priority": 4,
        "status": "pending",
        "task_type": "paper_review",
        "source": "diverse_gen",
        "article_id": aid,
        "tags": ["paper-review", "codex-24h-rule", "main-thread-only"],
        "created_at": _now_iso(),
    } for aid, title in sampled]


def _parse_cron_gap_seconds(cron: str) -> int | None:
    """Return rough expected gap between cron firings, in seconds.

    Conservative — only handles common patterns we actually use. Returns None
    for shapes we can't confidently estimate (so we won't false-flag staleness).
    """
    parts = cron.strip().split()
    if len(parts) != 5:
        return None
    minute, hour, dom, month, dow = parts
    if minute.startswith("*/") and hour == "*":
        try:
            return int(minute[2:]) * 60
        except ValueError:
            return None
    if minute.isdigit() and hour.startswith("*/"):
        try:
            return int(hour[2:]) * 3600
        except ValueError:
            return None
    if minute.isdigit() and hour == "*":
        return 3600
    if minute.isdigit() and hour.isdigit() and dom == "*" and dow == "*":
        return 86400
    if minute.isdigit() and hour.isdigit() and dow != "*":
        return 7 * 86400
    return None


def _parse_banner_ts(text: str) -> datetime | None:
    m = re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:\+00:00|\+\d{4})", text)
    if m:
        raw = m.group(0)
        if re.search(r"[+-]\d{4}$", raw):
            raw = raw[:-5] + raw[-5:-2] + ":" + raw[-2:]
        try:
            return datetime.fromisoformat(raw).astimezone(timezone.utc)
        except ValueError:
            pass
    m = re.search(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}", text)
    if m:
        try:
            return datetime.strptime(
                m.group(0).replace("T", " "),
                "%Y-%m-%d %H:%M:%S",
            ).replace(tzinfo=timezone(timedelta(hours=8))).astimezone(timezone.utc)
        except ValueError:
            pass
    m = re.search(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?!:)", text)
    if m:
        try:
            return datetime.strptime(
                m.group(0).replace("T", " "),
                "%Y-%m-%d %H:%M",
            ).replace(tzinfo=timezone(timedelta(hours=8))).astimezone(timezone.utc)
        except ValueError:
            return None
    return None


def _latest_cron_log_ts(job_id: str, log_rel: str | None = None) -> datetime | None:
    if log_rel:
        candidate = ROOT / log_rel if not log_rel.startswith("/") else Path(log_rel)
        log_path = candidate if candidate.exists() else CRON_LOGS / f"{job_id}.log"
    else:
        log_path = CRON_LOGS / f"{job_id}.log"
    if not log_path.exists():
        return None
    try:
        lines = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        if "===" not in line:
            continue
        ts = _parse_banner_ts(line)
        if ts is not None:
            return ts
    try:
        return datetime.fromtimestamp(log_path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return None


def gen_platform_ops_tasks(existing: set[str]) -> list[dict]:
    """Detect stale cron jobs — prefer recent log banner over stale cron_last_run."""
    if not CRON_LAST_RUN.exists() or not RUNTIME_SCHEDULES.exists():
        return []
    last_run = json.loads(CRON_LAST_RUN.read_text(encoding="utf-8"))
    schedules = json.loads(RUNTIME_SCHEDULES.read_text(encoding="utf-8"))
    crontab_items = (schedules.get("system_crontab") or {}).get("items") or []

    now = datetime.now(timezone.utc)
    stale: list[tuple[str, str, int, int]] = []  # (id, last_iso, gap_s, expected_s)
    for item in crontab_items:
        cid = item.get("id")
        cron_expr = item.get("cron")
        if not cid or not cron_expr:
            continue
        if item.get("host_crontab_managed") is False:
            continue
        expected = _parse_cron_gap_seconds(cron_expr)
        if expected is None:
            continue
        last_iso = last_run.get(cid)
        log_rel = item.get("log_path")
        log_dt = _latest_cron_log_ts(cid, log_rel)
        if not last_iso:
            if log_dt is None:
                continue
            last_dt = log_dt
            last_iso = log_dt.isoformat()
        else:
            try:
                last_dt = datetime.fromisoformat(last_iso.replace("Z", "+00:00"))
            except Exception:
                continue
        if log_dt and log_dt > last_dt:
            last_dt = log_dt
            last_iso = last_dt.isoformat()
        gap = int((now - last_dt).total_seconds())
        if gap > 2 * expected and gap > 3600:  # absolute floor 1h to skip recently-fired
            stale.append((cid, last_iso, gap, expected))

    stale.sort(key=lambda x: x[2] / x[3], reverse=True)  # worst overdue first
    sampled = stale[:QUOTA_PLATFORM_OPS]
    out = []
    for cid, last_iso, gap, expected in sampled:
        task_id = f"platform_ops_cron_stale_{cid}"
        if task_id in existing:
            continue
        gap_h = gap / 3600
        exp_h = expected / 3600
        out.append({
            "id": task_id,
            "title": f"Cron staleness: {cid} — last fire {gap_h:.1f}h ago (expected ≤{2 * exp_h:.1f}h)",
            "description": (
                f"`{cid}` last ran at {last_iso} ({gap_h:.1f}h ago). Expected cadence "
                f"per config/runtime_schedules.json gives gap ≤{exp_h:.1f}h; "
                f"observed >2x. Investigate: (a) wrapper script exists & executable, "
                f"(b) recent log at storage/logs/cron/{cid}.log, "
                f"(c) launchd / crontab entry actually installed, "
                f"(d) downstream consumer (release_pool / daily_update) for failure cascade."
            ),
            "priority": 3,
            "status": "pending",
            "task_type": "platform_ops",
            "source": "diverse_gen",
            "tags": ["platform-ops", "cron-staleness", "main-thread-only"],
            "created_at": _now_iso(),
        })
    return out


def gen_governance_tasks(existing: set[str]) -> list[dict]:
    """Skill audit cadence + error_log accumulation review.

    Two governance signals:
    1. Stale skill: any SKILL.md not touched in > SKILL_STALE_DAYS — emit single
       audit task per generator run (low-frequency; one slot only).
    2. error_log accumulation: if `### ` heading count > threshold and no recent
       sweep marker — emit error_log review task. (For now we just check raw count;
       a sweep marker file is a follow-up.)

    Capped at QUOTA_GOVERNANCE total across both signals to avoid governance noise.
    """
    out: list[dict] = []
    now = datetime.now(timezone.utc)

    # Signal 1 — skill mtime audit
    if SKILLS_DIR.exists() and len(out) < QUOTA_GOVERNANCE:
        stale_skills: list[tuple[str, float]] = []
        cutoff = now.timestamp() - SKILL_STALE_DAYS * 86400
        for skill_md in SKILLS_DIR.glob("*/SKILL.md"):
            try:
                m = skill_md.stat().st_mtime
            except OSError:
                continue
            if m < cutoff:
                stale_skills.append((skill_md.parent.name, m))
        if stale_skills:
            stale_skills.sort(key=lambda x: x[1])  # oldest first
            oldest_name = stale_skills[0][0]
            stale_count = len(stale_skills)
            task_id = f"governance_skill_audit_{datetime.now(timezone.utc).strftime('%Y%m%d')}"
            if task_id not in existing and not any(
                e.startswith("governance_skill_audit_") for e in existing
            ):
                out.append({
                    "id": task_id,
                    "title": f"Governance: {stale_count} skill(s) untouched >{SKILL_STALE_DAYS}d (oldest: {oldest_name})",
                    "description": (
                        f"{stale_count} skill(s) in .claude/skills/ have mtime older than "
                        f"{SKILL_STALE_DAYS} days; oldest is `{oldest_name}`. Audit each: "
                        f"(a) still relevant to current workflow, (b) reflects current rules / "
                        f"path triggers, (c) prune or refresh. Stale skills cause silent "
                        f"workflow drift — see CLAUDE.md `Rule path-trigger 時序原則`."
                    ),
                    "priority": 4,
                    "status": "pending",
                    "task_type": "governance",
                    "source": "diverse_gen",
                    "tags": ["governance", "skill-audit", "main-thread-only"],
                    "created_at": _now_iso(),
                })

    # Signal 2 — error_log accumulation
    if ERROR_LOG.exists() and len(out) < QUOTA_GOVERNANCE:
        try:
            heading_count = sum(
                1 for line in ERROR_LOG.read_text(encoding="utf-8").splitlines()
                if line.startswith("### ")
            )
        except Exception:
            heading_count = 0
        if heading_count >= ERROR_LOG_REVIEW_THRESHOLD:
            task_id = f"governance_error_log_review_{heading_count}"
            if task_id not in existing and not any(
                e.startswith("governance_error_log_review_") for e in existing
            ):
                out.append({
                    "id": task_id,
                    "title": f"Governance: error_log has {heading_count} entries — sweep for systemic patterns",
                    "description": (
                        f"docs/error_log.md accumulated {heading_count} entries (threshold "
                        f"{ERROR_LOG_REVIEW_THRESHOLD}). Read recent 20 entries; identify "
                        f"recurring root cause patterns; consolidate into rules / skills if a "
                        f"class of failure repeats. Per CLAUDE.md `永遠修流程，不修資料`."
                    ),
                    "priority": 4,
                    "status": "pending",
                    "task_type": "governance",
                    "source": "diverse_gen",
                    "tags": ["governance", "error-log-sweep", "main-thread-only"],
                    "created_at": _now_iso(),
                })

    return out


def gen_experiment_tasks(existing: set[str], rng: random.Random) -> list[dict]:
    """Surface unimplemented experiments from research_program.md backlog.

    Signal: research_program.md mentions K-IDs (e.g. ``K1234``) that have no
    corresponding ``experiments/k1234/`` directory. Cap at QUOTA_EXPERIMENT to
    avoid flooding the queue. These tasks are agent-dispatchable for designing
    the experiment scaffold (README + initial py stub).

    Idempotent: skips IDs already in ``existing`` task set.
    """
    out: list[dict] = []
    if not RESEARCH_PROGRAM.exists() or not EXPERIMENTS_DIR.exists():
        return out

    try:
        text = RESEARCH_PROGRAM.read_text(encoding="utf-8")
    except OSError:
        return out

    import re
    # Strip range / open-ended expressions to avoid bogus K-IDs:
    #   K400-K1258  → range bound, not specific experiment
    #   K500+       → "K500 onwards" generic reference
    cleaned = re.sub(r"\b[Kk]\d{2,4}[a-z]?\s*[-~–]\s*[Kk]\d{2,4}[a-z]?\b", "", text)
    cleaned = re.sub(r"[Kk]\d{2,4}[a-z]?\+", "", cleaned)
    # Match K\d+ tokens; case-insensitive (K1234 / k1234)
    mentioned = set(re.findall(r"\b[Kk](\d{3,4}[a-z]?)\b", cleaned))
    if not mentioned:
        return out

    # Existing experiments (folder presence)
    try:
        existing_dirs = {p.name.lower() for p in EXPERIMENTS_DIR.iterdir() if p.is_dir()}
    except OSError:
        return out

    # Completed-K filter: K-IDs already documented in knowledge.json or
    # docs/research_archive/completed_phases_*.md should NOT be surfaced as
    # backlog (K136 case 2026-05-08: already-completed BTC leverage-crowding
    # has knowledge entry but no experiments/k136/ dir — surfacing it as
    # backlog produced false positive).
    completed_ids: set[str] = set()
    kb_path = ROOT / "storage" / "memory" / "knowledge.json"
    if kb_path.exists():
        try:
            kb_text = kb_path.read_text(encoding="utf-8")
            for m in re.finditer(r"\b[Kk](\d{3,4}[a-z]?)\b", kb_text):
                completed_ids.add(f"k{m.group(1).lower()}")
        except OSError:
            pass
    archive_dir = ROOT / "docs" / "research_archive"
    if archive_dir.exists():
        for archive_md in archive_dir.glob("completed_phases_*.md"):
            try:
                arc_text = archive_md.read_text(encoding="utf-8")
                for m in re.finditer(r"\b[Kk](\d{3,4}[a-z]?)\b", arc_text):
                    completed_ids.add(f"k{m.group(1).lower()}")
            except OSError:
                continue

    # Find K-IDs in research_program with no experiment dir AND not yet completed
    backlog: list[str] = []
    for kid in mentioned:
        kid_lower = f"k{kid.lower()}"
        if any(_experiment_dir_covers_kid(dirname, kid_lower) for dirname in existing_dirs):
            continue
        if kid_lower in completed_ids:
            continue
        backlog.append(kid_lower)

    if not backlog:
        return out

    # Stable sort + sample QUOTA_EXPERIMENT items per run
    backlog_sorted = sorted(backlog)
    rng.shuffle(backlog_sorted)
    picks = backlog_sorted[: QUOTA_EXPERIMENT]

    for kid in picks:
        task_id = f"experiment_scaffold_{kid}"
        if task_id in existing or any(e == f"{kid.upper()}_article_general" or e == kid.upper() for e in existing):
            # avoid double-queue if K\d+ already has an article task or scaffold
            continue
        out.append({
            "id": task_id,
            "title": f"Experiment scaffold: {kid.upper()} (research_program backlog)",
            "description": (
                f"{kid.upper()} mentioned in research_program.md but no "
                f"experiments/{kid}/ directory yet. Create three-part scaffold per "
                f"CLAUDE.md `.claude/rules/experiments.md`: (a) README.md (motivation "
                f"+ method + expected output + lookahead policy), (b) "
                f"{kid}.py initial implementation (with signal.shift(1) + seed), "
                f"(c) plan placeholder {kid}_results.json schema. Do NOT run the "
                f"experiment — just scaffold + stage for main thread to review."
            ),
            "priority": 4,
            "status": "pending",
            "task_type": "experiment",
            "source": "diverse_gen",
            "tags": ["experiment", "scaffold", "research-program-backlog"],
            "created_at": _now_iso(),
        })

    return out


def generate(*, dry_run: bool = False, seed: int = 42) -> dict:
    """Programmatic entry — used by continue_task_dispatch._maybe_refill."""
    payload, tasks = _load_tasks()
    existing = _existing_ids(tasks)
    rng = random.Random(seed)

    paper_review = gen_paper_review_tasks(existing, rng)
    platform_ops = gen_platform_ops_tasks(existing)
    governance = gen_governance_tasks(existing)
    experiment = gen_experiment_tasks(existing, rng)
    new_entries = paper_review + platform_ops + governance + experiment

    summary = {
        "ok": True,
        "added": 0 if dry_run else len(new_entries),
        "would_add": len(new_entries) if dry_run else None,
        "by_type": {
            "paper_review": len(paper_review),
            "platform_ops": len(platform_ops),
            "governance": len(governance),
            "experiment": len(experiment),
        },
        "added_ids": [e["id"] for e in new_entries],
    }
    if not dry_run and new_entries:
        tasks.extend(new_entries)
        _save_tasks(payload, tasks)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    if not (args.dry_run or args.apply):
        print("error: must specify --dry-run or --apply", file=sys.stderr)
        return 2

    payload, tasks = _load_tasks()
    existing = _existing_ids(tasks)
    rng = random.Random(args.seed)

    paper_review = gen_paper_review_tasks(existing, rng)
    platform_ops = gen_platform_ops_tasks(existing)
    governance = gen_governance_tasks(existing)
    experiment = gen_experiment_tasks(existing, rng)

    new_entries = paper_review + platform_ops + governance + experiment
    summary = {
        "ok": True,
        "added": len(new_entries),
        "by_type": {
            "paper_review": len(paper_review),
            "platform_ops": len(platform_ops),
            "governance": len(governance),
            "experiment": len(experiment),
        },
        "added_ids": [e["id"] for e in new_entries],
    }

    if args.json:
        print(json.dumps(summary, ensure_ascii=False))
    else:
        print(f"[generate_diverse_tasks] would add {len(new_entries)} task(s):")
        for e in new_entries:
            print(f"  [{e['task_type']:14}] {e['id']}  ({e['title'][:60]})")

    if args.dry_run:
        return 0

    if new_entries:
        tasks.extend(new_entries)
        _save_tasks(payload, tasks)
    return 0


if __name__ == "__main__":
    sys.exit(main())
