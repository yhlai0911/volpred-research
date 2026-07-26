"""Typed Operations Core program context for the periodic boss report.

The report used to paste two files written in May 2026 and labelled them
"current".  This module deliberately reads only the master spec status table
declared canonical by ``AGENTS.md`` plus the current task-pool mode control
receipt.  It returns source identities with the read model so freshness and
provenance are visible to the renderer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any


_MASTER_SPEC = Path("docs/refactor_plan_ops_master_2026_07.md")
_QUEUE = Path("storage/next_tasks.json")
_MODE = Path("storage/ops/task_pool_mode.json")
_STATUS_HEADING = re.compile(
    r"^## 7\.\s+狀態表（canonical — 唯一進度真相）\s*$"
)
_NEXT_LEVEL_TWO_HEADING = re.compile(r"^## (?!#)")
_TABLE_DIVIDER = re.compile(r"^:?-{3,}:?$")


@dataclass(frozen=True)
class ProgramStatusItem:
    """One non-complete row from the canonical master status table."""

    title: str
    status: str
    evidence: str


@dataclass(frozen=True)
class BossReportProgram:
    """Current program intent and open work with exact source identities."""

    schema_version: str
    intent: str
    open_items: tuple[ProgramStatusItem, ...]
    source_ref: str
    source_sha256: str
    source_updated_at: str
    control_ref: str
    control_sha256: str
    warnings: tuple[str, ...]

    def next_actions(self, *, limit: int = 8) -> list[str]:
        if isinstance(limit, bool) or limit <= 0:
            raise ValueError("Boss Report next-action limit must be positive")
        return [
            f"{item.title} — {item.status}"
            + (f"；{item.evidence}" if item.evidence else "")
            for item in self.open_items[:limit]
        ]

    def as_report_fields(self) -> dict[str, Any]:
        """Adapt the typed read model to the existing HTML table interface."""

        active = [
            f"{item.title}（{item.status}）"
            for item in self.open_items[:4]
        ]
        risks = [
            f"{item.title}：{item.evidence or item.status}"
            for item in self.open_items
            if "contained" in item.status.lower()
            or "blocked" in item.status.lower()
            or "pending" in item.status.lower()
        ][:4]
        fields: dict[str, Any] = {
            "intent": self.intent,
            "weekly_goal": active,
            "plan": self.next_actions(limit=8),
            "success_criteria": [
                "只以 §7 canonical 狀態與 live receipt 回讀判定完成",
                "contained 不得冒充 root_cause_fixed_and_verified",
                "排程與外部效果必須有 owner、terminal receipt 與下游 acknowledgement",
            ],
            "risks": risks,
            "source_identity": (
                f"{self.source_ref} · sha256={self.source_sha256[:12]} · "
                f"updated={self.source_updated_at}; "
                f"{self.control_ref} · sha256={self.control_sha256[:12]}"
            ),
        }
        if self.warnings:
            fields["source_warnings"] = list(self.warnings)
        return fields


def read_boss_report_program(repo_root: Path) -> BossReportProgram:
    """Build the report program context from canonical, versioned sources."""

    root = repo_root.resolve()
    spec_path = root / _MASTER_SPEC
    spec_bytes = spec_path.read_bytes()
    spec_text = spec_bytes.decode("utf-8")
    status_row_count, open_items = _status_items(spec_text)
    if status_row_count == 0:
        raise ValueError(
            "canonical master spec §7 has no status data rows"
        )

    intent, control_ref, control_sha256, warnings = _current_intent(root)
    stat = spec_path.stat()
    source_updated_at = datetime.fromtimestamp(
        stat.st_mtime,
        tz=timezone.utc,
    ).isoformat()
    return BossReportProgram(
        schema_version="boss-report-program.v1",
        intent=intent,
        open_items=tuple(open_items),
        source_ref=f"{_MASTER_SPEC.as_posix()}#7",
        source_sha256=hashlib.sha256(spec_bytes).hexdigest(),
        source_updated_at=source_updated_at,
        control_ref=control_ref,
        control_sha256=control_sha256,
        warnings=tuple(warnings),
    )


def _current_intent(
    root: Path,
) -> tuple[str, str, str, list[str]]:
    mode_path = root / _MODE
    mode_bytes = mode_path.read_bytes()
    mode = _object(json.loads(mode_bytes), field=str(_MODE))
    mode_ref = _MODE.as_posix()
    warnings: list[str] = []
    if (
        mode.get("enabled") is False
        and mode.get("mode") == "queued_execution"
    ):
        reason = str(mode.get("reason") or "").strip()
        if not reason:
            warnings.append(
                "queued-execution control reason unavailable; "
                "using master-spec intent"
            )
            reason = (
                "依 Operations Core master spec 收斂所有未完成狀態"
            )
        return (
            reason,
            mode_ref,
            hashlib.sha256(mode_bytes).hexdigest(),
            warnings,
        )

    if (
        mode.get("enabled") is not True
        or mode.get("mode") != "direct_execution"
    ):
        warnings.append(
            "task-pool mode is unsupported; using master-spec intent"
        )
        return (
            "依 Operations Core master spec 收斂所有未完成狀態",
            mode_ref,
            hashlib.sha256(mode_bytes).hexdigest(),
            warnings,
        )

    queue_path = root / _QUEUE
    queue_bytes = queue_path.read_bytes()
    queue = json.loads(queue_bytes)
    if not isinstance(queue, list):
        raise ValueError(f"{_QUEUE} root must be a list")
    control_sha256 = hashlib.sha256(
        mode_bytes + b"\0" + queue_bytes
    ).hexdigest()
    raw_preserve_ids = mode.get("preserve_task_ids")
    if not isinstance(raw_preserve_ids, list) or not raw_preserve_ids:
        raise ValueError(
            "direct-execution mode preserve_task_ids must be non-empty"
        )
    if not all(
        isinstance(value, str) and value.strip()
        for value in raw_preserve_ids
    ):
        raise ValueError(
            "direct-execution mode preserve_task_ids must be non-empty strings"
        )
    preserve_ids = [value.strip() for value in raw_preserve_ids]
    if len(set(preserve_ids)) != len(preserve_ids):
        raise ValueError(
            "direct-execution mode preserve_task_ids must be unique"
        )
    rows = [
        row
        for row in queue
        if isinstance(row, dict)
    ]
    selected: list[tuple[str, str]] = []
    for task_id in preserve_ids:
        matches = [
            row
            for row in rows
            if str(row.get("id") or "").strip() == task_id
        ]
        if len(matches) != 1:
            raise ValueError(
                "direct-execution preserved task must have exactly one "
                f"queue row: {task_id}"
            )
        title = str(matches[0].get("title") or "").strip()
        if not title:
            raise ValueError(
                "direct-execution preserved task title is empty: "
                f"{task_id}"
            )
        selected.append((task_id, title))
    if not selected:
        raise AssertionError(
            "validated direct-execution selection cannot be empty"
        )
    return (
        "；".join(title for _, title in selected),
        (
            f"{mode_ref} + {_QUEUE.as_posix()}#"
            + ",".join(task_id for task_id, _ in selected)
        ),
        control_sha256,
        warnings,
    )


def _status_items(
    spec_text: str,
) -> tuple[int, list[ProgramStatusItem]]:
    lines = spec_text.splitlines()
    try:
        start = next(
            index
            for index, line in enumerate(lines)
            if _STATUS_HEADING.fullmatch(line.strip())
        )
    except StopIteration as exc:
        raise ValueError("canonical master spec §7 heading is missing") from exc

    section: list[str] = []
    for line in lines[start + 1 :]:
        if _NEXT_LEVEL_TWO_HEADING.match(line):
            break
        section.append(line)

    status_row_count = 0
    rows: list[ProgramStatusItem] = []
    for line in section:
        stripped = line.strip()
        if not stripped.startswith("|") or not stripped.endswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) < 3:
            continue
        title, status, evidence = (
            _plain_markdown(cells[0]),
            _plain_markdown(cells[1]),
            _plain_markdown(cells[2]),
        )
        if (
            not title
            or title in {"工作流", "項", "項目"}
            or _TABLE_DIVIDER.fullmatch(title)
            or _TABLE_DIVIDER.fullmatch(status)
        ):
            continue
        status_row_count += 1
        if (
            status.startswith("✅")
            or "root_cause_fixed_and_verified" in status.lower()
        ):
            continue
        rows.append(
            ProgramStatusItem(
                title=title,
                status=status,
                evidence=evidence,
            )
        )
    return status_row_count, rows


def _plain_markdown(value: str) -> str:
    plain = value.replace("**", "").replace("__", "").replace("`", "")
    plain = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", plain)
    return re.sub(r"\s+", " ", plain).strip()


def _object(value: Any, *, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} root must be an object")
    return value


__all__ = [
    "BossReportProgram",
    "ProgramStatusItem",
    "read_boss_report_program",
]
