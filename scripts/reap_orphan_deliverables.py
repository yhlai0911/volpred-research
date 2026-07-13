#!/usr/bin/env python3
"""產出即交付 — 把「寫完了但沒進系統」的成品自動收編，永不丟棄。

老闆 Telegram msg 624：完成的產出最後只能棄用 = 浪費 token。要求從底層邏輯修。

## 為什麼會有孤兒成品

一份 reader-facing 草稿要真正「交付」，需要兩件事：檔案寫進 `storage/drafts/`，
以及走 `publish_draft.py` 註冊進 feed（草稿池 → release cron 發出去）。producer 只做了
第一件事就結束的情況一直存在 —— 尤其是 fire lane 以外的 producer（codex-vscode session、
async render job）。對系統來說，只寫了檔案的成品**不存在**：feed 查不到、release 排不到、
dashboard 看不到。它唯一的痕跡是 `git status` 裡一行未追蹤檔案。

於是它被當成「垃圾」處理。PHASE-Z 看到不是自己這班產的檔案就不收（那道防線是對的 ——
盲目 `git add -A` 造成過三次事故），連續幾班沒人收就升級成 critical，而那封信的出口寫著
「人工判斷後二選一：commit 或丟棄」。一份寫完的深度文章，就這樣走到「丟棄」那一格。

## 這支程式怎麼修

它處理兩種有不同 canonical 出口的成品：

- 完整文章草稿走 `publish_draft.py`，由正式 gate 註冊進池。
- compute/lazypack job 的檔案走 receipt 的 `output_paths` ownership；只提交逐一宣告、實際存在、
  位於 main repo 內的普通檔案。job 執行失敗仍保留 `status=failed`，交付面另標
  `delivery_status=partial_delivered`，所以產物不丟、失敗也不會被粉飾。

三條硬規則：
1. **永不刪除、永不 checkout**。認不出來源的成品只會被「保留 + 回報」，不會被丟棄。
   這支程式裡沒有任何一行會刪檔，這是設計上的不變量，不是自律。
2. **偏向不收養**。判斷不確定時寧可漏收（檔案留著、下班再看）也不重複發佈 ——
   漏收的代價是延遲，重複發佈的代價是網站上出現兩篇一樣的文章。
3. **只管 cutover 之後的成品**。`storage/ops/orphan_draft_baseline.json` 凍結了改動前
   已存在的草稿（多數早已發佈，只是當年沒留下 provenance 欄位）。baseline 只准變少。
4. **Git ownership 只認 exact files**。不遞迴 result directory、不接受 repo 外路徑、目錄、
   symlink 或 ignored junk；commit 使用相同的 literal pathspec，永遠不掃整棵工作區。

## 交付憑證

`publish_draft.py` 現在會把 `details.source_draft` 寫進 feed entry —— 草稿檔與文章之間
第一次有了機器可查的連結。在這之前，「這份草稿發了沒」只能靠標題比對用猜的，
而猜不出來的那些，就是被判死的那些。

用法：
    uv run python scripts/reap_orphan_deliverables.py              # 掃描 + 回報（預設）
    uv run python scripts/reap_orphan_deliverables.py --apply      # 收編（跑正規入池）
    uv run python scripts/reap_orphan_deliverables.py --init-baseline   # 一次性 cutover
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from volpred.ops.diagnostics import warn  # noqa: E402

DRAFTS_DIR = ROOT / "storage" / "drafts"
FEED_PATH = ROOT / "storage" / "reports" / "feed.json"
TASKS_PATH = ROOT / "storage" / "next_tasks.json"
BASELINE_PATH = ROOT / "storage" / "ops" / "orphan_draft_baseline.json"
REPORT_PATH = ROOT / "storage" / "ops" / "orphan_reap_report.json"
QUEUE_DIR = ROOT / "storage" / "ops" / "compute_queue"

# A draft younger than this is presumed to still have an author typing into it.
# Adopting mid-write would publish half an article — the one failure mode worse
# than leaving it alone for an hour.
GRACE_SECONDS = 2 * 3600

# Outward-facing writes are rate-limited on purpose. If ten orphans show up at
# once, something upstream is broken and dumping ten articles onto the site is
# not the fix — the report will say so and the next run takes the next two.
DEFAULT_MAX_ADOPT = 2
DEFAULT_MAX_JOB_COMMITS = 4

# Below this, a "draft" is a stub or a scratch note, not a deliverable. Held for
# the author, never discarded.
MIN_BODY_CHARS = 800


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        # Fail-open is right here (a missing feed must not stop the sweep) but it
        # must not be silent: an unreadable feed makes every draft look unregistered,
        # which is the one input that could push this thing toward over-adopting.
        warn("reap_orphan", "load failed — treating as empty",
             path=str(path), err=str(exc))
        return default


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Return (frontmatter, body). Tolerates a missing/malformed block.

    Deliberately not a YAML dependency: we only need scalar keys, and a draft
    with exotic YAML is exactly the kind we want to hand back to its author
    rather than guess at.
    """
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    raw = text[3:end]
    body = text[end + 4:].lstrip("\n")
    fm: dict[str, str] = {}
    for line in raw.splitlines():
        if ":" not in line or line.lstrip().startswith("#"):
            continue
        key, _, val = line.partition(":")
        fm[key.strip()] = val.strip().strip('"').strip("'")
    return fm, body


