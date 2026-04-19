# Ensure project root is on sys.path so that top-level `scripts.*` imports
# in submodules (content, jobs, questions, etc.) resolve correctly.
# This MUST run before any submodule import.
import sys as _sys
from pathlib import Path as _Path

_PROJECT_ROOT = str(_Path(__file__).resolve().parents[3])
if _PROJECT_ROOT not in _sys.path:
    _sys.path.insert(0, _PROJECT_ROOT)
del _sys, _Path, _PROJECT_ROOT

from .content import (
    build_platform_cycle_summary,
    cleanup_test_post,
    ensure_article_local_backups,
    get_content_release_settings,
    publish_milestone_article,
    preview_release_pool_by_settings,
    release_pool_articles,
    release_pool_by_settings,
    send_article_notification,
    send_daily_digest,
    unpublish_article,
)
from .alerts import (
    ALERT_RECIPIENT,
    build_alert_condition_report,
    check_alert_conditions,
    send_alert,
)
from .health import health_snapshot
from .experiments import (
    adopt_experiment_files,
    build_experiment_migration_plan,
    build_experiments_report,
    infer_experiment_id,
    migrate_experiment_files,
    scaffold_experiment,
)
from .hygiene import build_hygiene_report
from .local_control_plane import (
    admin_override_claim,
    approve_task,
    build_control_plane_snapshot,
    claim_next_task,
    complete_task,
    create_task,
    curate_task,
    fail_task,
    get_agent_session,
    get_agent_session_by_session_key,
    get_task as get_local_task,
    heartbeat_agent,
    is_schedule_governance_task,
    list_agent_sessions,
    list_pending_curations,
    list_tasks as list_local_tasks,
    requeue_task,
    reject_task,
    resolve_session_key,
    task_governance_area,
)
from .papers import get_paper, list_papers, migrate_paper_pdf_to_storage, upload_paper_pdf, upsert_paper_metadata
from .rollback import create_rollback_point, list_rollback_points, restore_rollback_point
from .schedules import build_schedule_report
from .shared_lock import shared_state_lock
from .agent_spec import check_agent_specs, import_agent_specs, render_agent_specs, sync_agent_specs
from .session import session_bootstrap, session_finish_task, session_next_task, session_shutdown
from .jobs import SUPPORTED_ACTIONS, enqueue_job, get_job, list_jobs, work_loop, work_once
from .event_jobs import expand_due_event_jobs, gc_event_ledger, preview_event_jobs
from .execution_brief import (
    build_execution_brief,
    ensure_execution_brief,
    preflight_executor_task,
    preview_execution_brief,
    run_executor_task,
    set_execution_brief,
    task_brief_is_ready,
    task_brief_is_stale,
    task_preconditions_met,
    task_requires_coordinator,
    task_unmet_preconditions,
)
from .smoke import run_scheduler_live_smoke, run_scheduler_smoke
from .scheduler import get_scheduler_state, scheduler_preview, scheduler_tick
from .questions import (
    answer_internal_question,
    build_question_rerank_workflow,
    claim_question_for_research,
    get_member_question_ranking_summary,
    rerank_member_questions,
)
from .strategies import activate_strategy, deactivate_strategy, upsert_strategy_metadata
from .sync import run_daily_update, run_recalc_metrics, sync_all
from .supervisor import build_supervisor_snapshot, load_supervisor_rules
from .autotune import autotune_supervisor_rules

__all__ = [
    "ALERT_RECIPIENT",
    "activate_strategy",
    "admin_override_claim",
    "adopt_experiment_files",
    "autotune_supervisor_rules",
    "build_alert_condition_report",
    "build_supervisor_snapshot",
    "load_supervisor_rules",
    "answer_internal_question",
    "build_question_rerank_workflow",
    "check_alert_conditions",
    "claim_question_for_research",
    "build_platform_cycle_summary",
    "build_schedule_report",
    "build_control_plane_snapshot",
    "build_execution_brief",
    "build_experiment_migration_plan",
    "build_experiments_report",
    "build_hygiene_report",
    "check_agent_specs",
    "claim_next_task",
    "cleanup_test_post",
    "complete_task",
    "create_rollback_point",
    "create_task",
    "curate_task",
    "deactivate_strategy",
    "ensure_execution_brief",
    "ensure_article_local_backups",
    "enqueue_job",
    "expand_due_event_jobs",
    "fail_task",
    "get_agent_session",
    "get_agent_session_by_session_key",
    "get_local_task",
    "get_member_question_ranking_summary",
    "get_content_release_settings",
    "get_job",
    "health_snapshot",
    "heartbeat_agent",
    "infer_experiment_id",
    "import_agent_specs",
    "is_schedule_governance_task",
    "list_agent_sessions",
    "list_pending_curations",
    "get_paper",
    "gc_event_ledger",
    "list_jobs",
    "list_local_tasks",
    "list_papers",
    "list_rollback_points",
    "migrate_paper_pdf_to_storage",
    "preview_release_pool_by_settings",
    "publish_milestone_article",
    "preflight_executor_task",
    "preview_execution_brief",
    "preview_event_jobs",
    "reject_task",
    "requeue_task",
    "resolve_session_key",
    "release_pool_articles",
    "release_pool_by_settings",
    "render_agent_specs",
    "run_executor_task",
    "run_scheduler_live_smoke",
    "run_scheduler_smoke",
    "session_bootstrap",
    "session_finish_task",
    "session_next_task",
    "session_shutdown",
    "scheduler_preview",
    "get_scheduler_state",
    "scheduler_tick",
    "restore_rollback_point",
    "migrate_experiment_files",
    "scaffold_experiment",
    "send_article_notification",
    "send_alert",
    "shared_state_lock",
    "send_daily_digest",
    "rerank_member_questions",
    "run_daily_update",
    "run_recalc_metrics",
    "SUPPORTED_ACTIONS",
    "set_execution_brief",
    "sync_all",
    "sync_agent_specs",
    "task_brief_is_ready",
    "task_brief_is_stale",
    "task_governance_area",
    "task_preconditions_met",
    "task_requires_coordinator",
    "task_unmet_preconditions",
    "unpublish_article",
    "upload_paper_pdf",
    "upsert_paper_metadata",
    "upsert_strategy_metadata",
    "work_loop",
    "work_once",
]
