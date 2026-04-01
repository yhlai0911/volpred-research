from __future__ import annotations

import os
import socket
import time
import traceback
import uuid
from datetime import datetime, timezone
from subprocess import CompletedProcess
from typing import Any

from scripts.supabase_sync import _patch_where, _post, _select_rows

from .content import (
    build_platform_cycle_summary,
    cleanup_test_post,
    publish_milestone_article,
    preview_release_pool_by_settings,
    release_pool_articles,
    release_pool_by_settings,
    send_article_notification,
    send_daily_digest,
    unpublish_article,
)
from .health import health_snapshot
from .papers import migrate_paper_pdf_to_storage, upload_paper_pdf, upsert_paper_metadata
from .questions import (
    answer_internal_question,
    build_question_rerank_workflow,
    get_member_question_ranking_summary,
    rerank_member_questions,
)
from .strategies import activate_strategy, deactivate_strategy, upsert_strategy_metadata
from .sync import run_daily_update, run_recalc_metrics, sync_all

JobStatus = str
JobScope = str

DEFAULT_SCOPE: JobScope = "local"
DEFAULT_SOURCE = "agent"
ACTIVE_STATUSES = {"queued", "running"}
SUPPORTED_ACTIONS = (
    "cleanup_test_post",
    "daily_update",
    "health_check",
    "paper_migrate_storage",
    "paper_upload_pdf",
    "paper_upsert",
    "platform_cycle_summary",
    "publish_milestone",
    "question_rerank",
    "question_ranking_summary",
    "question_ranking_workflow",
    "release_article_pool",
    "release_article_pool_by_settings",
    "send_article_notification",
    "send_daily_digest",
    "question_answer",
    "recalc_metrics",
    "strategy_set_active",
    "strategy_upsert",
    "sync_all",
    "unpublish_article",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_worker_id() -> str:
    explicit = os.environ.get("VOLPRED_WORKER_ID")
    if explicit:
        return explicit
    return f"{socket.gethostname()}:{os.getpid()}"


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, CompletedProcess):
        return {
            "returncode": value.returncode,
            "stdout": value.stdout,
            "stderr": value.stderr,
        }
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return str(value)


def _job_select() -> str:
    return (
        "id,action,scope,source,requested_by,payload,dry_run,priority,status,"
        "worker_id,result,error,dedupe_key,created_at,started_at,finished_at,updated_at"
    )


def append_job_log(job_id: str, level: str, message: str, data: dict[str, Any] | None = None) -> bool:
    return _post(
        "ops_job_logs",
        {
            "job_id": job_id,
            "level": level,
            "message": message,
            "data": _json_safe(data) if data is not None else None,
            "created_at": _utc_now(),
        },
    )


def record_audit_log(
    *,
    action: str,
    source: str,
    actor: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    status: str = "succeeded",
    payload: dict[str, Any] | None = None,
    result: Any = None,
    error: str | None = None,
) -> bool:
    return _post(
        "ops_audit_logs",
        {
            "action": action,
            "source": source,
            "actor": actor,
            "target_type": target_type,
            "target_id": target_id,
            "status": status,
            "payload": _json_safe(payload) if payload is not None else {},
            "result": _json_safe(result),
            "error": error,
            "created_at": _utc_now(),
        },
    )