def _norm_title(title: str) -> str:
    """Collapse whitespace/punctuation so a title match survives light editing."""
    return re.sub(r"[\s　·・\-—–|｜:：,，.。!！?？]+", "", title or "").lower()


def _k_ids(fm: dict, body: str) -> set[str]:
    found = set()
    for src in (fm.get("kid", ""), fm.get("k_id", ""), fm.get("experiment_refs", "")):
        found.update(re.findall(r"[Kk]\d{3,4}", src or ""))
    return {k.upper() for k in found}


def load_baseline() -> set[str]:
    data = _load_json(BASELINE_PATH, {})
    return set(data.get("drafts", []))


# ── queue-owned deliverables ─────────────────────────────────────────────────

_TERMINAL_JOB_STATES = {"completed", "failed"}
_GIT_ENV_KEYS = {
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
}


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    """Run git against ROOT without inheriting a caller's repository override."""
    env = os.environ.copy()
    for key in _GIT_ENV_KEYS:
        env.pop(key, None)
    # `check-ignore` rejects Git's global `--literal-pathspecs` option.  Its
    # caller accepts only pathspec-safe filenames; every mutating command keeps
    # the literal flag mechanically enforced.
    command = ["git", *args] if args and args[0] == "check-ignore" else [
        "git", "--literal-pathspecs", *args,
    ]
    return subprocess.run(
        command,
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
    )


