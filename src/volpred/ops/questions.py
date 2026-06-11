from __future__ import annotations

from datetime import datetime, timezone
import fcntl
import json
from typing import Any

from scripts.supabase_sync import (
    _patch_where,
    _patch_where_returning,
    _post,
    _select_rows,
)
from volpred.memory.system import MemorySystem

from .common import dump_json, load_json, project_path, write_ops_snapshot


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_article_status(article_slug: str) -> str | None:
    """Return the Supabase status of an article ('published', 'draft', etc.)."""
    try:
        rows = _select_rows("articles", select="id,status", slug=article_slug)
        if rows:
            return str(rows[0].get("status") or "")
    except Exception:
        pass
    return None


def _link_question_article(question_id: str, article_slug: str) -> bool:
    """Insert a question_articles row linking a question to an article.

    Uses the article slug to resolve the Supabase article UUID, then upserts
    into the question_articles table.  Returns True on success.
    """
    try:
        from scripts.supabase_sync import _get_article_id
        article_id = _get_article_id(article_slug)
        if not article_id:
            return False
        return _post("question_articles", {"question_id": question_id, "article_id": article_id})
    except Exception:
        return False


def claim_question_for_research(question_id: str) -> dict:
    """Atomically claim a question for research using status transition as lock.

    Transition: status='ranked' → status='researching' (conditional).
    If another session already changed status to 'researching' (or beyond),
    this call returns claimed=False. Protects against cross-session races
    where two concurrent sessions pick the same top-ranked question.

    Uses Supabase conditional PATCH with return=representation, so we know
    whether any row was actually updated (not just HTTP success).
    """
    now = _utc_now()
    affected = _patch_where_returning(
        "questions",
        {"id": question_id, "status": "ranked"},
        {"status": "researching", "updated_at": now},
    )
    if affected:
        return {
            "claimed": True,
            "question_id": question_id,
            "question": affected[0],
        }
    # Check current status to explain why claim failed
    current = _select_rows(
        "questions", select="id,status,updated_at", id=question_id
    )
    if not current:
        return {"claimed": False, "question_id": question_id, "reason": "not_found"}
    return {
        "claimed": False,
        "question_id": question_id,
        "reason": f"current_status={current[0].get('status')}",
        "current_status": current[0].get("status"),
    }


def archive_question(question_id: str, reason: str = "manual") -> dict:
    """Archive a question (remove from ranking pool).

    Status transition: any → 'archived'. No status check (force archive)
    so it works on test spam / accidental submissions regardless of
    current state. Preserves the row for audit; question-ranking-summary
    ignores status='archived'.
    """
    now = _utc_now()
    affected = _patch_where_returning(
        "questions",
        {"id": question_id},
        {"status": "archived", "updated_at": now},
    )
    if not affected:
        return {"archived": False, "question_id": question_id, "reason": "not_found"}
    # affected[0].status is post-patch ('archived'); read pre-patch state via
    # a separate select before the patch if the caller wants true prev.
    # Keeping this simple: return current (archived) status for audit.
    return {
        "archived": True,
        "question_id": question_id,
        "new_status": affected[0].get("status"),
        "archive_reason": reason,
    }


def answer_internal_question(
    question_id: str,
    answer: str,
    storage_dir: str = "storage",
    article_id: str | None = None,
) -> dict:
    # Determine if the linked article is already published
    article_is_published = False
    if article_id:
        article_status = _get_article_status(article_id)
        article_is_published = article_status == "published"

    memory = MemorySystem(storage_dir=storage_dir)

    if article_is_published:
        # Article is published → mark question as answered
        memory.answer_question(question_id, answer)
        question_status = "answered"
    else:
        # Article is draft/scheduled → keep question as researching, store pending article
        questions = load_json(project_path(storage_dir, "memory", "open_questions.json"), [])
        for q in questions:
            if q["id"] == question_id:
                q["status"] = "researching"
                q["answer"] = answer
                q["pending_article"] = article_id
                break
        filepath = project_path(storage_dir, "memory", "open_questions.json")
        dump_json(filepath, questions)
        question_status = "researching"

    # Update Supabase question status
    _patch_where("questions", {"id": question_id}, {
        "status": question_status,
        "answer": answer[:500] if answer else None,
        "updated_at": _utc_now(),
        **({"answered_at": _utc_now()} if article_is_published else {}),
    })

    linked_article = False
    if article_id:
        linked_article = _link_question_article(question_id, article_id)
        # Ensure article's details.question_id is set so frontend sync
        # (syncQuestionArticleLinks) maintains the link on every article upsert.
        _ensure_article_question_metadata(article_id, question_id)

    return {
        "id": question_id,
        "found": True,
        "status": question_status,
        "article_published": article_is_published,
        "linked_article": article_id if linked_article else None,
        "note": None if article_is_published else "文章尚未發佈，問題保持 researching 狀態。文章發佈時會自動標為 answered。",
    }