def list_jobs(
    *,
    status: JobStatus | None = None,
    scope: JobScope | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    filters: dict[str, object] = {}
    if status:
        filters["status"] = status
    if scope:
        filters["scope"] = scope

    rows = _select_rows("ops_jobs", select=_job_select(), **filters)
    rows.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
    return rows[: max(limit, 1)]


def get_job(job_id: str) -> dict[str, Any] | None:
    rows = _select_rows("ops_jobs", select=_job_select(), id=job_id)
    if not rows:
        return None

    logs = _select_rows(
        "ops_job_logs",
        select="id,job_id,level,message,data,created_at",
        job_id=job_id,
    )
    logs.sort(key=lambda row: str(row.get("created_at") or ""))

    job = rows[0]
    job["logs"] = logs
    return job


def enqueue_job(
    *,
    action: str,
    payload: dict[str, Any] | None = None,
    scope: JobScope = DEFAULT_SCOPE,
    source: str = DEFAULT_SOURCE,
    requested_by: str | None = None,
    dry_run: bool = False,
    priority: int = 100,
    dedupe_key: str | None = None,
) -> dict[str, Any]:
    if dedupe_key:
        existing = _select_rows(
            "ops_jobs",
            select=_job_select(),
            dedupe_key=dedupe_key,
        )
        for row in existing:
            if row.get("status") in ACTIVE_STATUSES:
                return row

    job = {
        "id": str(uuid.uuid4()),
        "action": action,
        "scope": scope,
        "source": source,
        "requested_by": requested_by,
        "payload": _json_safe(payload or {}),
        "dry_run": dry_run,
        "priority": priority,
        "status": "queued",
        "worker_id": None,
        "result": None,
        "error": None,
        "dedupe_key": dedupe_key,
        "created_at": _utc_now(),
        "started_at": None,
        "finished_at": None,
        "updated_at": _utc_now(),
    }
    if not _post("ops_jobs", job):
        raise RuntimeError(f"Failed to enqueue ops job: {action}")
    append_job_log(job["id"], "info", "Job queued", {"action": action, "scope": scope})
    record_audit_log(
        action=action,
        source=source,
        actor=requested_by,
        target_type="ops_job",
        target_id=job["id"],
        status="queued",
        payload=payload or {},
    )
    return job


def _claim_job(job: dict[str, Any], worker_id: str) -> dict[str, Any] | None:
    now = _utc_now()
    claimed = _patch_where(
        "ops_jobs",
        {"id": job["id"], "status": "queued"},
        {
            "status": "running",
            "worker_id": worker_id,
            "started_at": now,
            "updated_at": now,
            "error": None,
        },
    )
    if not claimed:
        return None

    refreshed = _select_rows("ops_jobs", select=_job_select(), id=job["id"])
    if not refreshed:
        return None
    row = refreshed[0]
    if row.get("status") != "running" or row.get("worker_id") != worker_id:
        return None
    return row


def claim_next_job(scope: JobScope = DEFAULT_SCOPE, worker_id: str | None = None) -> dict[str, Any] | None:
    worker = worker_id or _default_worker_id()
    rows = _select_rows("ops_jobs", select=_job_select(), status="queued", scope=scope)
    rows.sort(key=lambda row: (int(row.get("priority") or 100), str(row.get("created_at") or "")))
    for row in rows:
        claimed = _claim_job(row, worker)
        if claimed:
            return claimed
    return None


def _run_action(action: str, payload: dict[str, Any]) -> Any:
    if action == "publish_milestone":
        return {
            "id": publish_milestone_article(
                title=str(payload["title"]),
                description=str(payload["description"]),
                phase=str(payload["phase"]),
                details=payload.get("details") if isinstance(payload.get("details"), dict) else None,
                tags=list(payload.get("tags") or []),
                status=str(payload.get("status", "published")),
                publish_at=str(payload["publish_at"]) if payload.get("publish_at") else None,
                storage_dir=str(payload.get("storage_dir", "storage")),
            )
        }
    if action == "release_article_pool":
        return release_pool_articles(
            pub_id=str(payload["pub_id"]) if payload.get("pub_id") else None,
            limit=int(payload.get("limit", 1) or 1),
            due_only=bool(payload.get("due_only", True)),
            storage_dir=str(payload.get("storage_dir", "storage")),
        )
    if action == "release_article_pool_by_settings":
        return release_pool_by_settings(
            force=bool(payload.get("force", False)),
            storage_dir=str(payload.get("storage_dir", "storage")),
        )
    if action == "send_article_notification":
        return send_article_notification(
            str(payload["pub_id"]),
            force_send=bool(payload.get("force_send", False)),
            storage_dir=str(payload.get("storage_dir", "storage")),
        )
    if action == "send_daily_digest":
        return send_daily_digest(
            target_date=str(payload["target_date"]) if payload.get("target_date") else None,
            force_send=bool(payload.get("force_send", False)),
            storage_dir=str(payload.get("storage_dir", "storage")),
        )
    if action == "unpublish_article":
        result = unpublish_article(
            str(payload["pub_id"]),
            storage_dir=str(payload.get("storage_dir", "storage")),
        )
        if not result.get("found"):
            raise RuntimeError(f"Publication not found: {payload['pub_id']}")
        return result
    if action == "cleanup_test_post":
        result = cleanup_test_post(
            str(payload["pub_id"]),
            hard_delete=bool(payload.get("hard_delete", False)),
            storage_dir=str(payload.get("storage_dir", "storage")),
        )
        if not result.get("found"):
            raise RuntimeError(f"Publication not found: {payload['pub_id']}")
        return result
    if action == "sync_all":
        return sync_all(storage_dir=str(payload.get("storage_dir", "storage")))
    if action == "daily_update":
        return _json_safe(run_daily_update())
    if action == "recalc_metrics":
        return _json_safe(run_recalc_metrics())
    if action == "strategy_upsert":
        success = upsert_strategy_metadata(
            strategy_key=str(payload["strategy_key"]),
            strategy_name=str(payload["strategy_name"]),
            weights=dict(payload.get("weights") or {}),
            display_order=int(payload.get("display_order", 0)),
            is_active=bool(payload.get("is_active", True)),
            howto=payload.get("howto"),
            description=payload.get("description"),
            color=payload.get("color"),
            articles=list(payload.get("articles") or []),
            vix_level=payload.get("vix_level"),
            sigma_ann=payload.get("sigma_ann"),
        )
        if not success:
            raise RuntimeError(f"Failed to upsert strategy: {payload['strategy_key']}")
        return {"success": True, "strategy_key": payload["strategy_key"]}
    if action == "strategy_set_active":
        identifier = str(payload["identifier"])
        active = bool(payload.get("active", True))
        success = activate_strategy(identifier) if active else deactivate_strategy(identifier)
        if not success:
            raise RuntimeError(f"Failed to update strategy active state: {identifier}")
        return {"identifier": identifier, "active": active, "success": True}
    if action == "question_answer":
        result = answer_internal_question(
            str(payload["question_id"]),
            str(payload["answer"]),
            storage_dir=str(payload.get("storage_dir", "storage")),
            article_id=payload.get("article_id"),
        )
        if not result.get("found"):
            raise RuntimeError(f"Question not found: {payload['question_id']}")
        return result
    if action == "question_rerank":
        evaluations = payload.get("evaluations")
        if not isinstance(evaluations, list):
            raise RuntimeError("question_rerank requires payload.evaluations[]")
        return rerank_member_questions(
            evaluations,
            source=str(payload.get("source", "user")),
        )
    if action == "question_ranking_summary":
        return get_member_question_ranking_summary(
            source=str(payload.get("source", "user")),
            limit=int(payload.get("limit", 20)),
        )
    if action == "question_ranking_workflow":
        return build_question_rerank_workflow(
            source=str(payload.get("source", "user")),
            limit=int(payload.get("limit", 20)),
            storage_dir=str(payload.get("storage_dir", "storage")),
            write_latest=bool(payload.get("write_latest", False)),
        )
    if action == "platform_cycle_summary":
        return build_platform_cycle_summary(
            storage_dir=str(payload.get("storage_dir", "storage")),
            source=str(payload.get("source", "user")),
            limit=int(payload.get("limit", 20)),
            write_latest=bool(payload.get("write_latest", False)),
        )
    if action == "health_check":
        return health_snapshot(storage_dir=str(payload.get("storage_dir", "storage")))
    if action == "paper_upsert":
        return upsert_paper_metadata(
            paper_id=str(payload["paper_id"]),
            title=str(payload["title"]),
            authors=str(payload["authors"]),
            abstract=str(payload["abstract"]) if payload.get("abstract") is not None else None,
            status=str(payload.get("status", "working")),
            target_journal=str(payload["target_journal"]) if payload.get("target_journal") else None,
            pdf_url=str(payload["pdf_url"]) if payload.get("pdf_url") else None,
            pages=int(payload["pages"]) if payload.get("pages") is not None else None,
            figures=int(payload["figures"]) if payload.get("figures") is not None else None,
            tables=int(payload["tables"]) if payload.get("tables") is not None else None,
            citations=int(payload["citations"]) if payload.get("citations") is not None else None,
            score=float(payload["score"]) if payload.get("score") is not None else None,
            tags=list(payload.get("tags") or []),
            display_order=int(payload.get("display_order", 0)),
            storage_bucket=str(payload["storage_bucket"]) if payload.get("storage_bucket") else None,
            storage_path=str(payload["storage_path"]) if payload.get("storage_path") else None,
        )
    if action == "paper_upload_pdf":
        return upload_paper_pdf(
            paper_id=str(payload["paper_id"]),
            file_path=str(payload["file_path"]),
            bucket=str(payload.get("bucket", "papers")),
            file_name=str(payload["file_name"]) if payload.get("file_name") else None,
        )
    if action == "paper_migrate_storage":
        return migrate_paper_pdf_to_storage(
            paper_id=str(payload["paper_id"]),
            file_path=str(payload["file_path"]) if payload.get("file_path") else None,
        )

    raise ValueError(f"Unsupported ops job action: {action}")


def execute_job(job: dict[str, Any], worker_id: str | None = None) -> dict[str, Any]:
    worker = worker_id or str(job.get("worker_id") or _default_worker_id())
    payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}
    dry_run = bool(job.get("dry_run"))
    append_job_log(job["id"], "info", "Worker started job", {"worker_id": worker})

    try:
        if dry_run:
            result = {
                "dry_run": True,
                "action": job["action"],
                "payload": _json_safe(payload),
            }
        else:
            result = _json_safe(_run_action(str(job["action"]), payload))

        status = "succeeded"
        error = None
        append_job_log(job["id"], "info", "Job completed", {"worker_id": worker})
    except Exception as exc:  # pragma: no cover - defensive logging
        status = "failed"
        error = "".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)
        ).strip()
        result = {"message": str(exc)}
        append_job_log(
            job["id"],
            "error",
            "Job failed",
            {"worker_id": worker, "error": error},
        )

    finished_at = _utc_now()
    _patch_where(
        "ops_jobs",
        {"id": job["id"]},
        {
            "status": status,
            "worker_id": worker,
            "result": result,
            "error": error,
            "finished_at": finished_at,
            "updated_at": finished_at,
        },
    )
    record_audit_log(
        action=str(job["action"]),
        source=str(job.get("source") or DEFAULT_SOURCE),
        actor=job.get("requested_by"),
        target_type="ops_job",
        target_id=job["id"],
        status=status,
        payload=payload,
        result=result,
        error=error,
    )
    refreshed = get_job(job["id"])
    return refreshed or {**job, "status": status, "result": result, "error": error}


def work_once(scope: JobScope = DEFAULT_SCOPE, worker_id: str | None = None) -> dict[str, Any] | None:
    worker = worker_id or _default_worker_id()
    job = claim_next_job(scope=scope, worker_id=worker)
    if not job:
        return None
    return execute_job(job, worker_id=worker)


def work_loop(
    *,
    scope: JobScope = DEFAULT_SCOPE,
    worker_id: str | None = None,
    poll_interval: float = 10.0,
    once: bool = False,
    max_jobs: int | None = None,
) -> int:
    worker = worker_id or _default_worker_id()
    processed = 0

    while True:
        result = work_once(scope=scope, worker_id=worker)
        if result is not None:
            processed += 1
            if max_jobs is not None and processed >= max_jobs:
                return processed
            if once:
                return processed
            continue

        if once:
            return processed
        time.sleep(max(poll_interval, 0.5))