@contextmanager
def _receipt_lock():
    """Share the compute queue's receipt lock while merging delivery metadata."""
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    with (QUEUE_DIR / ".receipts.lock").open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _write_job_receipt(path: Path, payload: dict) -> None:
    """Replace one terminal receipt without exposing partially written JSON."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def _exact_repo_file(raw: object) -> tuple[str | None, str | None]:
    """Validate one ownership declaration as an exact regular file in ROOT."""
    if not isinstance(raw, str) or not raw.strip():
        return None, "not_a_nonempty_string"
    candidate = Path(raw)
    candidate = candidate if candidate.is_absolute() else ROOT / candidate
    if candidate.is_symlink():
        return None, "symlink_not_owned"
    resolved = candidate.resolve(strict=False)
    try:
        rel = resolved.relative_to(ROOT.resolve(strict=False))
    except ValueError:
        return None, "outside_repo"
    if not resolved.is_file():
        return None, "missing_or_not_regular_file"
    if rel.parts and rel.parts[0] == ".git":
        return None, "git_internal_path"
    if rel.as_posix().startswith(":") or any(ch in rel.as_posix() for ch in "*?["):
        return None, "pathspec_unsafe_name"
    ignored = _git("check-ignore", "-q", "--", rel.as_posix())
    if ignored.returncode == 0:
        return None, "git_ignored"
    if ignored.returncode not in {0, 1}:
        return None, "git_ignore_check_failed"
    return rel.as_posix(), None


def _path_is_dirty(rel: str) -> bool:
    status = _git("status", "--porcelain=v1", "--untracked-files=all", "--", rel)
    # Fail closed toward preserving the file: if git cannot classify it, make
    # the delivery attempt surface the concrete error instead of skipping it.
    return status.returncode != 0 or bool(status.stdout.strip())


def scan_job_deliverables() -> dict:
    """Find terminal compute jobs whose exact declared files need delivery."""
    candidates: list[dict] = []
    held: list[dict] = []
    if not QUEUE_DIR.is_dir():
        return {"candidates": candidates, "held": held}

    for job_path in sorted(QUEUE_DIR.glob("*.json")):
        try:
            job = json.loads(job_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            warn("reap_job_deliverable", "queue receipt unreadable — held",
                 path=str(job_path), err=str(exc))
            held.append({"job_id": job_path.stem, "reason": "unreadable_job",
                         "detail": str(exc)})
            continue
        if not isinstance(job, dict):
            held.append({"job_id": job_path.stem, "reason": "invalid_job_schema"})
            continue
        if job.get("status") not in _TERMINAL_JOB_STATES:
            continue
        # Agent outputs belong to their worktree merge/review workflow.  This
        # reaper owns only main-checkout compute/lazypack deliverables.
        if job.get("kind") == "agent":
            continue
        declared = job.get("output_paths")
        if not isinstance(declared, list) or not declared:
            continue

        exact: list[str] = []
        rejected: list[dict] = []
        for raw in declared:
            rel, reason = _exact_repo_file(raw)
            if rel is not None:
                exact.append(rel)
            else:
                rejected.append({"path": raw, "reason": reason})
        exact = list(dict.fromkeys(exact))
        if not exact:
            # Do not finalize the job: a timed-out producer may still land a
            # declared file before the next sweep, and preserving it is the goal.
            held.append({"job_id": str(job.get("id") or job_path.stem),
                         "reason": "no_existing_declared_files",
                         "rejected": rejected})
            continue
        previously_delivered = job.get("delivered_paths") or []
        if not isinstance(previously_delivered, list):
            previously_delivered = []
        previous = {str(path) for path in previously_delivered}
        pending = [path for path in exact if path not in previous or _path_is_dirty(path)]
        if not pending:
            if rejected:
                held.append({
                    "job_id": str(job.get("id") or job_path.stem),
                    "reason": "declared_outputs_not_yet_deliverable",
                    "rejected": rejected,
                })
            continue
        candidates.append({
            "job_id": str(job.get("id") or job_path.stem),
            "job_path": str(job_path),
            "execution_status": job.get("status"),
            "paths": pending,
            "existing_paths": exact,
            "previously_delivered_paths": sorted(previous),
            "rejected": rejected,
        })
    return {"candidates": candidates, "held": held}


def deliver_job_outputs(candidate: dict) -> dict:
    """Commit only one job's exact declared files, then stamp its receipt."""
    job_id = str(candidate["job_id"])
    job_path = Path(candidate["job_path"])
    requested_paths = list(candidate["paths"])
    outcome = {"job_id": job_id, "paths": requested_paths, "delivered": False}

    with _receipt_lock():
        latest = json.loads(job_path.read_text(encoding="utf-8"))
        previous = latest.get("delivered_paths") or []
        if not isinstance(previous, list):
            previous = []
        previous_set = {str(path) for path in previous}
        # A second reaper may have completed this candidate while we waited for
        # the lock.  Re-evaluate ownership instead of replaying a stale scan.
        paths = [
            path for path in requested_paths
            if path not in previous_set or _path_is_dirty(path)
        ]
        if not paths:
            outcome["reason"] = "no_pending_paths"
            return outcome

        pre_staged = _git("diff", "--cached", "--name-only", "--", *paths)
        if pre_staged.returncode != 0:
            outcome.update(reason="git_preflight_failed",
                           stderr=(pre_staged.stderr or "")[-500:])
            return outcome
        collisions = [line for line in pre_staged.stdout.splitlines() if line]
        if collisions:
            outcome.update(reason="pre_staged_collision", collisions=collisions)
            return outcome

        index_owned = True  # preflight proved these scoped index entries were empty
        try:
            add = _git("add", "--", *paths)
            if add.returncode != 0:
                outcome.update(reason="git_add_failed", stderr=(add.stderr or "")[-500:])
                return outcome
            staged = _git("diff", "--cached", "--name-only", "--", *paths)
            if staged.returncode != 0:
                outcome.update(reason="git_diff_failed", stderr=(staged.stderr or "")[-500:])
                return outcome
            staged_paths = [line for line in staged.stdout.splitlines() if line]

            if staged_paths:
                safe_job_id = re.sub(r"[\x00-\x1f\x7f]+", "_", job_id)[:120]
                commit = _git(
                    "commit", "--only", "-m",
                    f"chore(deliverables): commit {safe_job_id} outputs",
                    "--", *paths,
                )
                if commit.returncode != 0:
                    outcome.update(reason="git_commit_failed",
                                   stderr=(commit.stderr or commit.stdout or "")[-500:])
                    return outcome
                index_owned = False
                evidence = _git("log", "-1", "--format=%H", "--", *staged_paths)
            else:
                # Clean paths are deliverable only if Git already tracks them;
                # HEAD alone is not evidence that this job's file is in history.
                for path in paths:
                    tracked = _git("ls-files", "--error-unmatch", "--", path)
                    if tracked.returncode != 0:
                        outcome.update(reason="clean_path_not_tracked", path=path)
                        return outcome
                evidence = _git("log", "-1", "--format=%H", "--", *paths)

            if evidence.returncode != 0 or not evidence.stdout.strip():
                outcome.update(reason="delivery_commit_not_found",
                               stderr=(evidence.stderr or "")[-500:])
                return outcome
            commit_hash = evidence.stdout.strip().splitlines()[0]

            delivered_union = previous_set | set(paths)
            existing = set(candidate.get("existing_paths") or paths)
            rejected = candidate.get("rejected") or []
            execution_status = latest.get("status")
            complete = (
                execution_status == "completed"
                and not rejected
                and existing.issubset(delivered_union)
            )
            delivery_status = "delivered" if complete else "partial_delivered"
            latest.update({
                "delivery_status": delivery_status,
                "partial_delivered": not complete,
                "delivery_commit": commit_hash,
                "delivered_paths": sorted(delivered_union),
                "delivered_at": _now().isoformat(),
                "delivery_source": "reap_orphan_deliverables",
            })
            _write_job_receipt(job_path, latest)
            outcome.update(
                delivered=True,
                delivery_status=delivery_status,
                delivery_commit=commit_hash,
                reason="committed" if staged_paths else "already_committed",
            )
            return outcome
        finally:
            if index_owned and not outcome["delivered"]:
                # Preflight proved no one else owned these scoped index entries,
                # so cleanup cannot erase a foreign staged change. Working files
                # remain intact for the next sweep.
                _git("reset", "-q", "HEAD", "--", *paths)