def _ensure_article_question_metadata(article_slug: str, question_id: str) -> None:
    """Write question_id into article's details so frontend sync preserves the link.

    The frontend syncQuestionArticleLinks() reads details.question_id on every
    article upsert to rebuild question_articles rows. Without this metadata,
    the link gets dropped on the next sync cycle.
    """
    try:
        # Update local report JSON
        import json
        from pathlib import Path
        report_path = Path("storage/reports") / f"{article_slug}.json"
        if report_path.exists():
            report = json.loads(report_path.read_text())
            if not report.get("details"):
                report["details"] = {}
            report["details"]["question_id"] = question_id
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))

        # Update feed.json
        feed_path = Path("storage/reports/feed.json")
        if feed_path.exists():
            feed = json.loads(feed_path.read_text())
            for item in feed:
                if item.get("id") == article_slug:
                    if not item.get("details"):
                        item["details"] = {}
                    item["details"]["question_id"] = question_id
                    break
            feed_path.write_text(json.dumps(feed, ensure_ascii=False, indent=2))

        # Update Supabase article details
        rows = _select_rows("articles", select="id,details", slug=article_slug)
        if rows:
            details = rows[0].get("details") or {}
            details["question_id"] = question_id
            _patch_where("articles", {"slug": article_slug}, {"details": details})
    except Exception:
        pass  # Non-critical; question_articles row is the primary link


ACTIVE_USER_STATUSES = {"ranked", "researching"}
PENDING_USER_STATUSES = {"evaluating", "pending", "open"}
MEMBER_QA_ACTIVE_TASK_STATUSES = {
    "pending",
    "claimed",
    "in_progress",
    "blocked",
    "blocked_on_user",
    "pending_main_thread",
}

# 2026-06-11 (boss): member_qa min-age gate. A question must be at least this
# old before it gets materialized into a research/evaluate task. The 6h cron
# cadence (0/6/12/18) was a dispatch interval, NOT a per-question cooldown — a
# question posted at 17:31 was processed at the 18:00 fire (酒店文 mile_9b76989e).
# Boss wants a real cooldown so questions are not answered the moment they land.
MEMBER_QA_MIN_AGE_SECONDS = 6 * 3600


def _parse_time(value: Any) -> float:
    if not value:
        return 0.0
    text = str(value).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return 0.0


def _active_rank_sort_key(row: dict[str, Any]) -> tuple[int, float, float]:
    status = str(row.get("status") or "")
    status_group = 0 if status == "researching" else 1
    current_rank = row.get("current_rank")
    prev_rank = row.get("prev_rank")
    created_at = _parse_time(row.get("created_at"))

    if isinstance(current_rank, (int, float)):
        rank_order = int(current_rank)
    elif isinstance(prev_rank, (int, float)):
        rank_order = int(prev_rank)
    else:
        # Bootstrap path for older rows before ranking fields existed.
        rank_order = 10_000

    score = float(row.get("score") or 0)
    return (status_group, rank_order, -score, -created_at)


def _candidate_sort_key(entry: dict[str, Any]) -> tuple[float, float, str]:
    score = float(entry.get("score") or 0)
    created_at = _parse_time(entry.get("created_at"))
    return (-score, created_at, str(entry.get("id") or ""))


def _build_question_index(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("id")): row
        for row in rows
        if row.get("id")
    }


