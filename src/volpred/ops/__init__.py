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
    fail_task,
    get_agent_session,
    get_task as get_local_task,
    heartbeat_agent,
    list_agent_sessions,
    list_tasks as list_local_tasks,
    reject_task,
)
from .papers import get_paper, list_papers, migrate_paper_pdf_to_storage, upload_paper_pdf, upsert_paper_metadata
from .rollback import create_rollback_point, list_rollback_points, restore_rollback_point
from .schedules import build_schedule_report
from .shared_lock import shared_state_lock
from .agent_spec import check_agent_specs, import_agent_specs, render_agent_specs
from .jobs import SUPPORTED_ACTIONS, enqueue_job, get_job, list_jobs, work_loop, work_once
from .questions import (
    answer_internal_question,
    build_question_rerank_workflow,
    claim_question_for_research,
    get_member_question_ranking_summary,
    rerank_member_questions,
)
from .strategies import activate_strategy, deactivate_strategy, upsert_strategy_metadata
from .sync import run_daily_update, run_recalc_metrics, sync_all

__all__ = [
    "activate_strategy",
    "admin_override_claim",
    "adopt_experiment_files",
    "answer_internal_question",
    "build_question_rerank_workflow",
    "claim_question_for_research",
    "build_platform_cycle_summary",
    "build_schedule_report",
    "build_control_plane_snapshot",
    "build_experiment_migration_plan",
    "build_experiments_report",
    "build_hygiene_report",
    "check_agent_specs",
    "claim_next_task",
    "cleanup_test_post",
    "complete_task",
    "create_rollback_point",
    "create_task",
    "deactivate_strategy",
    "ensure_article_local_backups",
    "enqueue_job",
    "fail_task",
    "get_agent_session",
    "get_local_task",
    "get_member_question_ranking_summary",
    "get_content_release_settings",
    "get_job",
    "health_snapshot",
    "heartbeat_agent",
    "infer_experiment_id",
    "import_agent_specs",
    "list_agent_sessions",
    "get_paper",
    "list_jobs",
    "list_local_tasks",
    "list_papers",
    "list_rollback_points",
    "migrate_paper_pdf_to_storage",
    "preview_release_pool_by_settings",
    "publish_milestone_article",
    "reject_task",
    "release_pool_articles",
    "release_pool_by_settings",
    "render_agent_specs",
    "restore_rollback_point",
    "migrate_experiment_files",
    "scaffold_experiment",
    "send_article_notification",
    "shared_state_lock",
    "send_daily_digest",
    "rerank_member_questions",
    "run_daily_update",
    "run_recalc_metrics",
    "SUPPORTED_ACTIONS",
    "sync_all",
    "unpublish_article",
    "upload_paper_pdf",
    "upsert_paper_metadata",
    "upsert_strategy_metadata",
    "work_loop",
    "work_once",
]