def is_registered(rel: str, fm: dict, body: str, feed: list[dict]) -> tuple[bool, str]:
    """Has this draft already been delivered as an article?

    Three probes, strongest first. Any hit means "leave it alone" — the bias is
    deliberate and asymmetric: a missed orphan costs a delay, a double-publish
    costs the reader two copies of the same article on the site.
    """
    for art in feed:
        details = art.get("details") or {}
        if isinstance(details, dict) and details.get("source_draft") == rel:
            return True, f"source_draft → {art.get('id')}"

    # Pre-provenance window: articles published before `source_draft` existed
    # carry no back-link. Title is the only honest fallback.
    title = _norm_title(fm.get("title", ""))
    if title:
        for art in feed:
            if _norm_title(art.get("title", "")) == title:
                return True, f"title match → {art.get('id')}"

    # A K already covered for this audience means the finding has shipped; a
    # second draft of it is a duplicate, not an orphan (the arc-dedup gate would
    # have blocked it at write time anyway).
    kids = _k_ids(fm, body)
    audience = (fm.get("audience") or "").strip()
    if kids and audience:
        for art in feed:
            if (art.get("audience") or "") != audience:
                continue
            refs = ((art.get("details") or {}).get("experiment_refs")) or []
            if isinstance(refs, list) and kids & {str(r).upper() for r in refs}:
                return True, f"K-coverage → {art.get('id')}"
    return False, ""


