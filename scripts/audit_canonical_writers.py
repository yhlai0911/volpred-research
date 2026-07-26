#!/usr/bin/env python3
"""Inventory and ratchet direct mutations of canonical ``storage/`` state.

``VOLPRED_NO_CANONICAL_WRITE`` is only useful when every canonical writer reaches
the one structural guard, :func:`volpred.canonical_write.guard_canonical_write`.
This audit supplies the mechanical backstop: it scans active Python under
``src/volpred``, ``src/api`` and ``scripts`` for storage-derived write operations,
prints every operation with its source line, and rejects an operation that is
not both guarded in its owning scope and part of the frozen low-level-owner
inventory below.

The inventory is deliberately a *counted* ratchet.  The human-readable table
below is the complete set of low-level owners.  An owner must call the guard
before mutating; a guarded mutation outside an owner is still rejected because
it creates a second write path.  Counts changing in either direction fail.

Usage::

    uv run python scripts/audit_canonical_writers.py
    uv run python scripts/audit_canonical_writers.py --root /candidate/tree --json
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Iterator, Mapping


ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOTS = ("src/volpred", "src/api", "scripts")
SKIP_PARTS = {"__pycache__", "tests", "_legacy", "experiments"}

# This is the canonical surface formerly fingerprinted by tests/conftest.py,
# plus dispatch_state (already writer-guarded because a live daemon mutates it).
# Research results, charts, caches and immutable experiment artifacts are not
# shared mutable control state and are intentionally outside this audit.
CANONICAL_TARGETS: tuple[tuple[str, ...], ...] = (
    ("storage", "publication_candidates.json"),
    ("storage", "next_tasks.json"),
    ("storage", "work_log.json"),
    ("storage", "reports", "feed.json"),
    ("storage", "memory", "knowledge.json"),
    ("storage", "memory", "thinking_journal.json"),
    ("storage", "memory", "experiment_experiences.json"),
    ("storage", "ops", "event_ledger"),
    ("storage", "ops", "tasks"),
    ("storage", "ops", "dispatch_state.json"),
    ("storage", "ops", "cron_last_run.json"),
)

# Human-readable canonical writer ownership. Values are the exact operation
# multiset expected in that scope; this is a ratchet, not an exemption. Every
# listed call must also have an earlier guard_canonical_write in the same scope.
# Filled from the audited tree after the owner refactor; changes require review.
LOW_LEVEL_OWNERS: Mapping[str, Mapping[str, int]] = {
    "scripts/append_work_log.py:append_entries": {
        "mkdir": 1, "open-write": 1, "os.replace": 1, "unlink": 1,
    },
    "scripts/backfill_feed_audience.py:_atomic_write_feed": {
        "os.replace": 1, "write_text": 1,
    },
    "scripts/backfill_feed_audience.py:reconcile_rewrite_tasks": {
        "mkdir": 1, "open-write": 1, "write_text": 1,
    },
    "scripts/backfill_arc_dedup_metadata.py:_write_json_atomic": {
        "os.replace": 1, "unlink": 1, "write_text": 1,
    },
    "scripts/backfill_null_task_ids.py:main": {"open-write": 1},
    "scripts/backfill_verified_live.py:main": {"replace": 1, "write_text": 1},
    "scripts/build_publication_candidates.py:_write_output_atomically": {
        "os.replace": 1, "write_text": 1,
    },
    # scripts/check_alerts.py:_append_next_task_locked was a direct flock writer
    # until 2026-07-21 (dispatch-lanes absorb): it now delegates to the
    # append_task_record gateway and owns no direct mutation.
    "scripts/check_alerts.py:_ci_close_pending_repair_tasks": {"open-write": 1},
    "scripts/check_alerts.py:_record_release_pool_fallback_fire": {
        "mkdir": 1, "write_text": 1,
    },
    "scripts/continue_task_dispatch.py:_materialize_pool_dry_diagnostic_task": {
        "mkdir": 1, "open-write": 1, "write_text": 1,
    },
    "scripts/continue_task_dispatch.py:_promote_starved_article_tasks": {"open-write": 1},
    "scripts/continue_task_dispatch.py:_sweep_cleared_dreaming_tasks": {"open-write": 1},
    "scripts/cron_mark_last_run.py:_atomic_write": {
        "mkdir": 1, "os.replace": 1, "unlink": 1,
    },
    "scripts/cron_mark_last_run.py:merge_last_run": {
        "mkdir": 1, "open-write": 1,
    },
    "scripts/daily_update.py:main": {"write_text": 1},
    "scripts/dedupe_next_tasks.py:main": {"open-write": 1},
    "scripts/dispatch_supervisor/state.py:_atomic_write_json": {"os.replace": 1, "unlink": 1},
    "scripts/dispatch_supervisor/state.py:_locked_state": {"mkdir": 1},
    "scripts/dreaming_review.py:apply_auto_dispatch": {
        "mkdir": 1, "open-write": 1, "write_text": 1,
    },
    "scripts/extract_base64_images.py:main": {"write_text": 1},
    "scripts/fb_page_post.py:_mark_success": {"write_text": 1},
    "scripts/mark_fb_post_status.py:_write_json": {"write_text": 1},
    "scripts/merge_feed_files.py:<module>": {"open-write": 2},
    "scripts/migrate_fb_post_status_single_source.py:main": {"write_text": 1},
    "scripts/reap_orphan_deliverables.py:_close_resolved_escalations": {
        "open-write": 1,
    },
    # scripts/publish_draft.py:apply_update was a canonical feed writer until
    # WS-C1 (2026-07-20): --update now routes through
    # Publisher.rewrite_and_sync_article, so the script owns no feed mutation.
    "scripts/record_and_publish.py:record_and_publish": {"write_text": 1},
    "scripts/series_registry.py:apply": {"write_text": 1},
    "scripts/slim_feed_description.py:main": {"write_text": 1},
    "scripts/sync_next_tasks_status.py:main": {"open-write": 1},
    "scripts/task_pool_claim.py:_locked_load": {
        "mkdir": 1, "open-write": 1, "write_text": 1,
    },
    "scripts/unblock_expired_blocked_tasks.py:main": {"open-write": 1},
    "src/volpred/memory/system.py:MemorySystem._append_to_index": {
        "open-write": 1, "replace": 1,
    },
    "src/volpred/ops/alert_remediation.py:_enqueue": {
        "mkdir": 1, "open-write": 1, "write_text": 1,
    },
    "src/volpred/ops/alert_remediation.py:_close_cleared_task": {
        "open-write": 1,
    },
    "src/volpred/ops/alert_remediation.py:_sweep_cleared_ordinary_tasks": {
        "open-write": 1,
    },
    "src/api/routers/mirror.py:append_memory_file": {
        "mkdir": 1, "replace": 1, "write_bytes": 1,
    },
    "src/api/routers/mirror.py:put_memory_file": {
        "mkdir": 1, "replace": 1, "write_bytes": 1,
    },
    "src/volpred/ops/common.py:dump_json": {"mkdir": 1, "write_text": 1},
    "src/volpred/ops/content.py:_materialize_release_audit_fix_task": {
        "mkdir": 1, "open-write": 1, "write_text": 1,
    },
    "src/volpred/ops/content.py:_write_feed_locked": {
        "mkdir": 1, "replace": 1, "unlink": 1, "write_text": 1,
    },
    "src/volpred/ops/event_jobs.py:_event_ledger_root": {"mkdir": 1},
    "src/volpred/ops/event_jobs.py:_ensure_next_task": {"mkdir": 1, "open-write": 1},
    "src/volpred/ops/event_jobs.py:_expire_next_tasks": {"open-write": 1},
    "src/volpred/ops/event_jobs.py:_suppress_canonical_for_legacy_conflict": {
        "open-write": 1,
    },
    "src/volpred/ops/event_jobs.py:_write_json": {
        "mkdir": 1, "os.replace": 1, "unlink": 1, "write_text": 1,
    },
    "src/volpred/ops/event_jobs.py:gc_event_ledger": {"unlink": 1},
    "src/volpred/ops/feed_sync.py:reconcile_content_from_singles": {"write_text": 1},
    "src/volpred/ops/foreign_incident.py:reconcile_incidents": {"open-write": 1},
    "src/volpred/ops/local_control_plane.py:_atomic_write_json": {
        "mkdir": 1, "replace": 1, "write_text": 1,
    },
    "src/volpred/ops/local_control_plane.py:_plane_lock": {"open-write": 1},
    "src/volpred/ops/local_control_plane.py:ensure_control_plane_dirs": {
        "mkdir": 2, "touch": 1,
    },
    "src/volpred/ops/next_tasks.py:write_tasks_locked": {
        "mkdir": 1, "open-write": 1, "write_text": 1,
    },
    "src/volpred/ops/next_tasks.py:write_tasks_to_handle": {
        "truncate": 1, "write": 2,
    },
    "src/volpred/ops/questions.py:_ensure_article_question_metadata": {"write_text": 1},
    "src/volpred/ops/questions.py:ensure_member_qa_task": {
        "mkdir": 1, "open-write": 1, "write_text": 1,
    },
    "src/volpred/ops/retraction.py:_write_feed_atomic": {
        "os.replace": 1, "unlink": 1, "write_text": 1,
    },
    "src/volpred/publisher/lazypack_install.py:install_lazypack_section": {"write_text": 1},
    "src/volpred/publisher/publisher.py:Publisher._append_to_feed": {
        "open-write": 1, "replace": 1,
    },
    "src/volpred/publisher/publisher.py:Publisher._rewrite_feed_entry": {
        "open-write": 1, "replace": 1, "unlink": 1,
    },
    "src/volpred/publisher/publisher.py:Publisher.unpublish": {"open-write": 1},
}

# True low-level primitives and dynamic-path entrypoints whose target cannot be
# reduced to one literal path inside their own body. Only mutations whose target
# depends on one of these names are inventoried; declaring an owner no longer
# turns every unrelated write in a broad ``main()`` into canonical state.
GENERIC_OWNER_TARGETS: Mapping[str, frozenset[str]] = {
    "scripts/append_work_log.py:append_entries": frozenset({"path", "lock_path"}),
    "scripts/backfill_feed_audience.py:_atomic_write_feed": frozenset({"path", "tmp"}),
    "scripts/backfill_feed_audience.py:reconcile_rewrite_tasks": frozenset(
        {"tasks_path"}
    ),
    "scripts/backfill_arc_dedup_metadata.py:_write_json_atomic": frozenset({"path"}),
    "scripts/check_alerts.py:_ci_close_pending_repair_tasks": frozenset(
        {"next_tasks_path"}
    ),
    "scripts/cron_mark_last_run.py:_atomic_write": frozenset({"path", "tmp"}),
    "scripts/cron_mark_last_run.py:merge_last_run": frozenset(
        {"path", "lock_path"}
    ),
    "scripts/dispatch_supervisor/state.py:_atomic_write_json": frozenset({"path"}),
    "scripts/dispatch_supervisor/state.py:_locked_state": frozenset({"path"}),
    "scripts/extract_base64_images.py:main": frozenset({"feed_path"}),
    "scripts/mark_fb_post_status.py:_write_json": frozenset({"path"}),
    "scripts/slim_feed_description.py:main": frozenset({"feed_path"}),
    "src/api/routers/mirror.py:append_memory_file": frozenset({"path"}),
    "src/api/routers/mirror.py:put_memory_file": frozenset({"path"}),
    "src/volpred/memory/system.py:MemorySystem._append_to_index": frozenset(
        {"filepath"}
    ),
    "src/volpred/ops/alert_remediation.py:_enqueue": frozenset({"path"}),
    "src/volpred/ops/common.py:dump_json": frozenset({"path"}),
    "src/volpred/ops/event_jobs.py:_write_json": frozenset({"path"}),
    "src/volpred/ops/event_jobs.py:gc_event_ledger": frozenset({"path"}),
    "src/volpred/ops/local_control_plane.py:_atomic_write_json": frozenset({"path"}),
    "src/volpred/ops/local_control_plane.py:_plane_lock": frozenset({"paths"}),
    "src/volpred/ops/local_control_plane.py:ensure_control_plane_dirs": frozenset(
        {"path"}
    ),
    "src/volpred/ops/next_tasks.py:write_tasks_locked": frozenset({"p", "path"}),
    "src/volpred/ops/next_tasks.py:write_tasks_to_handle": frozenset(
        {"fh", "handle_name"}
    ),
    "src/volpred/ops/retraction.py:_write_feed_atomic": frozenset({"path", "tmp"}),
}

HANDLE_ONLY_OWNERS = {"src/volpred/ops/next_tasks.py:write_tasks_to_handle"}

# --- WS-A1 next_tasks helper-routing gate (2026-07-20) -----------------------
# The owner ratchet above answers "is this mutation registered?"; it does NOT
# answer "does the registered writer actually serialize through the canonical
# helper?" (docs/audit_next_tasks_writers.md gap note). This gate closes that:
# outside NEXT_TASKS_MODULE, a scope touching storage/next_tasks.json may only
# (a) mkdir its parent, (b) bootstrap-write a literal "[]", (c) open it "r+" —
# and it MUST call one of the canonical helpers to land bytes. Full-payload
# write_text / json.dump / handle truncate+write / tmp+replace are rejected.
NEXT_TASKS_TARGET: tuple[str, ...] = ("storage", "next_tasks.json")
NEXT_TASKS_MODULE = "src/volpred/ops/next_tasks.py"
NEXT_TASKS_HELPERS = frozenset(
    {
        "write_tasks_to_handle", "write_tasks_locked", "append_next_task",
        "append_task_record", "backfill_ci_repair_commit",
    }
)
NEXT_TASKS_BOOTSTRAP_LITERALS = frozenset({"[]", "[]\n"})
# Frozen ratchet (may only SHRINK) mirroring test_work_log_writer_gate.py's
# BASELINE: archived one-shot experiment scripts are evidence of what was
# actually executed (research-honesty) and are not on any scheduled path, so
# they are not rewritten — but the class must not grow.
NEXT_TASKS_EXPERIMENT_BASELINE = frozenset({"experiments/K1387/write_knowledge.py"})
# Doc lines that WRITE into next_tasks.json via shell (the jq-then-mv shape the
# retired cron_hourly_dispatch_prompt.md instruction taught to agents).
NEXT_TASKS_DOC_MUTATION_PATTERNS = (
    r"\bmv\s+\S+\s+\S*next_tasks\.json",
    r"\b(?:tee|sponge)\s+(?:-a\s+)?\S*next_tasks\.json",
    r">\s*\S*next_tasks\.json",
)

PATH_MUTATORS = {
    "mkdir",
    "rename",
    "replace",
    "rmdir",
    "touch",
    "unlink",
    "write_bytes",
    "write_text",
}
OWNER_HANDLE_MUTATORS = {"truncate", "write"}
OS_MUTATORS = {"remove", "removedirs", "rename", "renames", "replace", "unlink"}
SHUTIL_DEST_MUTATORS = {"copy", "copy2", "copyfile", "copytree", "move"}
WRITE_MODES = {"a", "w", "x", "+"}


@dataclass(frozen=True)
class Mutation:
    path: str
    line: int
    scope: str
    operation: str
    guarded: bool
    declared_owner: bool

    @property
    def owner(self) -> str:
        return f"{self.path}:{self.scope}"

    @property
    def classification(self) -> str:
        if self.declared_owner and self.guarded:
            return "guarded-owner"
        if self.declared_owner:
            return "owner-missing-guard"
        if self.guarded:
            return "direct-guarded-bypass"
        return "unguarded-direct"


@dataclass(frozen=True)
class AuditResult:
    inventory: tuple[Mutation, ...]
    violations: tuple[Mutation, ...]
    owner_count_mismatches: tuple[str, ...]
    parse_errors: tuple[str, ...]
    helper_routing_violations: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not (
            self.violations
            or self.owner_count_mismatches
            or self.parse_errors
            or self.helper_routing_violations
        )


def _iter_python_files(root: Path) -> Iterator[Path]:
    # In a checkout, audit the candidate's tracked surface only. This both
    # matches what CI receives and prevents local scratch/untracked work from
    # silently enlarging or satisfying the owner inventory.
    if (root / ".git").exists():
        proc = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--", *SCAN_ROOTS],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0:
            for rel in sorted(line for line in proc.stdout.splitlines() if line.endswith(".py")):
                path = root / rel
                relative_parts = Path(rel).parts
                if any(part in SKIP_PARTS for part in relative_parts[:-1]):
                    continue
                if path.is_file():
                    yield path
            return
    for rel in SCAN_ROOTS:
        base = root / rel
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.py")):
            relative_parts = path.relative_to(base).parts[:-1]
            if any(part in SKIP_PARTS for part in relative_parts):
                continue
            yield path


def _scope_nodes(tree: ast.AST) -> Iterator[tuple[ast.AST, str]]:
    """Yield module/functions without treating nested-function bodies as parent code."""

    yield tree, "<module>"

    def visit(node: ast.AST, prefix: tuple[str, ...]) -> Iterator[tuple[ast.AST, str]]:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                yield from visit(child, (*prefix, child.name))
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qualified = (*prefix, child.name)
                yield child, ".".join(qualified)
                yield from visit(child, qualified)

    yield from visit(tree, ())


def _nodes_in_scope(scope: ast.AST) -> Iterator[ast.AST]:
    """Walk one lexical scope, excluding nested class/function bodies."""

    stack: list[ast.AST] = list(reversed(list(ast.iter_child_nodes(scope))))
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        yield node
        stack.extend(reversed(list(ast.iter_child_nodes(node))))


def _assignment_names(target: ast.AST) -> Iterator[str]:
    if isinstance(target, ast.Name):
        yield target.id
    elif isinstance(target, ast.Attribute):
        qualified = _qualified_name(target)
        if qualified:
            yield qualified
    elif isinstance(target, (ast.Tuple, ast.List)):
        for item in target.elts:
            yield from _assignment_names(item)


def _assignments(scope: ast.AST) -> dict[str, list[ast.AST]]:
    values: dict[str, list[ast.AST]] = {}
    for node in _nodes_in_scope(scope):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                for name in _assignment_names(target):
                    values.setdefault(name, []).append(node.value)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            for name in _assignment_names(node.target):
                values.setdefault(name, []).append(node.value)
        elif isinstance(node, ast.NamedExpr):
            for name in _assignment_names(node.target):
                values.setdefault(name, []).append(node.value)
    return values


def _function_returns(tree: ast.AST) -> dict[str, list[ast.AST]]:
    """Collect return expressions for local path-builder helpers."""

    parents = {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }
    returns: dict[str, list[ast.AST]] = {}
    for function in ast.walk(tree):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        values: list[ast.AST] = []
        for node in ast.walk(function):
            if not isinstance(node, ast.Return) or node.value is None:
                continue
            current = parents.get(node)
            while current is not None and not isinstance(
                current, (ast.FunctionDef, ast.AsyncFunctionDef)
            ):
                current = parents.get(current)
            if current is function:
                values.append(node.value)
        likely_path_helper = any(
            token in function.name.lower() for token in ("path", "root", "dir")
        )
        path_values = [
            value
            for value in values
            if likely_path_helper
            or (isinstance(value, ast.BinOp) and isinstance(value.op, ast.Div))
            or (
                isinstance(value, ast.Call)
                and _qualified_name(value.func).rsplit(".", 1)[-1]
                in {"Path", "joinpath", "project_path", "storage_path", "with_name", "with_suffix"}
            )
        ]
        if path_values:
            returns.setdefault(function.name, []).extend(path_values)
    return returns


def _parameter_bindings(tree: ast.AST) -> dict[str, dict[str, list[ast.AST]]]:
    """Map local helper parameters to call-site arguments and defaults."""

    definitions = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    bindings: dict[str, dict[str, list[ast.AST]]] = {}
    for name, function in definitions.items():
        params = [*function.args.posonlyargs, *function.args.args]
        defaults = [None] * (len(params) - len(function.args.defaults)) + list(
            function.args.defaults
        )
        for parameter, default in zip(params, defaults):
            if default is not None:
                bindings.setdefault(name, {}).setdefault(parameter.arg, []).append(default)
    for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
        name = _qualified_name(call.func).rsplit(".", 1)[-1]
        function = definitions.get(name)
        if function is None:
            continue
        params = [*function.args.posonlyargs, *function.args.args]
        # A method call's implicit self/cls is not represented in call.args.
        offset = 1 if params and params[0].arg in {"self", "cls"} else 0
        for parameter, argument in zip(params[offset:], call.args):
            bindings.setdefault(name, {}).setdefault(parameter.arg, []).append(argument)
        by_keyword = {keyword.arg: keyword.value for keyword in call.keywords if keyword.arg}
        for parameter in params[offset:]:
            if parameter.arg in by_keyword:
                bindings.setdefault(name, {}).setdefault(parameter.arg, []).append(
                    by_keyword[parameter.arg]
                )
    return bindings


def _looks_like_storage_name(name: str) -> bool:
    compact = name.lower().strip("_")
    return compact == "storage" or compact.startswith("storage_") or compact.endswith("_storage")


def _literal_mentions_storage(value: object) -> bool:
    if not isinstance(value, str):
        return False
    normalized = value.replace("\\", "/")
    return "storage" in [part.lower() for part in normalized.split("/") if part]


def _is_path_builder(
    node: ast.AST,
    function_returns: Mapping[str, list[ast.AST]],
) -> bool:
    if isinstance(node, (ast.Name, ast.Attribute)):
        return True
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return True
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        value = node.value.replace("\\", "/")
        return "/" in value or value.endswith((".json", ".jsonl", ".tmp"))
    if isinstance(node, ast.Call):
        name = _qualified_name(node.func).rsplit(".", 1)[-1]
        return name in {
            "Path", "joinpath", "project_path", "resolve", "storage_path",
            "with_name", "with_suffix",
        } or name in function_returns
    return False


def _path_hints(
    node: ast.AST | None,
    assignments: Mapping[str, list[ast.AST]],
    module_assignments: Mapping[str, list[ast.AST]],
    *,
    function_returns: Mapping[str, list[ast.AST]] | None = None,
    seen: frozenset[str] = frozenset(),
) -> set[str]:
    function_returns = function_returns or {}
    if node is None:
        return set()
    if isinstance(node, ast.Constant):
        if not isinstance(node.value, str):
            return set()
        normalized = node.value.replace("\\", "/").lower()
        return {normalized, *(part for part in normalized.split("/") if part)}
    if isinstance(node, ast.Name):
        hints = {node.id.lower()}
        if _looks_like_storage_name(node.id):
            hints.add("storage")
        if node.id in seen:
            return hints
        next_seen = seen | {node.id}
        values = assignments.get(node.id, ()) or module_assignments.get(node.id, ())
        for value in values:
            if not _is_path_builder(value, function_returns):
                continue
            hints.update(
                _path_hints(
                    value,
                    assignments,
                    module_assignments,
                    function_returns=function_returns,
                    seen=next_seen,
                )
            )
        return hints
    if isinstance(node, ast.Attribute):
        qualified = _qualified_name(node)
        hints = {node.attr.lower(), qualified.lower()}
        if _looks_like_storage_name(node.attr):
            hints.add("storage")
        if qualified not in seen:
            next_seen = seen | {qualified}
            values = assignments.get(qualified, ()) or module_assignments.get(qualified, ())
            for value in values:
                if not _is_path_builder(value, function_returns):
                    continue
                hints.update(
                    _path_hints(
                        value,
                        assignments,
                        module_assignments,
                        function_returns=function_returns,
                        seen=next_seen,
                    )
                )
        hints.update(
            _path_hints(
                node.value,
                assignments,
                module_assignments,
                function_returns=function_returns,
                seen=seen,
            )
        )
        return hints
    if isinstance(node, ast.keyword):
        return _path_hints(
            node.value,
            assignments,
            module_assignments,
            function_returns=function_returns,
            seen=seen,
        )
    hints: set[str] = set()
    if isinstance(node, ast.Call):
        name = _qualified_name(node.func).rsplit(".", 1)[-1]
        call_key = f"call:{name}"
        if call_key not in seen:
            for value in function_returns.get(name, ()):
                hints.update(
                    _path_hints(
                        value,
                        assignments,
                        module_assignments,
                        function_returns=function_returns,
                        seen=seen | {call_key},
                    )
                )
    for child in ast.iter_child_nodes(node):
        hints.update(
            _path_hints(
                child,
                assignments,
                module_assignments,
                function_returns=function_returns,
                seen=seen,
            )
        )
    return hints


def _is_canonical_target(
    node: ast.AST | None,
    assignments: Mapping[str, list[ast.AST]],
    module_assignments: Mapping[str, list[ast.AST]],
    function_returns: Mapping[str, list[ast.AST]],
) -> bool:
    hints = _path_hints(
        node,
        assignments,
        module_assignments,
        function_returns=function_returns,
    )
    return any(all(component in hints for component in target) for target in CANONICAL_TARGETS)


def _qualified_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _qualified_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _mode_is_write(node: ast.AST | None) -> bool:
    if node is None:
        return False
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return any(marker in node.value for marker in WRITE_MODES)
    # A dynamic mode cannot be proved read-only, so fail closed.
    return True


def _open_mode(call: ast.Call, *, path_method: bool) -> ast.AST | None:
    positional_index = 0 if path_method else 1
    if len(call.args) > positional_index:
        return call.args[positional_index]
    for keyword in call.keywords:
        if keyword.arg == "mode":
            return keyword.value
    return None


def _mutation_target(call: ast.Call) -> tuple[str, ast.AST | None] | None:
    func = call.func
    qualified = _qualified_name(func)

    if (
        isinstance(func, ast.Attribute)
        and func.attr in PATH_MUTATORS
        and not qualified.startswith(("os.", "shutil."))
    ):
        if func.attr in {"rename", "replace"}:
            target = call.args[0] if call.args else func.value
        else:
            target = func.value
        return func.attr, target

    if isinstance(func, ast.Attribute) and func.attr in OWNER_HANDLE_MUTATORS:
        return func.attr, func.value

    if isinstance(func, ast.Attribute) and func.attr == "open":
        if _mode_is_write(_open_mode(call, path_method=True)):
            return "open-write", func.value
        return None

    if qualified in {"open", "builtins.open", "io.open"}:
        if not call.args:
            return None
        if _mode_is_write(_open_mode(call, path_method=False)):
            return "open-write", call.args[0]
        return None

    if qualified.startswith("os.") and qualified.rsplit(".", 1)[-1] in OS_MUTATORS:
        op = qualified.rsplit(".", 1)[-1]
        if not call.args:
            return None
        target_index = 1 if op in {"rename", "renames", "replace"} and len(call.args) > 1 else 0
        return qualified, call.args[target_index]

    if qualified.startswith("shutil.") and qualified.rsplit(".", 1)[-1] in SHUTIL_DEST_MUTATORS:
        if len(call.args) < 2:
            return None
        return qualified, call.args[1]

    if qualified == "shutil.rmtree" and call.args:
        return qualified, call.args[0]
    return None


def _looks_path_like(
    node: ast.AST,
    assignments: Mapping[str, list[ast.AST]],
    module_assignments: Mapping[str, list[ast.AST]],
    *,
    function_returns: Mapping[str, list[ast.AST]] | None = None,
    seen: frozenset[str] = frozenset(),
) -> bool:
    """Separate ``Path.replace``/``rename`` from ubiquitous string methods."""

    function_returns = function_returns or {}
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return True
    if isinstance(node, ast.Subscript):
        return _looks_path_like(
            node.value,
            assignments,
            module_assignments,
            function_returns=function_returns,
            seen=seen,
        )
    if isinstance(node, ast.Call):
        name = _qualified_name(node.func).rsplit(".", 1)[-1]
        if name in {"Path", "joinpath", "resolve", "with_name", "with_suffix"}:
            return True
        if name not in seen and any(
            _looks_path_like(
                value,
                assignments,
                module_assignments,
                function_returns=function_returns,
                seen=seen | {name},
            )
            for value in function_returns.get(name, ())
        ):
            return True
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        value = node.value.lower()
        return "/" in value or value.endswith((".json", ".jsonl", ".tmp"))

    names: list[str] = []
    if isinstance(node, ast.Name):
        names.append(node.id)
    elif isinstance(node, ast.Attribute):
        names.extend((_qualified_name(node), node.attr))
        if node.attr in {"parent", "parents"} and _looks_path_like(
            node.value,
            assignments,
            module_assignments,
            function_returns=function_returns,
            seen=seen,
        ):
            return True
    for name in names:
        qualified = _qualified_name(node) if isinstance(node, ast.Attribute) else name
        if qualified in seen:
            continue
        values = assignments.get(qualified, ()) or assignments.get(name, ())
        values = values or module_assignments.get(qualified, ()) or module_assignments.get(name, ())
        next_seen = seen | {qualified}
        if any(
            _looks_path_like(
                value,
                assignments,
                module_assignments,
                function_returns=function_returns,
                seen=next_seen,
            )
            for value in values
        ):
            return True
    return False


def _origin_aliases(
    node: ast.AST | None,
    assignments: Mapping[str, list[ast.AST]],
    module_assignments: Mapping[str, list[ast.AST]],
    function_returns: Mapping[str, list[ast.AST]],
    *,
    seen: frozenset[str] = frozenset(),
) -> set[str]:
    """Return variable/attribute origins without conflating shared ROOT literals."""

    if node is None:
        return set()
    if isinstance(node, ast.Name):
        aliases = {node.id}
        if node.id in seen:
            return aliases
        values = assignments.get(node.id, ()) or module_assignments.get(node.id, ())
        for value in values:
            aliases.update(
                _origin_aliases(
                    value,
                    assignments,
                    module_assignments,
                    function_returns,
                    seen=seen | {node.id},
                )
            )
        return aliases
    if isinstance(node, ast.Attribute):
        qualified = _qualified_name(node)
        aliases = {qualified}
        values = assignments.get(qualified, ()) or module_assignments.get(qualified, ())
        if qualified not in seen:
            for value in values:
                aliases.update(
                    _origin_aliases(
                        value,
                        assignments,
                        module_assignments,
                        function_returns,
                        seen=seen | {qualified},
                    )
                )
        if node.attr in {"parent", "parents"} or not values:
            aliases.update(
                _origin_aliases(
                    node.value,
                    assignments,
                    module_assignments,
                    function_returns,
                    seen=seen,
                )
            )
        return aliases
    if isinstance(node, ast.Call):
        aliases: set[str] = set()
        name = _qualified_name(node.func).rsplit(".", 1)[-1]
        call_key = f"call:{name}"
        if call_key not in seen:
            for value in function_returns.get(name, ()):
                aliases.update(
                    _origin_aliases(
                        value,
                        assignments,
                        module_assignments,
                        function_returns,
                        seen=seen | {call_key},
                    )
                )
        # Path constructors/transforms inherit their receiver/arguments.
        if isinstance(node.func, ast.Attribute):
            aliases.update(
                _origin_aliases(
                    node.func.value,
                    assignments,
                    module_assignments,
                    function_returns,
                    seen=seen,
                )
            )
        for arg in node.args:
            aliases.update(
                _origin_aliases(
                    arg,
                    assignments,
                    module_assignments,
                    function_returns,
                    seen=seen,
                )
            )
        for keyword in node.keywords:
            aliases.update(
                _origin_aliases(
                    keyword.value,
                    assignments,
                    module_assignments,
                    function_returns,
                    seen=seen,
                )
            )
        return aliases
    aliases: set[str] = set()
    for child in ast.iter_child_nodes(node):
        aliases.update(
            _origin_aliases(
                child,
                assignments,
                module_assignments,
                function_returns,
                seen=seen,
            )
        )
    return aliases


def _depends_on_generic_target(
    node: ast.AST | None,
    owner: str,
    assignments: Mapping[str, list[ast.AST]],
    module_assignments: Mapping[str, list[ast.AST]],
    function_returns: Mapping[str, list[ast.AST]],
) -> bool:
    expected = GENERIC_OWNER_TARGETS.get(owner, frozenset())
    if not expected:
        return False
    aliases = _origin_aliases(
        node, assignments, module_assignments, function_returns
    )
    leaf_aliases = {alias.rsplit(".", 1)[-1] for alias in aliases}
    return bool(expected & (aliases | leaf_aliases))


def _guard_import_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "volpred.canonical_write":
            for imported in node.names:
                if imported.name == "guard_canonical_write":
                    names.add(imported.asname or imported.name)
    shadowed: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            shadowed.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                shadowed.update(_assignment_names(target))
    names -= shadowed
    return names


def _guard_calls(scope: ast.AST, tree: ast.AST) -> list[ast.Call]:
    imported_names = _guard_import_names(tree)
    calls: list[ast.Call] = []
    for node in _nodes_in_scope(scope):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id in imported_names and node.args:
            calls.append(node)
    return calls


def _statement_path(
    node: ast.AST,
    scope: ast.AST,
    parents: Mapping[ast.AST, ast.AST],
) -> list[tuple[ast.AST, str, int, ast.stmt]]:
    path: list[tuple[ast.AST, str, int, ast.stmt]] = []
    current: ast.AST = node
    while current is not scope and current in parents:
        parent = parents[current]
        if isinstance(current, ast.stmt):
            for field, value in ast.iter_fields(parent):
                if isinstance(value, list) and current in value:
                    path.append((parent, field, value.index(current), current))
                    break
        current = parent
    return list(reversed(path))


def _dominates(
    guard: ast.Call,
    mutation: ast.Call,
    scope: ast.AST,
    parents: Mapping[ast.AST, ast.AST],
) -> bool:
    guard_path = _statement_path(guard, scope, parents)
    mutation_path = _statement_path(mutation, scope, parents)
    for guard_step, mutation_step in zip(guard_path, mutation_path):
        guard_block = (guard_step[0], guard_step[1])
        mutation_block = (mutation_step[0], mutation_step[1])
        if guard_block != mutation_block:
            return False
        if guard_step[3] is mutation_step[3]:
            continue
        # A direct expression earlier in the same executed block dominates.
        return guard_step[2] < mutation_step[2] and isinstance(guard_step[3], ast.Expr)
    return False


def _enclosing_if(
    node: ast.AST,
    parents: Mapping[ast.AST, ast.AST],
) -> ast.If | None:
    current = node
    while current in parents:
        current = parents[current]
        if isinstance(current, ast.If):
            return current
    return None


def _same_condition_guard_covers(
    guard: ast.Call,
    mutation: ast.Call,
    owner: str,
    parents: Mapping[ast.AST, ast.AST],
) -> bool:
    guard_if = _enclosing_if(guard, parents)
    mutation_if = _enclosing_if(mutation, parents)
    if guard_if is not None and mutation_if is not None:
        guard_branch = _if_branch_containing(guard, guard_if)
        mutation_branch = _if_branch_containing(mutation, mutation_if)
        return (
            guard.lineno < mutation.lineno
            and guard_branch is not None
            and guard_branch == mutation_branch
            and ast.dump(guard_if.test, include_attributes=False)
            == ast.dump(mutation_if.test, include_attributes=False)
        )
    # File handles expose an integer name for anonymous/in-memory descriptors
    # and a str/Path name for path-backed files. The writer guards exactly the
    # latter before touching the handle.
    return owner in HANDLE_ONLY_OWNERS and guard.lineno < mutation.lineno


def _if_branch_containing(
    node: ast.AST,
    condition: ast.If,
) -> str | None:
    """Return the branch of ``condition`` that lexically contains ``node``."""

    for branch in ("body", "orelse"):
        if any(
            node is descendant
            for statement in getattr(condition, branch)
            for descendant in ast.walk(statement)
        ):
            return branch
    return None


def _mode_guard_covers(
    guard: ast.Call,
    mutation: ast.Call,
    assignments: Mapping[str, list[ast.AST]],
    module_assignments: Mapping[str, list[ast.AST]],
    parents: Mapping[ast.AST, ast.AST],
) -> bool:
    """Prove a conditional guard covers the write-capable branch of ``open``.

    Dry-run tools commonly select ``"r+" if apply else "r"`` but guard only
    inside ``if apply``.  The guard cannot dominate the read-only invocation,
    so accept this shape only when the same predicate selects the guarded write
    mode and the opposite branch is statically read-only.  Other dynamic modes
    remain write-capable and fail closed.
    """

    guard_if = _enclosing_if(guard, parents)
    if guard_if is None or guard.lineno >= mutation.lineno:
        return False
    guard_branch = _if_branch_containing(guard, guard_if)
    if guard_branch is None:
        return False

    path_method = (
        isinstance(mutation.func, ast.Attribute) and mutation.func.attr == "open"
    )
    mode = _open_mode(mutation, path_method=path_method)
    if isinstance(mode, ast.Name):
        candidates = [
            value
            for value in (
                assignments.get(mode.id, ())
                or module_assignments.get(mode.id, ())
            )
            if getattr(value, "lineno", mutation.lineno) < mutation.lineno
        ]
        # Multiple reaching definitions require control-flow analysis. Refuse
        # to guess which one feeds the open call.
        if len(candidates) != 1:
            return False
        mode = candidates[0]

    if not isinstance(mode, ast.IfExp):
        return False
    if ast.dump(guard_if.test, include_attributes=False) != ast.dump(
        mode.test, include_attributes=False
    ):
        return False

    guarded_mode = mode.body if guard_branch == "body" else mode.orelse
    unguarded_mode = mode.orelse if guard_branch == "body" else mode.body
    return _mode_is_write(guarded_mode) and not _mode_is_write(unguarded_mode)


def _handler_reraises(handler: ast.ExceptHandler) -> bool:
    return bool(handler.body) and isinstance(handler.body[-1], ast.Raise)


def _broad_handler(handler: ast.ExceptHandler) -> bool:
    if handler.type is None:
        return True
    names: set[str] = set()
    if isinstance(handler.type, ast.Name):
        names.add(handler.type.id)
    elif isinstance(handler.type, ast.Tuple):
        names.update(
            item.id for item in handler.type.elts if isinstance(item, ast.Name)
        )
    return bool(names & {"Exception", "BaseException", "RuntimeError"})


def _guard_can_be_swallowed(
    guard: ast.Call,
    parents: Mapping[ast.AST, ast.AST],
) -> bool:
    current: ast.AST = guard
    while current in parents:
        parent = parents[current]
        if isinstance(parent, ast.Try):
            in_try_body = any(
                guard is descendant
                for statement in parent.body
                for descendant in ast.walk(statement)
            )
            if in_try_body and any(
                _broad_handler(handler) and not _handler_reraises(handler)
                for handler in parent.handlers
            ):
                return True
        current = parent
    return False


def _targets_correlate(
    guard_target: ast.AST,
    mutation_target: ast.AST | None,
    assignments: Mapping[str, list[ast.AST]],
    module_assignments: Mapping[str, list[ast.AST]],
    function_returns: Mapping[str, list[ast.AST]],
) -> bool:
    guard_aliases = _origin_aliases(
        guard_target, assignments, module_assignments, function_returns
    )
    mutation_aliases = _origin_aliases(
        mutation_target, assignments, module_assignments, function_returns
    )
    ignored = {
        "Path", "ROOT", "PROJECT_ROOT", "REPO", "REPO_ROOT", "storage",
        "storage_dir", "self",
    }
    guard_aliases -= ignored
    mutation_aliases -= ignored
    if guard_aliases & mutation_aliases:
        return True
    return ast.dump(guard_target, include_attributes=False) == ast.dump(
        mutation_target, include_attributes=False
    )


def _scan_file(path: Path, root: Path) -> tuple[list[Mutation], str | None]:
    relative = path.relative_to(root).as_posix()
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
    except (OSError, SyntaxError, UnicodeError) as exc:
        return [], f"{relative}: {type(exc).__name__}: {exc}"

    module_assignments = _assignments(tree)
    function_returns = _function_returns(tree)
    parameter_bindings = _parameter_bindings(tree)
    parents = {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }
    # Attribute paths such as ``self._feed_file`` are commonly established in
    # __init__ and mutated in another method. Make those definitions available
    # across class scopes while keeping ordinary local names scope-local.
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        value = getattr(node, "value", None)
        if value is None:
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            for name in _assignment_names(target):
                if "." in name:
                    module_assignments.setdefault(name, []).append(value)
    inventory: list[Mutation] = []
    for scope_node, scope_name in _scope_nodes(tree):
        owner = f"{relative}:{scope_name}"
        declared_owner = owner in LOW_LEVEL_OWNERS
        local_assignments = (
            dict(module_assignments) if scope_node is tree else _assignments(scope_node)
        )
        if isinstance(scope_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for parameter, values in parameter_bindings.get(scope_node.name, {}).items():
                local_assignments.setdefault(parameter, []).extend(values)
        guards = _guard_calls(scope_node, tree)
        for node in _nodes_in_scope(scope_node):
            if not isinstance(node, ast.Call):
                continue
            mutation = _mutation_target(node)
            if mutation is None:
                continue
            operation, target = mutation
            if operation in OWNER_HANDLE_MUTATORS and owner not in HANDLE_ONLY_OWNERS:
                continue
            generic_target = _depends_on_generic_target(
                target,
                owner,
                local_assignments,
                module_assignments,
                function_returns,
            )
            if (
                operation in {"replace", "rename"}
                and isinstance(node.func, ast.Attribute)
                and not generic_target
                and not _looks_path_like(
                    node.func.value,
                    local_assignments,
                    module_assignments,
                    function_returns=function_returns,
                )
            ):
                continue
            canonical_target = _is_canonical_target(
                target,
                local_assignments,
                module_assignments,
                function_returns,
            )
            if not canonical_target and not (declared_owner and generic_target):
                continue
            matching_guards = [
                guard
                for guard in guards
                if not _guard_can_be_swallowed(guard, parents)
                and (
                    _dominates(guard, node, scope_node, parents)
                    or _same_condition_guard_covers(
                        guard, node, owner, parents
                    )
                    or (
                        operation == "open-write"
                        and _mode_guard_covers(
                            guard,
                            node,
                            local_assignments,
                            module_assignments,
                            parents,
                        )
                    )
                )
                and _targets_correlate(
                    guard.args[0],
                    target,
                    local_assignments,
                    module_assignments,
                    function_returns,
                )
            ]
            inventory.append(
                Mutation(
                    path=relative,
                    line=node.lineno,
                    scope=scope_name,
                    operation=operation,
                    guarded=bool(matching_guards),
                    declared_owner=declared_owner,
                )
            )
    return inventory, None


def _is_next_tasks_path(
    node: ast.AST | None,
    assignments: Mapping[str, list[ast.AST]],
    module_assignments: Mapping[str, list[ast.AST]],
    function_returns: Mapping[str, list[ast.AST]],
) -> bool:
    hints = _path_hints(
        node, assignments, module_assignments, function_returns=function_returns
    )
    return all(component in hints for component in NEXT_TASKS_TARGET)


#: Locked read-modify-write handle modes. "r"/"r+" is the dry-run/apply ternary
#: used by queue-maintenance CLIs; "a+" is event_jobs' create-if-missing handle
#: (bytes still land via write_tasks_to_handle's seek(0)+truncate discipline).
NEXT_TASKS_RMW_MODES = frozenset({"r", "r+", "a+"})


def _mode_constants(
    node: ast.AST | None,
    assignments: Mapping[str, list[ast.AST]],
    seen: frozenset[str] = frozenset(),
) -> set[str]:
    """All string constants an open-mode expression can evaluate to; empty set
    when any branch is unresolvable (callers fail closed)."""
    if isinstance(node, ast.Constant):
        return {node.value} if isinstance(node.value, str) else set()
    if isinstance(node, ast.IfExp):
        body = _mode_constants(node.body, assignments, seen)
        orelse = _mode_constants(node.orelse, assignments, seen)
        return body | orelse if body and orelse else set()
    if isinstance(node, ast.Name) and node.id not in seen:
        values = assignments.get(node.id, ())
        if not values:
            return set()
        out: set[str] = set()
        for value in values:
            resolved = _mode_constants(value, assignments, seen | {node.id})
            if not resolved:
                return set()
            out |= resolved
        return out
    return set()


def _next_tasks_handle_names(
    scope: ast.AST,
    assignments: Mapping[str, list[ast.AST]],
    module_assignments: Mapping[str, list[ast.AST]],
    function_returns: Mapping[str, list[ast.AST]],
) -> set[str]:
    """Names bound to an open handle on the next_tasks file inside ``scope``."""

    def _binds(call: ast.AST | None) -> bool:
        return (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == "open"
            and _is_next_tasks_path(
                call.func.value, assignments, module_assignments, function_returns
            )
        )

    names: set[str] = set()
    for node in _nodes_in_scope(scope):
        if isinstance(node, ast.withitem) and _binds(node.context_expr):
            if isinstance(node.optional_vars, ast.Name):
                names.add(node.optional_vars.id)
        elif isinstance(node, ast.Assign) and _binds(node.value):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
    return names


def _scan_next_tasks_routing(path: Path, root: Path) -> list[str]:
    """WS-A1 gate: every next_tasks.json mutation must route through a helper."""
    relative = path.relative_to(root).as_posix()
    if relative == NEXT_TASKS_MODULE:
        return []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
    except (OSError, SyntaxError, UnicodeError):
        return []  # silent-ok: _scan_file already reports the parse error for scan roots
    module_assignments = _assignments(tree)
    function_returns = _function_returns(tree)
    parameter_bindings = _parameter_bindings(tree)
    findings: list[str] = []
    for scope_node, scope_name in _scope_nodes(tree):
        local_assignments = (
            dict(module_assignments) if scope_node is tree else _assignments(scope_node)
        )
        if isinstance(scope_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for parameter, values in parameter_bindings.get(scope_node.name, {}).items():
                local_assignments.setdefault(parameter, []).extend(values)

        def _on_next_tasks(node: ast.AST | None) -> bool:
            return _is_next_tasks_path(
                node, local_assignments, module_assignments, function_returns
            )

        handle_names = _next_tasks_handle_names(
            scope_node, local_assignments, module_assignments, function_returns
        )
        helper_called = False
        scope_findings: list[str] = []
        mutates = False
        for node in _nodes_in_scope(scope_node):
            if not isinstance(node, ast.Call):
                continue
            qualified = _qualified_name(node.func)
            if qualified.rsplit(".", 1)[-1] in NEXT_TASKS_HELPERS:
                helper_called = True
                continue
            where = f"{relative}:{node.lineno}: {scope_name}"
            # Serialization straight onto a next_tasks handle bypasses
            # write_tasks_to_handle's serialize-first + audits.
            if qualified == "json.dump" and len(node.args) >= 2:
                fp = node.args[1]
                if isinstance(fp, ast.Name) and fp.id in handle_names:
                    mutates = True
                    scope_findings.append(
                        f"{where} -> json.dump on next_tasks handle "
                        "(serialize via write_tasks_to_handle)"
                    )
                continue
            if (
                isinstance(node.func, ast.Attribute)
                and node.func.attr in {"truncate", "write"}
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in handle_names
            ):
                mutates = True
                scope_findings.append(
                    f"{where} -> handle .{node.func.attr}() on next_tasks "
                    "(serialize via write_tasks_to_handle)"
                )
                continue
            mutation = _mutation_target(node)
            if mutation is None:
                continue
            operation, target = mutation
            if operation in OWNER_HANDLE_MUTATORS:
                continue  # handled via handle_names above
            if not _on_next_tasks(target):
                continue
            mutates = True
            if operation == "mkdir":
                continue  # parent-dir bootstrap is harmless
            if operation == "write_text":
                arg = node.args[0] if node.args else None
                if (
                    isinstance(arg, ast.Constant)
                    and isinstance(arg.value, str)
                    and arg.value in NEXT_TASKS_BOOTSTRAP_LITERALS
                ):
                    continue
                scope_findings.append(
                    f"{where} -> full-payload write_text on next_tasks.json "
                    "(use write_tasks_locked)"
                )
                continue
            if operation == "open-write":
                mode = _open_mode(
                    node, path_method=isinstance(node.func, ast.Attribute)
                )
                resolved = _mode_constants(mode, local_assignments)
                if resolved and resolved <= NEXT_TASKS_RMW_MODES:
                    continue
                scope_findings.append(
                    f"{where} -> open(next_tasks.json) with mode outside "
                    f"{sorted(NEXT_TASKS_RMW_MODES)} (truncating/overwrite modes "
                    "bypass the locked read-modify-write contract)"
                )
                continue
            scope_findings.append(
                f"{where} -> {operation} targeting next_tasks.json "
                "(replace/rename/unlink bypass the flock; use the canonical helpers)"
            )
        if mutates and not helper_called:
            scope_findings.append(
                f"{relative}: {scope_name} mutates next_tasks.json without calling a "
                f"canonical helper ({'/'.join(sorted(NEXT_TASKS_HELPERS))})"
            )
        findings.extend(scope_findings)
    return findings


def _scan_experiment_next_tasks(root: Path) -> tuple[list[str], list[str]]:
    """Extend the routing gate into experiments/ (frozen-baseline ratchet).

    ``SKIP_PARTS`` exempts experiments/ from the owner ratchet, which is how
    K1387's bare ``open('w')`` writer stayed invisible (A1a audit). Text
    prefilter keeps the pass cheap; baseline entries are frozen evidence.
    """
    base = root / "experiments"
    violations: list[str] = []
    read_errors: list[str] = []
    if not base.is_dir():
        return violations, read_errors
    for path in sorted(base.rglob("*.py")):
        rel_parts = path.relative_to(base).parts[:-1]
        if any(part in SKIP_PARTS for part in rel_parts):
            continue
        relative = path.relative_to(root).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            read_errors.append(f"{relative}: {type(exc).__name__}: {exc}")
            continue  # silent-ok: recorded in read_errors -> surfaces as PARSE_ERROR (fail closed)
        if "next_tasks" not in text:
            continue
        if relative in NEXT_TASKS_EXPERIMENT_BASELINE:
            continue
        try:
            ast.parse(text, filename=relative)
        except SyntaxError as exc:
            # Fail closed: an unparseable experiment file that mentions the
            # queue cannot be audited, and _scan_file never sees experiments/.
            read_errors.append(f"{relative}: SyntaxError: {exc}")
            continue  # silent-ok: recorded in read_errors -> surfaces as PARSE_ERROR (fail closed)
        violations.extend(_scan_next_tasks_routing(path, root))
    return violations, read_errors


def _scan_next_tasks_doc_instructions(root: Path) -> list[str]:
    """Reject doc/prompt lines that teach shell rewrites of next_tasks.json."""
    patterns = [re.compile(p) for p in NEXT_TASKS_DOC_MUTATION_PATTERNS]
    doc_paths: list[Path] = []
    claude_dir = root / ".claude"
    if claude_dir.is_dir():
        for path in sorted(claude_dir.rglob("*")):
            rel = path.relative_to(claude_dir).parts
            if rel and rel[0] == "worktrees":
                continue
            if path.is_file() and path.suffix.lower() in {".md", ".sh"}:
                doc_paths.append(path)
    scripts_dir = root / "scripts"
    if scripts_dir.is_dir():
        doc_paths.extend(sorted(scripts_dir.glob("*.md")))
    violations: list[str] = []
    for path in doc_paths:
        relative = path.relative_to(root).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue  # silent-ok: docs are prose; unreadable prose cannot teach a writer
        for lineno, line in enumerate(text.splitlines(), 1):
            if "next_tasks.json" not in line:
                continue
            if any(p.search(line) for p in patterns):
                violations.append(
                    f"{relative}:{lineno}: doc teaches a shell rewrite of "
                    "next_tasks.json (route via scripts/task_pool_claim.py, "
                    "e.g. the annotate subcommand)"
                )
    return violations


def audit(root: Path = ROOT) -> AuditResult:
    root = root.resolve()
    inventory: list[Mutation] = []
    parse_errors: list[str] = []
    routing: list[str] = []
    for path in _iter_python_files(root):
        findings, error = _scan_file(path, root)
        inventory.extend(findings)
        if error:
            parse_errors.append(error)
        routing.extend(_scan_next_tasks_routing(path, root))
    experiment_violations, experiment_read_errors = _scan_experiment_next_tasks(root)
    routing.extend(experiment_violations)
    parse_errors.extend(experiment_read_errors)
    routing.extend(_scan_next_tasks_doc_instructions(root))

    inventory.sort(key=lambda item: (item.path, item.line, item.operation))
    violations = tuple(
        item for item in inventory if not (item.declared_owner and item.guarded)
    )
    observed_by_owner: dict[str, Counter[str]] = {}
    for item in inventory:
        if item.declared_owner:
            observed_by_owner.setdefault(item.owner, Counter())[item.operation] += 1
    mismatches = tuple(
        f"{owner}: expected {dict(expected)}, observed {dict(observed_by_owner.get(owner, Counter()))}"
        for owner, expected in sorted(LOW_LEVEL_OWNERS.items())
        if (root / owner.split(":", 1)[0]).exists()
        and Counter(expected) != observed_by_owner.get(owner, Counter())
    )
    return AuditResult(
        tuple(inventory),
        violations,
        mismatches,
        tuple(parse_errors),
        tuple(sorted(routing)),
    )


def _render_text(result: AuditResult) -> str:
    lines = [
        f"[canonical-writers] {len(result.inventory)} canonical/owner mutations inventoried"
    ]
    for item in result.inventory:
        lines.append(
            f"{item.path}:{item.line}: {item.classification}: "
            f"{item.scope} -> {item.operation}"
        )
    for mismatch in result.owner_count_mismatches:
        lines.append(f"RATCHET: {mismatch}")
    for error in result.parse_errors:
        lines.append(f"PARSE_ERROR: {error}")
    for finding in result.helper_routing_violations:
        lines.append(f"NEXT-TASKS-ROUTING: {finding}")
    lines.append(
        f"[canonical-writers] {'PASS' if result.ok else 'FAIL'}: "
        f"{len(result.violations)} unguarded, "
        f"{len(result.owner_count_mismatches)} owner-count mismatch(es), "
        f"{len(result.parse_errors)} parse error(s), "
        f"{len(result.helper_routing_violations)} next-tasks routing violation(s)"
    )
    return "\n".join(lines)


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)

    result = audit(args.root)
    if args.json:
        print(
            json.dumps(
                {
                    "ok": result.ok,
                    "inventory": [
                        {**asdict(item), "classification": item.classification}
                        for item in result.inventory
                    ],
                    "violations": [asdict(item) for item in result.violations],
                    "owner_count_mismatches": list(result.owner_count_mismatches),
                    "parse_errors": list(result.parse_errors),
                    "helper_routing_violations": list(result.helper_routing_violations),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(_render_text(result))
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
