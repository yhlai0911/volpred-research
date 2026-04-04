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
    edit_article,
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
from .papers import get_paper, list_papers, migrate_paper_pdf_to_storage, upload_paper_pdf, upsert_paper_metadata
from .jobs import SUPPORTED_ACTIONS, enqueue_job, get_job, list_jobs, work_loop, work_once
from .questions import (
    answer_internal_question,
    build_question_rerank_workflow,
    get_member_question_ranking_summary,
    rerank_member_questions,
)
from .strategies import activate_strategy, deactivate_strategy, upsert_strategy_metadata
from .sync import run_daily_update, run_recalc_metrics, sync_all

__all__ = [
    "activate_strategy",
    "answer_internal_question",
    "build_question_rerank_workflow",
    "build_platform_cycle_summary",
    "cleanup_test_post",
    "deactivate_strategy",
    "ensure_article_local_backups",
    "enqueue_job",
    "get_member_question_ranking_summary",
    "get_content_release_settings",
    "get_job",
    "health_snapshot",
    "get_paper",
    "list_jobs",
    "list_papers",
    "migrate_paper_pdf_to_storage",
    "preview_release_pool_by_settings",
    "publish_milestone_article",
    "release_pool_articles",
    "release_pool_by_settings",
    "send_article_notification",
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