def _inflight_stems(tasks: list[dict]) -> set[str]:
    """Draft stems a live task is still working on — not orphans, just in flight."""
    live = {"claimed", "in_progress"}
    blob = " ".join(
        json.dumps(t, ensure_ascii=False)
        for t in tasks
        if isinstance(t, dict) and t.get("status") in live
    )
    return set(re.findall(r"[\w\-]+(?=_draft\.md)", blob)) | set(
        re.findall(r"storage/drafts/([\w\-.]+)\.md", blob)
    )


def scan(*, now_ts: float | None = None) -> dict:
    """Classify every post-cutover draft. Pure read — writes nothing, deletes nothing."""
    now_ts = now_ts if now_ts is not None else time.time()
    feed = _load_json(FEED_PATH, [])
    feed = feed if isinstance(feed, list) else []
    tasks = _load_json(TASKS_PATH, [])
    tasks = tasks if isinstance(tasks, list) else tasks.get("tasks", []) if isinstance(tasks, dict) else []
    baseline = load_baseline()
    inflight = _inflight_stems(tasks)

    adoptable: list[dict] = []
    held: list[dict] = []
    skipped = {"baseline": 0, "registered": 0, "grace": 0, "inflight": 0}

    for path in sorted(DRAFTS_DIR.glob("*.md")) if DRAFTS_DIR.is_dir() else []:
        rel = str(path.relative_to(ROOT))
        if rel in baseline:
            skipped["baseline"] += 1
            continue
        try:
            stat = path.stat()
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            warn("reap_orphan", "draft unreadable — held, not discarded",
                 path=rel, err=str(exc))
            held.append({"path": rel, "reason": "unreadable", "detail": str(exc)})
            continue

        age_s = now_ts - stat.st_mtime
        if age_s < GRACE_SECONDS:
            skipped["grace"] += 1
            continue
        if path.stem in inflight or path.stem.replace("_draft", "") in inflight:
            skipped["inflight"] += 1
            continue

        fm, body = parse_frontmatter(text)
        registered, why = is_registered(rel, fm, body, feed)
        if registered:
            skipped["registered"] += 1
            continue

        # From here on it is an orphan: on disk, finished-looking, unknown to the
        # product. The only question left is whether we can route it ourselves.
        if not fm.get("title"):
            held.append({"path": rel, "reason": "no_title",
                         "detail": "缺 frontmatter title — 入池需要標題，保留等作者確認"})
            continue
        if len(body.strip()) < MIN_BODY_CHARS:
            held.append({"path": rel, "reason": "too_short",
                         "detail": f"正文 {len(body.strip())} 字 < {MIN_BODY_CHARS} — 像半成品，保留"})
            continue
        adoptable.append({
            "path": rel,
            "title": fm.get("title", ""),
            "audience": fm.get("audience", ""),
            "status": fm.get("status") or "draft",
            "body_chars": len(body.strip()),
            "age_hours": round(age_s / 3600, 1),
        })

    return {
        "generated_at": _now().isoformat(),
        "adoptable": adoptable,
        "held": held,
        "skipped": skipped,
        "orphan_count": len(adoptable) + len(held),
    }