def _active_question_order(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    active = [row for row in rows if str(row.get("status") or "") in ACTIVE_USER_STATUSES]
    active.sort(key=_active_rank_sort_key)
    return active


def _merge_scored_candidates(
    base_ranked: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged = list(base_ranked)
    for candidate in sorted(candidates, key=_candidate_sort_key):
        candidate_score = float(candidate.get("score") or 0)
        insert_at = len(merged)
        for idx, existing in enumerate(merged):
            existing_score = float(existing.get("score") or 0)
            if candidate_score > existing_score:
                insert_at = idx
                break
        merged.insert(insert_at, candidate)
    return merged


def _linked_article_count_map(question_ids: list[str]) -> dict[str, int]:
    if not question_ids:
        return {}

    rows = _select_rows("question_articles", select="question_id,article_id")
    counts: dict[str, int] = {question_id: 0 for question_id in question_ids}
    for row in rows:
        question_id = str(row.get("question_id") or "")
        if question_id in counts:
            counts[question_id] += 1
    return counts


def _rank_delta(current_rank: int, prev_rank: Any) -> tuple[str, int | None]:
    if not isinstance(prev_rank, (int, float)):
        return ("new", None)
    delta = int(prev_rank) - current_rank
    if delta > 0:
        return ("up", delta)
    if delta < 0:
        return ("down", abs(delta))
    return ("same", 0)


def get_member_question_ranking_summary(
    *,
    source: str = "user",
    limit: int = 20,
) -> dict[str, Any]:
    question_rows = _select_rows(
        "questions",
        select=(
            "id,source,user_id,question,status,score,current_rank,score_breakdown,"
            "prev_rank,proposer,created_at,updated_at,answered_at"
        ),
        source=source,
    )
    question_ids = [str(row.get("id")) for row in question_rows if row.get("id")]
    linked_counts = _linked_article_count_map(question_ids)
    candidate_rows = _select_rows(
        "question_research_candidates",
        select=(
            "id,question_id,status,requested_by,claimed_by,notes,score_snapshot,"
            "question_snapshot,linked_articles_count,completed_at,created_at,updated_at"
        ),
    )
    candidate_rows.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)

    active_ranked = [
        row for row in question_rows
        if str(row.get("status") or "") not in {"answered", "evaluating", "pending", "open", "archived"}
    ]
    active_ranked.sort(key=_active_rank_sort_key)

    pending_rows = [
        row for row in question_rows if str(row.get("status") or "") in PENDING_USER_STATUSES
    ]
    pending_rows.sort(key=lambda row: _parse_time(row.get("created_at")), reverse=True)

    ranked_table: list[dict[str, Any]] = []
    for index, row in enumerate(active_ranked[: max(limit, 1)], start=1):
        current_rank = row.get("current_rank")
        rank = int(current_rank) if isinstance(current_rank, (int, float)) else index
        direction, delta = _rank_delta(rank, row.get("prev_rank"))
        question_id = str(row.get("id") or "")
        ranked_table.append(
            {
                "rank": rank,
                "prev_rank": row.get("prev_rank") if isinstance(row.get("prev_rank"), (int, float)) else None,
                "rank_delta": delta,
                "rank_direction": direction,
                "question_id": question_id,
                "question": row.get("question") or "",
                "proposer": row.get("proposer") or "會員",
                "status": row.get("status") or "",
                "score": row.get("score") if isinstance(row.get("score"), (int, float)) else None,
                "linked_articles_count": linked_counts.get(question_id, 0),
                "created_at": row.get("created_at"),
            }
        )

    pending_questions: list[dict[str, Any]] = []
    for row in pending_rows[: max(limit, 1)]:
        question_id = str(row.get("id") or "")
        pending_questions.append(
            {
                "question_id": question_id,
                "question": row.get("question") or "",
                "proposer": row.get("proposer") or "會員",
                "status": row.get("status") or "",
                "created_at": row.get("created_at"),
                "linked_articles_count": linked_counts.get(question_id, 0),
                "suggested_payload": {
                    "question_id": question_id,
                    "score": None,
                    "score_breakdown": None,
                },
            }
        )

    latest_member_question_at = None
    created_values = sorted(
        [str(row.get("created_at")) for row in question_rows if row.get("created_at")],
        reverse=True,
    )
    if created_values:
        latest_member_question_at = created_values[0]

    latest_answered_at = None
    answered_values = sorted(
        [str(row.get("answered_at")) for row in question_rows if row.get("answered_at")],
        reverse=True,
    )
    if answered_values:
        latest_answered_at = answered_values[0]

    scored_questions = sum(1 for row in question_rows if isinstance(row.get("score"), (int, float)))
    researching_count = sum(1 for row in question_rows if str(row.get("status") or "") == "researching")
    answered_count = sum(1 for row in question_rows if str(row.get("status") or "") == "answered")

    suggestions: list[str] = []
    if pending_questions:
        suggestions.append(
            f"目前有 {len(pending_questions)} 題待評分會員問題，可在下一次 6 小時評分週期生成 evaluation payload。"
        )
    queued_candidates = [row for row in candidate_rows if str(row.get("status") or "queued") == "queued"]
    if queued_candidates:
        suggestions.append(
            f"研究候選池中有 {len(queued_candidates)} 題待領取，可優先處理高分但尚未連文的題目。"
        )
    uncovered_ranked = [row for row in ranked_table if row.get("linked_articles_count", 0) == 0]
    if uncovered_ranked:
        suggestions.append(
            f"前 {min(len(uncovered_ranked), 5)} 名中仍有未連文章題目，適合優先安排研究或發文。"
        )
    if not researching_count and ranked_table:
        suggestions.append("目前沒有研究中的會員題目，可從榜首或候選池中領取下一題。")
    if not suggestions:
        suggestions.append("目前會員問題排行健康，可維持既有 6 小時評分節奏。")

    return {
        "generated_at": _utc_now(),
        "cadence_hint": "每 6 小時檢查 pending_questions，評分後呼叫 question-rerank；既有榜單相對順序不應變動。",
        "table_columns": ["排名", "前次排名", "主題", "提出者", "狀態"],
        "health": {
            "active_ranked": len(active_ranked),
            "pending_evaluation": len(pending_rows),
            "researching": researching_count,
            "answered": answered_count,
            "scored_questions": scored_questions,
            "candidate_pool": len(candidate_rows),
            "latest_member_question_at": latest_member_question_at,
            "latest_answered_at": latest_answered_at,
        },
        "ranked_table": ranked_table,
        "pending_questions": pending_questions,
        "candidate_pool": candidate_rows[: max(limit, 1)],
        "suggestions": suggestions,
    }


def ensure_member_qa_task(
    *,
    source: str = "user",
    storage_dir: str = "storage",
) -> dict[str, Any]:
    """Materialize one member_qa task into next_tasks.json when work is pending.

    Priority order:
    1. Top-ranked question with no researching question in flight.
    2. Latest pending-evaluation question as an evaluate→rerank→research task.

    Dedupe key is `question_id` against active next_tasks member_qa entries.
    """
    summary = get_member_question_ranking_summary(source=source, limit=10)
    ranked_table = summary.get("ranked_table") if isinstance(summary.get("ranked_table"), list) else []
    pending_questions = summary.get("pending_questions") if isinstance(summary.get("pending_questions"), list) else []
    health = summary.get("health") if isinstance(summary.get("health"), dict) else {}

    if int(health.get("researching", 0) or 0) > 0:
        return {"created": False, "reason": "already_researching"}

    # 2026-06-11 (boss): min-age gate — skip questions younger than 6h so they
    # are not answered the moment they land. Track the youngest gated candidate
    # for observability (so the cron log shows "waiting, not stuck").
    now_ts = datetime.now(timezone.utc).timestamp()

    def _too_young(item: dict[str, Any]) -> bool:
        created = _parse_time(item.get("created_at"))
        if created <= 0:
            return False  # unknown age → don't block (fail-open, avoid stuck)
        return (now_ts - created) < MEMBER_QA_MIN_AGE_SECONDS

    gated_min_age = 0

    candidate: dict[str, Any] | None = None
    mode = "research"
    for item in ranked_table:
        if isinstance(item, dict) and str(item.get("status") or "") == "ranked":
            if _too_young(item):
                gated_min_age += 1
                continue
            candidate = item
            break

    if candidate is None and pending_questions:
        for item in pending_questions:
            if isinstance(item, dict):
                if _too_young(item):
                    gated_min_age += 1
                    continue
                candidate = item
                mode = "evaluate"
                break

    if candidate is None:
        reason = (
            "min_age_gate_all_too_young"
            if gated_min_age > 0
            else "no_pending_member_qa_work"
        )
        return {"created": False, "reason": reason, "gated_min_age": gated_min_age}

    question_id = str(candidate.get("question_id") or "").strip()
    if not question_id:
        return {"created": False, "reason": "missing_question_id"}

    next_tasks_path = project_path(storage_dir, "next_tasks.json")
    next_tasks_path.parent.mkdir(parents=True, exist_ok=True)
    if not next_tasks_path.exists():
        next_tasks_path.write_text("[]\n", encoding="utf-8")

    with next_tasks_path.open("r+", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            tasks = json.load(fh)
            if not isinstance(tasks, list):
                raise ValueError("next_tasks.json is not a list")

            for task in tasks:
                if not isinstance(task, dict):
                    continue
                if str(task.get("task_type") or "") != "member_qa":
                    continue
                if str(task.get("question_id") or "") != question_id:
                    continue
                if str(task.get("status") or "") in MEMBER_QA_ACTIVE_TASK_STATUSES:
                    return {
                        "created": False,
                        "reason": "task_already_exists",
                        "task_id": task.get("id"),
                    }

            title = _build_member_qa_task_title(candidate)
            task_id = _build_member_qa_task_id(question_id=question_id, mode=mode)
            task = {
                "id": task_id,
                "title": title,
                "description": _build_member_qa_task_description(candidate, mode=mode),
                "task_type": "member_qa",
                "priority": 2,
                "status": "pending",
                "tags": ["member_qa", source],
                "created_at": _utc_now(),
                "source": "question_ops_maintain",
                "question_id": question_id,
                "question_status": candidate.get("status"),
                "proposer": candidate.get("proposer"),
                "question_score": candidate.get("score"),
                "task_mode": mode,
            }
            tasks.append(task)
            fh.seek(0)
            fh.truncate()
            json.dump(tasks, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)

    return {
        "created": True,
        "task_id": task_id,
        "question_id": question_id,
        "mode": mode,
    }


def _build_member_qa_task_id(*, question_id: str, mode: str) -> str:
    suffix = "research" if mode == "research" else "evaluate"
    return f"member_qa_{question_id.split('-')[0]}_{suffix}"


def _build_member_qa_task_title(candidate: dict[str, Any]) -> str:
    proposer = str(candidate.get("proposer") or "會員").strip()
    question = " ".join(str(candidate.get("question") or "").split())
    if not question:
        question = f"question {candidate.get('question_id')}"
    return f"[member_qa] {proposer} 提問：{question[:80]}"


def _build_member_qa_task_description(candidate: dict[str, Any], *, mode: str) -> str:
    question_id = str(candidate.get("question_id") or "").strip()
    proposer = str(candidate.get("proposer") or "會員").strip()
    question = str(candidate.get("question") or "").strip()
    created_at = str(candidate.get("created_at") or "").strip()
    score = candidate.get("score")
    score_line = f"Current score: {score}\n" if isinstance(score, (int, float)) else ""
    if mode == "research":
        workflow = (
            "執行流程：\n"
            f"1. uv run volpred ops question-claim --question-id {question_id} --actor claude\n"
            "2. 依 member_qa workflow 完成 research / write / question-answer / question-finish\n"
            "3. 文章需 published（member_qa 不走 release pool）並加非投資建議 disclaimer\n"
        )
    else:
        workflow = (
            "執行流程：\n"
            "1. uv run volpred ops question-ranking-workflow --source user --output-json /tmp/q_workflow.json\n"
            "2. 主線程逐題做 4 維度評分（研究可行性 / 讀者價值 / 研究相關性 / 預期影響力）\n"
            "3. uv run volpred ops question-rerank --evaluations-json /tmp/q_evals.json\n"
            f"4. rerank 後如本題入榜，再 uv run volpred ops question-claim --question-id {question_id} --actor claude\n"
            "5. 完成 research / write / question-answer / question-finish\n"
        )
    return (
        f"Member question id: {question_id}\n"
        f"Proposer: {proposer}\n"
        f"Created: {created_at}\n"
        f"{score_line}"
        f"\n原題：\n{question}\n\n"
        f"{workflow}\n"
        "注意：member_qa 為 reader-facing published flow，不可只 review report 就停。"
    )


def build_question_rerank_workflow(
    *,
    source: str = "user",
    limit: int = 20,
    storage_dir: str | None = None,
    write_latest: bool = False,
) -> dict[str, Any]:
    summary = get_member_question_ranking_summary(source=source, limit=limit)
    evaluation_template = []
    for item in summary.get("pending_questions", []):
        evaluation_template.append(
            {
                "question_id": item.get("question_id"),
                "score": None,
                "score_breakdown": {
                    "研究可行性": None,
                    "讀者價值": None,
                    "研究相關性": None,
                    "預期影響力": None,
                },
            }
        )

    workflow = {
        **summary,
        "workflow_name": "member_question_rerank_cycle",
        "workflow_steps": [
            "讀 pending_questions 與 ranked_table，理解現有榜單與待評分題目。",
            "用 LLM 對 pending_questions 逐題評分，填入 evaluation_template。",
            "執行 question-rerank，把新題目插入既有榜單，且不改變舊榜單相對順序。",
        ],
        "evaluation_template": evaluation_template,
        "next_commands": {
            "read_summary": f"uv run python -m volpred.cli ops question-ranking-summary --source {source} --limit {limit}",
            "apply_rerank": "uv run python -m volpred.cli ops question-rerank --evaluations-json /path/to/evaluations.json",
        },
    }
    if write_latest:
        target = write_ops_snapshot(
            "question-ranking-workflow-latest",
            workflow,
            storage_dir=storage_dir or "storage",
        )
        workflow["snapshot_path"] = str(target.relative_to(project_path()))
    return workflow


def rerank_member_questions(
    evaluations: list[dict[str, Any]],
    *,
    source: str = "user",
) -> dict[str, Any]:
    question_rows = _select_rows(
        "questions",
        select="id,source,user_id,question,status,score,current_rank,score_breakdown,prev_rank,proposer,created_at,updated_at,answered_at",
        source=source,
    )
    question_index = _build_question_index(question_rows)

    previous_active = _active_question_order(question_rows)
    previous_ranks = {
        str(row.get("id")): index + 1
        for index, row in enumerate(previous_active)
    }

    researching_rows = [row for row in previous_active if str(row.get("status") or "") == "researching"]
    ranked_rows = [row for row in previous_active if str(row.get("status") or "") == "ranked"]

    candidate_rows: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for evaluation in evaluations:
        question_id = str(evaluation.get("question_id") or "").strip()
        if not question_id:
            continue
        row = question_index.get(question_id)
        if not row:
            skipped.append({"question_id": question_id, "reason": "not_found"})
            continue
        status = str(row.get("status") or "")
        if status not in PENDING_USER_STATUSES:
            skipped.append({"question_id": question_id, "reason": f"status:{status}"})
            continue

        score = evaluation.get("score")
        if not isinstance(score, (int, float)):
            skipped.append({"question_id": question_id, "reason": "missing_score"})
            continue

        candidate_rows.append(
            {
                **row,
                "status": "ranked",
                "score": int(round(float(score))),
                "score_breakdown": evaluation.get("score_breakdown"),
            }
        )

    merged_ranked = _merge_scored_candidates(ranked_rows, candidate_rows)
    final_active = researching_rows + merged_ranked

    updated_rows: list[dict[str, Any]] = []
    for current_rank, row in enumerate(final_active, start=1):
        question_id = str(row.get("id"))
        update_payload = {
            "status": str(row.get("status") or "ranked"),
            "score": row.get("score"),
            "current_rank": current_rank,
            "score_breakdown": row.get("score_breakdown"),
            "prev_rank": previous_ranks.get(question_id),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if _patch_where("questions", {"id": question_id}, update_payload):
            updated_rows.append(
                {
                    "question_id": question_id,
                    "rank": current_rank,
                    "prev_rank": previous_ranks.get(question_id),
                    "status": update_payload["status"],
                    "score": update_payload["score"],
                }
            )

    return {
        "source": source,
        "evaluated_count": len(candidate_rows),
        "updated_count": len(updated_rows),
        "previous_active_count": len(previous_active),
        "final_active_count": len(final_active),
        "updated_rows": updated_rows,
        "skipped": skipped,
    }
