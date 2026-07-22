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

## 受管目錄是資料，不是程式（2026-07-19，老闆 msg 963）

這支程式曾經是「每種產物一個 recognizer 函式」。那個形狀本身就是 bug：新增一種產物
目錄就要有人記得再寫一支函式，沒寫 = 該目錄的檔案沒有任何出口 → 永久 held → alert
永遠解不掉。同一個坑踩了三次（paper/、storage/drafts/、experiments/）。

現在受管目錄宣告在 `config/orphan_namespaces.json`，掃描與收編是一個吃 registry 的
泛型引擎（`scan_namespace` / `collect_namespace`）。**新增一個受管目錄 = 加一筆 config。**
預設是 `adopt`：namespace 裡的檔案就是那個 namespace 的產物（目錄的定義），只擋真正的
垃圾。並且 held 帶 `first_seen`，連續數班無主會升級成一張指名路徑的任務 —— 因為「作者
自己回來 commit」從來不是可靠的出口，作者 session 結束後不回來是常態。

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
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from volpred.canonical_write import guard_canonical_write  # noqa: E402
from volpred.ops.diagnostics import warn  # noqa: E402
from volpred.ops.git_writer_lock import (  # noqa: E402
    GitWriterLockError,
    git_writer_lock,
    git_writer_subprocess_kwargs,
    require_canonical_main_checkout,
)

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
_INFLIGHT_JOB_STATES = {"queued", "running"}
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
    locked_kwargs = git_writer_subprocess_kwargs(env)
    return subprocess.run(
        command,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        **locked_kwargs,
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


@contextmanager
def _git_transaction(actor: str):
    """Yield False on ordinary contention; never fall back to unlocked Git."""
    manager = git_writer_lock(ROOT, actor=actor, timeout_s=30)
    entered = False
    try:
        manager.__enter__()
        entered = True
        require_canonical_main_checkout(ROOT)
    except GitWriterLockError as exc:
        if entered:
            manager.__exit__(None, None, None)
        warn("reap_orphan", "git writer transaction busy — deferred",
             actor=actor, err=str(exc))
        yield False
        return
    try:
        yield True
    except BaseException:
        manager.__exit__(*sys.exc_info())
        raise
    else:
        manager.__exit__(None, None, None)


def _write_job_receipt(path: Path, payload: dict) -> None:
    """Replace one terminal receipt without exposing partially written JSON."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


# Rejection reasons that mean "the producer never wrote this file", as opposed
# to "the file is there but this reaper is not allowed to deliver it".
_NOTHING_WAS_PRODUCED = frozenset({
    "missing_or_not_regular_file",
    "not_a_nonempty_string",
})


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


_WORKTREE_PREFIX_RE = re.compile(r"^\.claude/worktrees/[^/]+/")


def _tracked_clean_in_worktree(raw: object) -> bool:
    """Return whether a declared output already has a worktree merge exit.

    The canonical checkout intentionally ignores ``.claude/worktrees``.  A
    compute job can nevertheless run there and commit its output on the
    worktree branch.  Treating that file as merely ``git_ignored`` manufactures
    an orphan alert and, worse, invites the main-checkout reaper to bypass the
    review/merge gate.  Only a regular file that Git tracks *and* reports clean
    in that exact worktree qualifies; untracked or modified outputs stay held.
    """
    if not isinstance(raw, str) or not raw.strip():
        return False
    candidate = Path(raw.strip())
    candidate = candidate if candidate.is_absolute() else ROOT / candidate
    if candidate.is_symlink() or not candidate.is_file():
        return False
    resolved = candidate.resolve(strict=False)
    worktrees_root = (ROOT / ".claude" / "worktrees").resolve(strict=False)
    try:
        within = resolved.relative_to(worktrees_root)
    except ValueError:  # silent-ok: declaration is outside managed worktrees
        return False
    if len(within.parts) < 2:
        return False
    worktree = worktrees_root / within.parts[0]
    rel = PurePosixPath(*within.parts[1:]).as_posix()

    env = os.environ.copy()
    for key in _GIT_ENV_KEYS:
        env.pop(key, None)
    kwargs = {
        "cwd": str(worktree),
        "env": env,
        "capture_output": True,
        "text": True,
    }
    tracked = subprocess.run(
        ["git", "--literal-pathspecs", "ls-files", "--error-unmatch", "--", rel],
        **kwargs,
    )
    if tracked.returncode != 0:
        return False
    status = subprocess.run(
        ["git", "--literal-pathspecs", "status", "--porcelain=v1",
         "--untracked-files=all", "--", rel],
        **kwargs,
    )
    return status.returncode == 0 and not status.stdout.strip()


def _managed_worktree_output_root(raw: object) -> Path | None:
    """Return the registered-worktree-shaped root for an existing output."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    candidate = Path(raw.strip())
    candidate = candidate if candidate.is_absolute() else ROOT / candidate
    if candidate.is_symlink() or not candidate.is_file():
        return None
    resolved = candidate.resolve(strict=False)
    worktrees_root = (ROOT / ".claude" / "worktrees").resolve(strict=False)
    try:
        within = resolved.relative_to(worktrees_root)
    except ValueError:  # silent-ok: declaration is outside managed worktrees
        return None
    if len(within.parts) < 2:
        return None
    worktree = worktrees_root / within.parts[0]
    # A linked worktree has a `.git` file pointing at the common repository.
    # Requiring it keeps an arbitrary ignored directory from impersonating a
    # review/merge owner.
    if not (worktree / ".git").is_file():
        return None
    return worktree


def _active_followup_owns_worktree(job: dict, declared: list[object]) -> bool:
    """Whether a live agent follow-up owns every declared worktree output.

    Compute results are intentionally left modified/untracked until their
    review stage commits the worktree.  The main-checkout reaper must not call
    those files ownerless while that exact downstream job remains queued or
    running; conversely, a missing/terminal/unrelated follow-up must not silence
    the hold.
    """
    if job.get("followup_dispatched") is not True:
        return False
    followup_id = job.get("followup_next_task_id")
    if not isinstance(followup_id, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._-]*", followup_id):
        return False

    roots = [_managed_worktree_output_root(raw) for raw in declared]
    if not roots or any(root is None for root in roots):
        return False
    worktree = roots[0]
    if any(root != worktree for root in roots[1:]):
        return False

    followup_path = QUEUE_DIR / f"{followup_id}.json"
    # Some follow-up ids name task-pool rows rather than compute receipts.
    # Absence here is therefore a normal non-match, not an unreadable-input
    # warning for every reaper sweep.
    if not followup_path.is_file():
        return False
    followup = _load_json(followup_path, {})
    if not isinstance(followup, dict):
        return False
    if (
        followup.get("kind") != "agent"
        or followup.get("status") not in _INFLIGHT_JOB_STATES
    ):
        return False
    cwd = followup.get("cwd")
    if not isinstance(cwd, str) or not cwd.strip():
        return False
    return Path(cwd).resolve(strict=False) == worktree.resolve(strict=False)


def _landed_in_main(raw: object) -> str | None:
    """Worktree-declared output that has since been merged into the checkout.

    A job that ran in a worktree declares `.claude/worktrees/<wt>/experiments/…`.
    Once the worktree merges, `merge_worktree.sh` removes it, so the declared
    path stops existing while the deliverable itself is safe in the main tree —
    the exact shape that produced seven bogus `no_existing_declared_files` holds
    on 2026-07-19. Resolve the same repo-relative path in the checkout instead.
    """
    if not isinstance(raw, str) or not raw.strip():
        return None
    original = raw.strip().removeprefix("./")
    stripped = _WORKTREE_PREFIX_RE.sub("", original)
    if stripped == original:
        return None  # never was a worktree path — nothing to re-resolve
    rel, _reason = _exact_repo_file(stripped)
    return rel


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
        if _active_followup_owns_worktree(job, declared):
            # The exact worktree and files have a live review/merge owner.  Its
            # queue receipt owns escalation if that job stalls; opening an
            # orphan-delivery task here duplicates ownership and pressures the
            # main reaper to bypass the experiment gate.
            continue

        exact: list[str] = []
        rejected: list[dict] = []
        worktree_owned = 0
        for raw in declared:
            rel, reason = _exact_repo_file(raw)
            if rel is not None:
                exact.append(rel)
            elif _tracked_clean_in_worktree(raw):
                worktree_owned += 1
            else:
                rejected.append({"path": raw, "reason": reason})
        exact = list(dict.fromkeys(exact))
        if not exact:
            if worktree_owned == len(declared):
                # Already committed on the job's worktree branch. Its only
                # legitimate exit is the normal review + merge workflow.
                continue
            landed = [rel for rel in (_landed_in_main(raw) for raw in declared)
                      if rel is not None]
            if landed:
                # Already in the checkout under its post-merge path. Nothing is
                # at risk, so holding it only manufactures a triage task.
                continue
            if job.get("status") == "failed" and all(
                    r.get("reason") in _NOTHING_WAS_PRODUCED for r in rejected):
                # A failed job produced no deliverable to preserve. Holding it
                # asks a human to find an exit for something that never existed.
                # The skip stops there on purpose: if a declared path *does*
                # exist and was refused on policy grounds (outside the repo, a
                # symlink, git-ignored), the artifact is real and this file's
                # invariant applies — held + a readable reason, never silently
                # dropped because the producer happened to exit non-zero.
                continue
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
            # A declared output that `.gitignore` excludes (`__pycache__`,
            # scratch `*_article.md`) is not a deliverable this reaper can ever
            # deliver — every real output already landed. Holding on those alone
            # is bookkeeping noise, not a preserved artifact.
            if rejected and any(r.get("reason") != "git_ignored" for r in rejected):
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

    # Receipt ownership and Git adoption are one transaction.  Holding the
    # receipt lock first preserves the existing reaper ordering; the Git lease
    # then prevents any other writer from interleaving preflight/add/commit.
    with _receipt_lock(), _git_transaction(f"orphan-reaper:job:{job_id}") as locked:
        if not locked:
            outcome["reason"] = "git_writer_lock_busy"
            return outcome
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

    # Derivatives of an already-published article name it in the filename:
    # `fb_mile_5a20a332.md` (FB copy), `k841_mile_179df5f5_correction.md`
    # (errata). They carry no frontmatter title — they were never meant to enter
    # the draft pool — so every probe above misses and they land in `no_title`
    # held forever. The article id in the name is an exact back-link; use it.
    named = _mile_ids(rel)
    if named:
        for art in feed:
            if str(art.get("id") or "") in named:
                return True, f"derivative of published {art.get('id')}"
    return False, ""


# No leading \b: the id is usually prefixed (`fb_mile_…`), and `_` is a word
# character, so \b would never fire on exactly the names this probe exists for.
_MILE_ID_RE = re.compile(r"mile_[0-9a-f]{6,}(?![0-9a-f])")


def _mile_ids(rel: str) -> set[str]:
    """Feed article ids named by a draft's filename (not its body)."""
    return set(_MILE_ID_RE.findall(PurePosixPath(rel).name))


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


# ---------------------------------------------------------------------------
# Namespace registry（2026-07-19，老闆 msg 963 — 底層邏輯重新設計）
#
# 這裡原本是三份平行的 recognizer：scan_paper_build_artifacts、scan_draft_artifacts，
# 各自帶一份 collect_*。形狀本身就是 bug：每新增一種產物目錄，就要有人記得再寫一個
# recognizer 函式；沒寫 = 那個目錄的檔案**沒有任何出口**（PHASE-Z by design 只 commit
# 自己那班產的檔），於是永久 held、alert 永遠解不掉。
#
# 這個坑踩了三次 —— paper/(07-14)、storage/drafts/(07-15，07-17 才把預設從白名單反轉
# 成收編)、experiments/(07-19)。07-17 那次反轉只做在 drafts recognizer 內部，沒有升級成
# 全域規則，所以下一個目錄照樣中招。問題不是少一個 recognizer，是這個架構要求人記得補
# recognizer。
#
# 所以：受管目錄變成 config（config/orphan_namespaces.json）裡的一筆資料，掃描與收編
# 變成一個吃 registry 的泛型引擎。新增一個受管目錄 = 加一筆 config，不寫任何程式。
# 預設值是 adopt：一個 namespace 裡的檔案**就是**那個 namespace 的產物（目錄的定義，
# 不是猜測），只擋真正的垃圾（編輯器殘留、快取目錄、dotfile、symlink、巨檔）。
#
# 檔案頂部的不變量一條都沒有放寬：被擋的一律 held + 可讀 reason，永不刪除、永不
# checkout；git ownership 只認 exact 普通檔；收編一律走 _git_transaction lease。
# ---------------------------------------------------------------------------

REGISTRY_PATH = ROOT / "config" / "orphan_namespaces.json"
HELD_STATE_PATH = ROOT / "storage" / "ops" / "orphan_held_state.json"

# 內建 fallback：config 讀不到時仍有一份安全的預設，而不是「沒有 namespace = 什麼都
# 不收」（那正是本次要修掉的失效模式）。
_BUILTIN_DEFAULTS = {
    "default": "adopt",
    "status_filter": "all",
    "respect_inflight": True,
    "content_gates": [],
    "max_file_bytes": 25 * 1024 * 1024,
    "max_files": 40,
    "exclusions": {
        "dotfiles": True,
        "editor_backups": True,
        "symlinks": True,
        "suffixes": [".tmp", ".temp", ".part", ".partial", ".swp", ".swo",
                     ".bak", ".lock", ".pyc", ".pyo"],
        "dirs": ["__pycache__", ".ipynb_checkpoints"],
    },
}

# held 不得是永久狀態。連續這麼多班仍無主 → 升級成一張指名該路徑清單的任務，並停止
# 重複噴同一句 alert。作者 session 結束後永不回來是常態，出口必須由系統提供。
DEFAULT_HELD_ESCALATION_SHIFTS = 6

_REGISTRY_CACHE: dict[str, dict] = {}


def load_registry(*, refresh: bool = False) -> dict:
    """Read the namespace registry, merging each entry over the declared defaults."""
    key = str(REGISTRY_PATH)
    if not refresh and key in _REGISTRY_CACHE:
        return _REGISTRY_CACHE[key]
    raw = _load_json(REGISTRY_PATH, {})
    if not isinstance(raw, dict):
        warn("reap_orphan", "namespace registry malformed — using builtin defaults",
             path=key)
        raw = {}
    defaults = {**_BUILTIN_DEFAULTS, **(raw.get("defaults") or {})}
    namespaces: dict[str, dict] = {}
    for entry in raw.get("namespaces") or []:
        if not isinstance(entry, dict) or not entry.get("path"):
            warn("reap_orphan", "namespace entry skipped — needs a path",
                 entry=json.dumps(entry, ensure_ascii=False)[:120])
            continue
        merged = {**defaults, **entry}
        merged["id"] = str(entry.get("id") or entry["path"]).strip()
        merged["path"] = str(entry["path"]).strip().strip("/")
        merged["exclusions"] = {**(defaults.get("exclusions") or {}),
                                **(entry.get("exclusions") or {})}
        namespaces[merged["id"]] = merged
    registry = {
        "namespaces": namespaces,
        "held_escalation_shifts": int(
            raw.get("held_escalation_shifts") or DEFAULT_HELD_ESCALATION_SHIFTS),
    }
    _REGISTRY_CACHE[key] = registry
    return registry


def get_namespace(ns_id: str) -> dict:
    ns = load_registry()["namespaces"].get(ns_id)
    if ns is None:
        raise KeyError(f"unknown orphan namespace: {ns_id!r}")
    return ns


# ── content gates ────────────────────────────────────────────────────────────
# Gates 是**可重用的規則**，不是每個目錄一支函式：一筆 config 用名字引用它們，多數
# namespace 一個都不用（default: adopt 就是出口）。paper/ 需要它們是因為那裡的 dirty
# 檔可能是真的內容變動 —— 那必須由作者驗證後自己 commit，reaper 只認「重建副產物」。

_VOLATILE_RESULT_KEYS = {"timestamp", "runtime_seconds", "generated_at",
                         "audit_date", "run_at", "elapsed_seconds"}
_BUILD_SOURCE_SUFFIXES = {".tex", ".bib", ".sty", ".cls", ".png", ".pdf_tex", ".eps"}


def _strip_volatile(obj):
    if isinstance(obj, dict):
        return {k: _strip_volatile(v) for k, v in obj.items()
                if k not in _VOLATILE_RESULT_KEYS}
    if isinstance(obj, list):
        return [_strip_volatile(v) for v in obj]
    return obj


def _results_volatile_only(rel: str) -> tuple[bool, str]:
    """True iff the dirty results.json differs from HEAD only in volatile keys."""
    head = _git("show", f"HEAD:{rel}")
    if head.returncode != 0:
        return False, "not_in_head"
    try:
        head_obj = json.loads(head.stdout)
        work_obj = json.loads((ROOT / rel).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"unparseable: {exc}"
    if _strip_volatile(head_obj) == _strip_volatile(work_obj):
        return True, "volatile_only"
    return False, "content_changed"


def _gate_volatile_json_only(rel: str, ctx: dict):
    """Claim *_results.json; collectable only if the diff is timestamps/runtime."""
    if not rel.endswith("_results.json"):
        return None
    ok, why = _results_volatile_only(rel)
    return ("results_json", ok, why)


def _gate_pdf_requires_clean_sources(rel: str, ctx: dict):
    """Claim *.pdf; collectable only as a rebuild of sources already in HEAD."""
    if not rel.endswith(".pdf"):
        return None
    parts = PurePosixPath(rel).parts
    depth = ctx["ns_depth"]
    if len(parts) < depth + 1:
        return None
    scope = "/".join(parts[:depth + 1])
    dirty_sources = [d for d in ctx["dirty_set"]
                     if d.startswith(scope + "/") and d != rel
                     and PurePosixPath(d).suffix in _BUILD_SOURCE_SUFFIXES]
    if dirty_sources:
        return ("pdf", False, f"sources_dirty:{dirty_sources[:3]}")
    return ("pdf", True, "rebuild_of_head_sources")


_CONTENT_GATES = {
    "volatile_json_only": _gate_volatile_json_only,
    "pdf_requires_clean_sources": _gate_pdf_requires_clean_sources,
}


# ── the generic engine ───────────────────────────────────────────────────────


def _exclusion_reason(rel: str, ns: dict) -> str | None:
    """Return a held-reason if this path is junk, else None（預設收編）。

    這是 07-17 為 storage/drafts/ 做的反轉，現在是**全域預設**而不是單一目錄特例。
    白名單對開放集合（一次產出的副檔名沒人猜得到下一個是什麼）等於預設拒絕，而拒絕
    在這支程式裡等於永遠卡著。所以只擋真正不該進版控的東西。
    """
    exc = ns.get("exclusions") or {}
    path = PurePosixPath(rel)
    name = path.name

    if exc.get("dotfiles", True) and name.startswith("."):
        # .DS_Store、.env、編輯器 dotfile —— 沒有一個是產物。
        return "excluded_dotfile"
    if exc.get("editor_backups", True) and name.endswith("~"):
        return "excluded_editor_backup"
    suffix = path.suffix.lower()
    if suffix in {str(s).lower() for s in exc.get("suffixes") or ()}:
        return f"excluded_suffix:{suffix}"
    if set(exc.get("dirs") or ()).intersection(path.parts[:-1]):
        return "excluded_junk_path"

    full = ROOT / rel
    if exc.get("symlinks", True) and full.is_symlink():
        # 檔案頂部不變量第 4 條：git ownership 只認 exact 普通檔。
        return "excluded_symlink"
    try:
        size = full.stat().st_size
    except OSError:
        return None  # silent-ok: status→stat race；下游的 stat 會再處理一次
    limit = int(ns.get("max_file_bytes") or 0)
    if limit and size > limit:
        return f"excluded_oversize:{size // (1024 * 1024)}MB"
    return None


def scan_namespace(ns_id: str, *, now_ts: float | None = None) -> dict:
    """Classify one registered namespace's dirty/untracked files. Pure read.

    One engine, every namespace. Behaviour is entirely a function of the config
    entry — which is the point: a new managed directory is a new config row, not
    a new recognizer nobody remembers to write.
    """
    ns = get_namespace(ns_id)
    now_ts = now_ts if now_ts is not None else time.time()
    adopt_default = ns.get("default", "adopt") == "adopt"
    all_files = ns.get("status_filter", "all") != "modified"

    inflight: set[str] = set()
    if ns.get("respect_inflight", True):
        tasks = _load_json(TASKS_PATH, [])
        tasks = tasks if isinstance(tasks, list) else (
            tasks.get("tasks", []) if isinstance(tasks, dict) else [])
        inflight = _inflight_stems(tasks)

    empty = {"namespace": ns_id, "collectable": [], "held": [],
             "skipped": {"grace": 0, "inflight": 0, "unclaimed": 0}}

    # quotePath=false: figure/result filenames may carry non-ASCII; git would
    # otherwise hand back an escaped name that no longer resolves as a real path.
    status = _git("-c", "core.quotePath=false", "status", "--porcelain=v1",
                  "--untracked-files=all" if all_files else "--untracked-files=no",
                  "--", ns["path"] + "/")
    if status.returncode != 0:
        warn("reap_orphan", "namespace scan: git status failed",
             namespace=ns_id, err=status.stderr[:120])
        return empty

    collectable: list[dict] = []
    held: list[dict] = []
    skipped = {"grace": 0, "inflight": 0, "unclaimed": 0}
    records: list[tuple[str, str]] = []
    dirty_set: set[str] = set()
    deletion_dirs: set[str] = set()
    pending_rename: dict[str, list[str]] = {}

    for line in status.stdout.splitlines():
        code, rel = line[:2], line[3:].strip()
        if not rel:
            continue
        if "D" in code:
            # A disappearing file is not a deliverable. Committing the deletion
            # would be this script's first destructive act; report it instead.
            if all_files:
                pending_rename.setdefault(
                    str(PurePosixPath(rel).parent), []).append(rel)
                deletion_dirs.add(str(PurePosixPath(rel).parent))
            continue
        dirty_set.add(rel)
        if not all_files and code.strip() != "M":
            continue
        records.append((code, rel))

    ns_depth = len(PurePosixPath(ns["path"]).parts)
    gates = [(name, _CONTENT_GATES[name]) for name in ns.get("content_gates") or ()
             if name in _CONTENT_GATES]
    ctx = {"dirty_set": dirty_set, "ns_depth": ns_depth, "ns": ns}

    for code, rel in records:
        if adopt_default:
            reason = _exclusion_reason(rel, ns)
            if reason:
                held.append({"path": rel, "kind": "excluded", "reason": reason})
                continue
        try:
            if now_ts - (ROOT / rel).stat().st_mtime < GRACE_SECONDS:
                skipped["grace"] += 1
                continue  # 可能有 session 正在寫 — 給滿 grace 再說
        except OSError:
            continue  # silent-ok: status→stat race, file already gone

        if inflight:
            stem = PurePosixPath(rel).stem
            if stem in inflight or stem.replace("_draft", "") in inflight:
                skipped["inflight"] += 1
                continue

        claimed = None
        for _name, gate in gates:
            claimed = gate(rel, ctx)
            if claimed is not None:
                break
        if claimed is not None:
            kind, ok, why = claimed
            (collectable if ok else held).append(
                {"path": rel, "kind": kind, "reason": why})
            continue
        if not adopt_default:
            # hold-by-default namespace, no gate claimed it: someone else owns it.
            skipped["unclaimed"] += 1
            continue

        parent = str(PurePosixPath(rel).parent)
        if parent in deletion_dirs:
            # A pending deletion beside it means this is half of a rename (the
            # k1380 `*_INVALID_20260716.*` shape: deliberate invalidation, the
            # additive half untracked). The reaper never commits deletions, so
            # adopting only the other half would land a half-applied rename and
            # silently duplicate invalidated data. Held → escalated by name.
            pending_rename.setdefault(parent, []).append(rel)
            continue

        collectable.append({"path": rel, "kind": PurePosixPath(rel).suffix.lstrip("."),
                            "reason": "untracked" if code == "??" else "modified"})

    # One in-flight rename is one thing to do, not N orphans. k1380's deliberate
    # `*_INVALID_20260716.*` invalidation produced eight held rows with two
    # different "not owned" reasons, and the escalation task read as eight
    # ownerless artifacts when the actual state was "a directory is mid-rename,
    # waiting to be committed". Report the directory once, name its members.
    for parent in sorted(pending_rename):
        members = sorted(set(pending_rename[parent]))
        held.append({"path": parent, "kind": "pending_rename",
                     "reason": "pending_rename",
                     "detail": f"{len(members)} 個檔案處於未 commit 的改名/修改中"
                               f"（非無主）：{', '.join(members)}。"
                               f"出口是 commit 這個目錄，不是找人認領。",
                     "members": members})

    return {"namespace": ns_id, "collectable": collectable, "held": held,
            "skipped": skipped}


def scan_all_namespaces(*, now_ts: float | None = None) -> dict[str, dict]:
    """Scan every registered namespace. Adding one here means editing config only."""
    return {ns_id: scan_namespace(ns_id, now_ts=now_ts)
            for ns_id in load_registry()["namespaces"]}


def _commit_message(ns: dict, paths: list[str]) -> str:
    depth = len(PurePosixPath(ns["path"]).parts)
    scopes = sorted({PurePosixPath(p).parts[depth] for p in paths
                     if len(PurePosixPath(p).parts) > depth})
    subject = str(ns.get("commit_subject")
                  or "chore(orphan-reap): collect {count} orphaned files in " + ns["path"])
    subject = subject.format(count=len(paths), scopes=", ".join(scopes) or ns["id"])
    body = str(ns.get("commit_body") or
               "Auto-collected by reap_orphan_deliverables: files in a managed "
               "namespace that no live producer owns.")
    return (f"{subject}\n\n{body}\n\n"
            "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>")


def collect_namespace(ns_id: str, entries: list[dict]) -> list[dict]:
    """Commit one namespace's collectable files through the git writer lease."""
    out: list[dict] = []
    if not entries:
        return out
    ns = get_namespace(ns_id)
    paths = [e["path"] for e in entries]
    with _git_transaction(f"orphan-reaper:{ns_id}") as locked:
        if not locked:
            return [{"namespace": ns_id, "paths": paths, "committed": False,
                     "err": "git_writer_lock_busy"}]
        pre_staged = _git("diff", "--cached", "--name-only", "--", *paths)
        collisions = [line for line in pre_staged.stdout.splitlines() if line]
        if pre_staged.returncode != 0 or collisions:
            err = "pre_staged_collision" if collisions else "git_preflight_failed"
            return [{"namespace": ns_id, "paths": paths, "committed": False,
                     "err": err, "collisions": collisions}]
        index_owned = True
        try:
            add = _git("add", "--", *paths)
            if add.returncode != 0:
                warn("reap_orphan", "namespace add failed",
                     namespace=ns_id, err=add.stderr[:150])
                return [{"namespace": ns_id, "paths": paths, "committed": False,
                         "err": add.stderr[:150]}]
            commit = _git("commit", "--only", "-m", _commit_message(ns, paths),
                          "--", *paths)
            if commit.returncode == 0:
                index_owned = False
        finally:
            if index_owned:
                # Preflight proved no one else owned these scoped index entries,
                # so cleanup cannot erase a foreign staged change. Working files
                # remain intact for the next sweep.
                _git("reset", "-q", "HEAD", "--", *paths)
    ok = commit.returncode == 0
    if not ok:
        warn("reap_orphan", "namespace commit failed",
             namespace=ns_id, err=commit.stderr[:150])
    out.append({"namespace": ns_id, "paths": paths, "committed": ok,
                "detail": (commit.stdout or commit.stderr)[:150]})
    return out


# ── held TTL → escalation ────────────────────────────────────────────────────
# held 原本只有 reason、沒有時間軸，所以一份無主檔案可以無限期卡著，每班噴一次同樣的
# alert，永遠沒有人被指派去解。這裡給每筆 held 一個 first_seen 與班次計數：連續 N 班
# 仍無主 → 產生一張**指名該路徑清單**的任務，之後這些路徑不再重複出現在 alert 面。
# 這條與「作者自己回來 commit」無關 —— 那個假設本來就是錯的。


def _held_key(entry: dict) -> str:
    path = entry.get("path")
    if path:
        return str(path)
    return f"job:{entry.get('job_id')}"


def _write_json_atomic(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    tmp.replace(path)


def _escalation_title(paths: list[str]) -> str:
    """點名的標題：一份就寫出它是誰，多份才退回計數（並仍點名第一個）。"""
    if len(paths) == 1:
        return f"解決長期無主的產物 `{paths[0]}`（reaper held 超過 TTL）"
    return (f"解決 {len(paths)} 份長期無主的產物："
            f"`{paths[0]}` 等（reaper held 超過 TTL）")


def _close_resolved_escalations(previous: dict, current: dict) -> list[str]:
    """關掉「當初升級的 held key 已經不再 held」的那些任務。

    這是缺掉的反向對帳。``state`` 每一輪都從當前 scan 重建，所以一個 key 不再 held
    時，它的記錄就消失了 —— 連同那個 ``task_id``。任務本身沒有任何人去關，於是
    **任務活得比它的成因更久**：``experiments/k1380`` 和其中一個 job key 早已不在
    state 裡，兩張單卻還躺在 pending。任務描述裡寫的「判定完成後這張任務關閉，held
    記錄會自然消失」把因果講反了 —— 記錄消失是自動的，關單不是。

    只關「所有 held_paths 都不再 held」的單：還有任一路徑卡著，事情就沒完。
    """
    stale_tasks: dict[str, set[str]] = {}
    for key, rec in previous.items():
        task_id = isinstance(rec, dict) and rec.get("task_id")
        if task_id and key not in current:
            stale_tasks.setdefault(str(task_id), set()).add(key)
    if not stale_tasks:
        return []

    from volpred.ops.next_tasks import write_tasks_to_handle

    guard_canonical_write(TASKS_PATH)
    closed: list[str] = []
    with TASKS_PATH.open("r+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            handle.seek(0)
            raw = handle.read().strip()
            tasks = json.loads(raw) if raw else []
            if not isinstance(tasks, list):
                return []
            for task in tasks:
                if not isinstance(task, dict):
                    continue
                tid = str(task.get("id") or "")
                if tid not in stale_tasks:
                    continue
                if str(task.get("status") or "").lower() not in ("pending", "blocked"):
                    continue
                held = set((task.get("payload") or {}).get("held_paths") or [])
                # 還有路徑卡著就留著 —— 部分解決不是解決。
                if held - stale_tasks[tid]:
                    continue
                task["status"] = "succeeded"
                task["completed_at"] = _now().isoformat()
                task["result"] = (
                    "held 條件已自行消失：當初升級的路徑都不再被 reaper held"
                    f"（{', '.join(sorted(stale_tasks[tid]))}）。"
                )
                closed.append(tid)
            if closed:
                write_tasks_to_handle(handle, tasks)
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    return closed


def _escalate_held(records: dict[str, dict]) -> dict:
    """Queue one task that names every path held past the TTL.

    Goes through `volpred.ops.next_tasks.append_next_task` — the single canonical
    gateway for the pending queue (flock + guard + priority normalisation). This
    script does not get its own queue writer; a second writer is how shared state
    gets corrupted.
    """
    from volpred.ops.next_tasks import append_next_task

    paths = sorted(records)
    lines = [f"- `{key}` — {records[key].get('reason')} "
             f"(namespace={records[key].get('namespace')}, "
             f"first_seen={records[key].get('first_seen')}, "
             f"shifts={records[key].get('shifts')})"
             for key in paths]
    return append_next_task(
        # 標題必須點名**是哪一份**。只編碼份數的話，每個單路徑逃逸都渲染成同一串字，
        # 於是 7/19、7/20、7/20 三張不同 held key（experiments/k1380、兩個 job:…）
        # 在任務池裡長得一模一樣 —— 老闆看到的是「同一張單開了三次」，而實際上是三件
        # 不同的事，沒有任何 dedup 失效。分不出來的標題，讓真重複與假重複都看不見。
        title=_escalation_title(paths),
        description=(
            "reap_orphan_deliverables 連續多班仍無法為以下路徑找到出口。held 不是"
            "永久狀態：作者 session 結束後永不回來是常態（不是例外），所以出口必須"
            "由系統指派，不能等作者自己回來 commit。\n\n"
            + "\n".join(lines)
            + "\n\n逐一判定：收編（走正常 commit）、或修正 reaper 設定"
              "（config/orphan_namespaces.json 加/調一筆 namespace）、或說明為何"
              "這些檔案本來就不該進版控。**不得刪除**：檔案頂部不變量禁止 reaper 與"
              "其下游丟棄產物。\n\n若這些路徑不再被 held（已收編或設定已修），下一輪"
              "sweep 會自行關閉本單並記下理由 —— 不需要人來收尾。"
        ),
        source="reap_orphan_deliverables_held_ttl",
        task_family="ops",
        legacy_priority=30,
        payload={"held_paths": paths,
                 "held_reasons": {key: records[key].get("reason") for key in paths},
                 "tags": ["orphan_reap", "held_escalation"]},
        created_by="reap_orphan_deliverables",
        path=TASKS_PATH,
    )


def track_held(held_entries: list[dict], *, shifts_to_escalate: int | None = None,
               persist: bool = True) -> dict:
    """Age every held entry one shift; escalate the ones past the TTL.

    Returns the per-key state plus the suppression set — keys already escalated
    are owned by a task now, so re-alerting on them every shift is noise.
    """
    if shifts_to_escalate is None:
        shifts_to_escalate = load_registry()["held_escalation_shifts"]
    # No state file yet is the normal first run, not a fault — reading it through
    # _load_json would warn on every sweep about an absence that means "nothing
    # has been held long enough to have a clock yet".
    previous: dict = {}
    if HELD_STATE_PATH.exists():
        loaded = _load_json(HELD_STATE_PATH, {})
        if isinstance(loaded, dict) and isinstance(loaded.get("entries"), dict):
            previous = loaded["entries"]
    now_iso = _now().isoformat()

    state: dict[str, dict] = {}
    for entry in held_entries:
        key = _held_key(entry)
        prior = previous.get(key) if isinstance(previous.get(key), dict) else None
        record = dict(prior) if prior else {"first_seen": now_iso, "shifts": 0}
        record["shifts"] = int(record.get("shifts") or 0) + 1
        record["last_seen"] = now_iso
        record["reason"] = entry.get("reason")
        record["namespace"] = entry.get("namespace")
        state[key] = record

    # 反向對帳先於升級：一張成因已消失的單還開著，會讓下一次判斷「這件事有人管了嗎」
    # 讀到錯的答案。
    resolved = _close_resolved_escalations(previous, state) if persist else []

    pending = {key: rec for key, rec in state.items()
               if rec["shifts"] >= shifts_to_escalate and not rec.get("task_id")}
    escalations: list[dict] = []
    if pending and persist:
        task = _escalate_held(pending)
        for rec in pending.values():
            rec["task_id"] = task["id"]
            rec["escalated_at"] = now_iso
        escalations.append({"task_id": task["id"], "paths": sorted(pending)})

    suppressed = sorted(key for key, rec in state.items() if rec.get("task_id"))
    if persist:
        _write_json_atomic(HELD_STATE_PATH, {
            "note": "held 的時間軸。超過 held_escalation_shifts 班仍無主 → 指名任務。"
                    "一筆記錄消失 = 那個路徑已經有出口了。",
            "updated_at": now_iso,
            "shifts_to_escalate": shifts_to_escalate,
            "entries": state,
        })
    return {"state": state, "escalations": escalations, "suppressed": suppressed,
            "resolved_tasks": resolved}


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
    ap.add_argument("--max-draft-files", type=int, default=None,
                    help="覆寫 drafts namespace 的 max_files（預設讀 "
                         "config/orphan_namespaces.json）")
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
    namespace_scans = scan_all_namespaces()
    registry = load_registry()
    job_deliveries: list[dict] = []
    namespace_collections: dict[str, list[dict]] = {}
    adopted: list[dict] = []
    if args.apply:
        # Before adopt(): commit the stable on-disk state. publish_draft.py may
        # rewrite frontmatter, and that delta is collected on a later run once it
        # ages past the grace window — never mid-write.
        for ns_id, ns_scan in namespace_scans.items():
            limit = registry["namespaces"][ns_id].get("max_files") or 0
            if ns_id == "drafts" and args.max_draft_files is not None:
                limit = args.max_draft_files
            batch = ns_scan["collectable"][:limit] if limit else ns_scan["collectable"]
            collected = collect_namespace(ns_id, batch)
            if collected:
                namespace_collections[ns_id] = collected
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
    # Every held entry, from every source, ages on the same clock. held is not a
    # terminal state any more: past the TTL it becomes a task that names the paths.
    all_held: list[dict] = [{**h, "namespace": "drafts_intake"} for h in result["held"]]
    all_held += [{**h, "namespace": "compute_queue"} for h in job_scan["held"]]
    for ns_id, ns_scan in namespace_scans.items():
        all_held += [{**h, "namespace": ns_id} for h in ns_scan["held"]]
    tracking = track_held(all_held, persist=args.apply)
    suppressed = set(tracking["suppressed"])

    def _open_held(entries: list[dict]) -> list[dict]:
        """Held entries still worth alerting on — escalated ones have an owner."""
        return [h for h in entries if _held_key(h) not in suppressed]

    result["adopted"] = adopted
    result["applied"] = args.apply
    result["job_deliverable_candidates"] = job_scan["candidates"]
    result["job_deliverable_held"] = _open_held(job_scan["held"])
    result["job_deliveries"] = job_deliveries
    result["namespaces"] = {
        ns_id: {
            "collectable": ns_scan["collectable"],
            "held": _open_held(ns_scan["held"]),
            "skipped": ns_scan["skipped"],
            "collections": namespace_collections.get(ns_id, []),
        }
        for ns_id, ns_scan in namespace_scans.items()
    }
    result["held"] = _open_held(result["held"])
    result["orphan_count"] = len(result["adoptable"]) + len(result["held"])
    result["held_escalations"] = tracking["escalations"]
    result["held_escalated_paths"] = tracking["suppressed"]

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
          f"已交付 {len(delivered_jobs)}、保留 {len(result['job_deliverable_held'])}")
    for ns_id, view in result["namespaces"].items():
        committed = sum(len(c["paths"]) for c in view["collections"] if c.get("committed"))
        print(f"[reap] namespace {ns_id}：可收 {len(view['collectable'])}、"
              f"已提交 {committed}、保留 {len(view['held'])}、略過 {view['skipped']}")
        for h in view["held"][:5]:
            print(f"  - 保留 {h['path']} — {h['reason']}")
    for esc in result["held_escalations"]:
        print(f"[reap] held 超過 TTL → 已開任務 {esc['task_id']}："
              f"{len(esc['paths'])} 條路徑（此後不再重複噴同一句 alert）")
    if result["held_escalated_paths"]:
        print(f"[reap] 已升級為任務、alert 靜音中：{len(result['held_escalated_paths'])} 條")
    print(f"[reap] 略過：{result['skipped']}")
    for h in result["held"][:10]:
        print(f"  - 保留 {h['path']} — {h.get('detail') or h.get('reason')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