def adopt(entry: dict, *, timeout_s: int = 900) -> dict:
    """Route one orphan through the canonical intake. Never touches the file itself.

    `publish_draft.py` owns every gate (anti-AI, arc-dedup, image, lazypack) and
    every write to feed.json. Calling it — rather than re-implementing intake here
    — is what keeps this a delivery fix instead of a second, competing publisher.
    """
    cmd = [
        "uv", "run", "python", "scripts/publish_draft.py", entry["path"],
        "--status", entry.get("status") or "draft",
    ]
    try:
        proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout_s)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return {"path": entry["path"], "adopted": False, "reason": f"intake_error: {exc}"}
    if proc.returncode == 0:
        return {"path": entry["path"], "adopted": True, "reason": "published_into_pool"}
    tail = (proc.stderr or proc.stdout or "").strip().splitlines()
    return {
        "path": entry["path"],
        "adopted": False,
        # A gate rejection is a real answer, not a failure to be papered over: the
        # draft stays on disk, the report says which gate said no, and a human or
        # a later fire fixes the draft. Nothing is discarded either way.
        "reason": f"gate_rejected (rc={proc.returncode}): {tail[-1][:200] if tail else 'no output'}",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true",
                    help="實際收編（跑 publish_draft 入池）。預設只掃描回報。")
    ap.add_argument("--max", type=int, default=DEFAULT_MAX_ADOPT,
                    help=f"單次最多收編幾份（預設 {DEFAULT_MAX_ADOPT}）")
    ap.add_argument("--max-jobs", type=int, default=DEFAULT_MAX_JOB_COMMITS,
                    help=f"單次最多提交幾個 queue job 的產物（預設 {DEFAULT_MAX_JOB_COMMITS}）")
    ap.add_argument("--init-baseline", action="store_true",
                    help="一次性 cutover：把現存草稿全數凍結為 baseline（豁免）")
    ap.add_argument("--json", action="store_true", help="只輸出 JSON")
    args = ap.parse_args()

    if args.init_baseline:
        drafts = sorted(str(p.relative_to(ROOT)) for p in DRAFTS_DIR.glob("*.md"))
        BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
        BASELINE_PATH.write_text(json.dumps({
            "note": "改動前既存草稿（多數早已發佈，只是當年沒有 source_draft provenance）。"
                    "只准變少：確認某份已交付或已收編就從這裡移除。",
            "cutover_at": _now().isoformat(),
            "drafts": drafts,
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"[reap] baseline 凍結 {len(drafts)} 份既存草稿 → {BASELINE_PATH.relative_to(ROOT)}")
        return 0

    result = scan()
    job_scan = scan_job_deliverables()
    job_deliveries: list[dict] = []
    adopted: list[dict] = []
    if args.apply:
        for candidate in job_scan["candidates"][: args.max_jobs]:
            job_deliveries.append(deliver_job_outputs(candidate))
        for entry in result["adoptable"][: args.max]:
            outcome = adopt(entry)
            adopted.append(outcome)
            print(f"[reap] {'收編' if outcome['adopted'] else '未收編'}: "
                  f"{entry['path']} — {outcome['reason']}")
        if len(result["adoptable"]) > args.max:
            print(f"[reap] 本次上限 {args.max}，還有 "
                  f"{len(result['adoptable']) - args.max} 份待下次收編（沒有丟棄）")
    result["adopted"] = adopted
    result["applied"] = args.apply
    result["job_deliverable_candidates"] = job_scan["candidates"]
    result["job_deliverable_held"] = job_scan["held"]
    result["job_deliveries"] = job_deliveries

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")

    if args.json:
        print(json.dumps(result, ensure_ascii=False))
        return 0

    print(f"[reap] 孤兒成品 {result['orphan_count']} 份："
          f"可收編 {len(result['adoptable'])}、保留待確認 {len(result['held'])}")
    delivered_jobs = [item for item in job_deliveries if item.get("delivered")]
    print(f"[reap] queue 產物：候選 {len(job_scan['candidates'])}、"
          f"已交付 {len(delivered_jobs)}、保留 {len(job_scan['held'])}")
    print(f"[reap] 略過：{result['skipped']}")
    for h in result["held"][:10]:
        print(f"  - 保留 {h['path']} — {h['detail']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
