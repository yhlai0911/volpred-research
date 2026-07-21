#!/usr/bin/env python3
"""Repository-wide experiment reproducibility audit.

The audit has two deliberately separate layers:

* ``inventory`` is fast and read-only.  It discovers experiments referenced by
  current papers and the most recent feed articles, classifies every K folder,
  and records why a folder is or is not currently reproducible.
* ``run`` executes selected experiments from a clean, disposable clone of the
  committed repository.  Historical ``*_results.json`` files in the working
  tree are never touched.  The clone's regenerated JSON is compared with the
  archived JSON and only a new ``reproduce_report.json`` is written to main.

This implements the minimum-standard distinction in Peng (2011): reproducing a
result makes a claim inspectable, but does not establish that the research is
correct.  The provenance and workflow fields follow Sandve et al. (2013) and
Stodden et al. (2016).

Examples:

    uv run python scripts/reproduce_check.py inventory
    uv run python scripts/reproduce_check.py run --experiment K1439 --timeout 180
    uv run python scripts/reproduce_check.py sample --limit 3 --timeout 120
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from volpred.ops.diagnostics import warn


ROOT = Path(__file__).resolve().parents[1]
REPORT_NAME = "reproduce_report.json"
SPEC_NAME = "reproduce_spec.json"
DEFAULT_INVENTORY = Path("storage/ops/reproducibility/latest.json")
KNOWLEDGE_PATH = Path("storage/memory/knowledge.json")
REPORT_SCHEMA = "volpred.reproduce_report.v1"
SPEC_SCHEMA = "volpred.reproduce_spec.v1"
INVENTORY_SCHEMA = "volpred.reproduce_inventory.v1"
STATUS_SCHEMA = "volpred.reproduce_status.v1"
PASS_REPORT_STATUSES = {"pass_exact", "pass_tolerated"}
# 2026-07-22 — 上限自 3600 放寬到 86400。
# 這個界的用途是攔「單位打錯」（把毫秒當秒填成 13448000），不是限制實驗能跑多久：
# 真正的執行上界是 `effective_timeout = min(CLI --timeout, spec.timeout_seconds)`，
# 呼叫端永遠可以再壓低。1 小時的天花板反而逼長跑實驗填一個**必然 timeout 的假值** ——
# K1730 arm A 真實耗時 13448s，誠實填 18000 會被 validator 拒收，填 3600 則是寫謊。
# 兩者都讓 reproduce gate 失去意義，所以放寬到 24h：仍能攔住量級錯誤，但不再獎勵造假。
MAX_TIMEOUT_SECONDS = 86_400
DEFAULT_RTOL = 1e-9
DEFAULT_ATOL = 1e-12

K_REF_RE = re.compile(r"(?<![A-Za-z0-9_])([Kk]\d{1,5}(?:[A-Za-z0-9_-]*[A-Za-z0-9])?)")
PAPER_K_REF_RE = re.compile(
    r"(?<![A-Za-z0-9_])([Kk]\d{1,5}(?:[A-Za-z]+\d*)?(?:-rev\d+)?)",
    re.IGNORECASE,
)
SEED_RE = re.compile(r"\b(seed|random_state|default_rng|RandomState)\b", re.IGNORECASE)
EXCLUDED_PAPER_PARTS = {
    "review_history",
    "reproducibility_audit",
    "archive",
    "archived",
    "_build",
}
DEFAULT_IGNORE_POINTERS = {"/created_at", "/generated_at", "/runtime_seconds"}
FALSE_EXPERIMENT_REFS = {"K125"}  # MIDAS lag K=125, not an experiment id.
PAPER_REF_ALIASES = {
    "K988B": "K988",  # supplement label stored inside experiments/k988/
    "K1025V3": "K1025",  # canonical vintage stored inside experiments/k1025/
}

METHODOLOGY_REFERENCES = [
    {
        "citation": "Peng (2011), Reproducible Research in Computational Science",
        "doi": "10.1126/science.1213847",
        "principle": "computational reproducibility is a minimum standard, not a validity verdict",
    },
    {
        "citation": "Sandve et al. (2013), Ten Simple Rules for Reproducible Computational Research",
        "doi": "10.1371/journal.pcbi.1003285",
        "principle": "record provenance and preserve the exact workflow behind every result",
    },
    {
        "citation": "Stodden et al. (2016), Enhancing Reproducibility for Computational Methods",
        "doi": "10.1126/science.aah6168",
        "principle": "disclose code, data, workflow, and computational environment",
    },
]


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant is forbidden: {value}")


def _loads_json_strict(value: str | bytes) -> Any:
    return json.loads(value, parse_constant=_json_constant)


def _read_json_strict(path: Path) -> Any:
    return _loads_json_strict(path.read_bytes())


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write derived evidence atomically; never leave a truncated report."""
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(encoded, encoding="utf-8")
        _read_json_strict(tmp)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _git_head(root: Path) -> str | None:
    proc = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.stdout.strip() if proc.returncode == 0 else None


def _git_file_sha256(root: Path, relative_path: str) -> str | None:
    proc = subprocess.run(
        ["git", "show", f"HEAD:{relative_path}"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    return hashlib.sha256(proc.stdout).hexdigest() if proc.returncode == 0 else None


def _normalize_ref(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    match = K_REF_RE.search(value.strip())
    if not match:
        return None
    raw = match.group(1)
    normalized = "K" + raw[1:]
    return PAPER_REF_ALIASES.get(normalized.upper(), normalized)


def _paper_source_files(root: Path) -> Iterable[Path]:
    paper_root = root / "paper"
    if not paper_root.exists():
        return []
    files: list[Path] = []
    try:
        from scripts.check_paper_compliance import submission_files
    except ModuleNotFoundError:  # direct ``python scripts/reproduce_check.py``
        from check_paper_compliance import submission_files
    for paper_dir in sorted(path for path in paper_root.iterdir() if path.is_dir()):
        manifest = paper_dir / "experiments.md"
        if manifest.is_file():
            files.append(manifest)
        active_sources = submission_files(paper_dir)
        files.extend(active_sources)
        # Pipeline papers may have neither a manifest nor a submission source yet.
        readme = paper_dir / "README.md"
        if not manifest.is_file() and not active_sources and readme.is_file():
            files.append(readme)
    return sorted(files)


def discover_priority_refs(root: Path = ROOT, feed_limit: int = 60) -> dict[str, list[str]]:
    paper_refs: set[str] = set()
    exp_root = root / "experiments"
    exp_dirs = sorted(path for path in exp_root.iterdir() if path.is_dir()) if exp_root.exists() else []
    for path in _paper_source_files(root):
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in PAPER_K_REF_RE.findall(text):
            ref = _normalize_ref(match)
            is_manifest = path.name == "experiments.md"
            if (
                ref
                and ref.upper() not in FALSE_EXPERIMENT_REFS
                and (is_manifest or _resolve_ref_dir(ref, exp_dirs) is not None)
            ):
                paper_refs.add(ref)

    feed_refs: set[str] = set()
    feed_path = root / "storage" / "reports" / "feed.json"
    try:
        raw = _read_json_strict(feed_path)
        items = raw if isinstance(raw, list) else raw.get("items", [])
        if not isinstance(items, list):
            items = []
    except (OSError, ValueError, json.JSONDecodeError):
        items = []

    def article_key(pair: tuple[int, Any]) -> tuple[str, int]:
        index, item = pair
        if not isinstance(item, dict):
            return "", index
        stamp = item.get("published_at") or item.get("created_at") or item.get("updated_at") or ""
        return str(stamp), index

    published = [item for item in items if isinstance(item, dict) and item.get("status") == "published"]
    recent = [item for _, item in sorted(enumerate(published), key=article_key)[-feed_limit:]]
    for item in recent:
        if not isinstance(item, dict):
            continue
        details = item.get("details") if isinstance(item.get("details"), dict) else {}
        refs = details.get("experiment_refs") or []
        if isinstance(refs, str):
            refs = [refs]
        if not isinstance(refs, list):
            continue
        for value in refs:
            ref = _normalize_ref(value)
            if ref:
                feed_refs.add(ref)

    return {
        "paper": sorted(paper_refs, key=str.casefold),
        "recent_feed": sorted(feed_refs, key=str.casefold),
        "priority": sorted(paper_refs | feed_refs, key=str.casefold),
    }


def _python_files(exp_dir: Path) -> list[Path]:
    return sorted(
        path
        for path in exp_dir.glob("*.py")
        if "__pycache__" not in path.parts and not path.name.startswith(".")
    )


def _code_surface_files(exp_dir: Path) -> list[Path]:
    return sorted(
        path
        for path in exp_dir.rglob("*.py")
        if "__pycache__" not in path.parts and not path.name.startswith(".")
    )


def _result_files(exp_dir: Path) -> list[Path]:
    return sorted(path for path in exp_dir.glob("*results.json") if path.name != REPORT_NAME)


def _k_id(name: str) -> str | None:
    """Leading K-number of an experiment dir (``k1538_bond_fund…`` → ``k1538``)."""
    match = re.match(r"^([Kk]\d+)", name)
    return match.group(1).casefold() if match else None


def knowledge_recorded_ids(root: Path = ROOT) -> set[str] | None:
    """K-ids that appear anywhere in the knowledge base. ``None`` = KB unreadable."""
    path = root / KNOWLEDGE_PATH
    try:
        entries = _read_json_strict(path)
    except (OSError, ValueError) as exc:
        warn("reproduce_check", "knowledge base unreadable", path=str(path), err=str(exc))
        return None
    if not isinstance(entries, list):
        warn("reproduce_check", "knowledge base is not a list", path=str(path))
        return None
    # Two entry shapes coexist: modern (item_id/content/evidence) and legacy
    # (title/experiment_id). Scan every value rather than a field whitelist —
    # a whitelist silently skipped every legacy entry.
    recorded: set[str] = set()
    for entry in entries:
        blob = json.dumps(entry, ensure_ascii=False) if isinstance(entry, dict) else str(entry)
        recorded.update(match.casefold() for match in re.findall(r"[Kk]\d{3,}", blob))
    return recorded


def _safe_relative_path(value: Any, *, field: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty relative path")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{field} escapes the repository: {value!r}")
    return path


def load_spec(exp_dir: Path) -> tuple[dict[str, Any] | None, str | None]:
    path = exp_dir / SPEC_NAME
    if not path.is_file():
        return None, "missing reproduce_spec.json"
    try:
        raw = _read_json_strict(path)
        if not isinstance(raw, dict) or raw.get("schema_version") != SPEC_SCHEMA:
            raise ValueError(f"schema_version must equal {SPEC_SCHEMA!r}")
        entrypoint = raw.get("entrypoint")
        if not isinstance(entrypoint, dict):
            raise ValueError("entrypoint must be an object")
        entry_rel = _safe_relative_path(entrypoint.get("path"), field="entrypoint.path")
        args = entrypoint.get("args", [])
        if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
            raise ValueError("entrypoint.args must be a list of strings")
        result_rel = _safe_relative_path(raw.get("canonical_result"), field="canonical_result")
        inputs = raw.get("inputs", [])
        if not isinstance(inputs, list):
            raise ValueError("inputs must be a list")
        for index, item in enumerate(inputs):
            if not isinstance(item, dict):
                raise ValueError(f"inputs[{index}] must be an object")
            _safe_relative_path(item.get("path"), field=f"inputs[{index}].path")
            digest = item.get("sha256")
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError(f"inputs[{index}].sha256 must be lowercase SHA-256")
        timeout = raw.get("timeout_seconds", 180)
        if (
            not isinstance(timeout, int)
            or isinstance(timeout, bool)
            or not 1 <= timeout <= MAX_TIMEOUT_SECONDS
        ):
            raise ValueError(
                f"timeout_seconds must be an integer in [1, {MAX_TIMEOUT_SECONDS}]"
            )
        if raw.get("network", "deny") not in {"deny", "allow"}:
            raise ValueError("network must be 'deny' or 'allow'")
        randomness = raw.get("randomness")
        if not isinstance(randomness, dict) or randomness.get("status") not in {
            "declared",
            "not_applicable",
        }:
            raise ValueError("randomness.status must be 'declared' or 'not_applicable'")
        seeds = randomness.get("seeds", [])
        if not isinstance(seeds, list):
            raise ValueError("randomness.seeds must be a list")
        if randomness["status"] == "declared" and not seeds:
            raise ValueError("declared randomness requires at least one seed")
        for index, seed in enumerate(seeds):
            if not isinstance(seed, dict) or not isinstance(seed.get("library"), str):
                raise ValueError(f"randomness.seeds[{index}] requires a library")
            value = seed.get("value")
            if isinstance(value, bool) or not isinstance(value, (int, str)):
                raise ValueError(f"randomness.seeds[{index}].value must be an integer or string")
        comparison = raw.get("comparison", {})
        if not isinstance(comparison, dict):
            raise ValueError("comparison must be an object")
        ignore = comparison.get("ignore_pointers", sorted(DEFAULT_IGNORE_POINTERS))
        if not isinstance(ignore, list) or not all(
            isinstance(pointer, str) and pointer.startswith("/") for pointer in ignore
        ):
            raise ValueError("comparison.ignore_pointers must contain JSON pointers")
        ignore_reasons = comparison.get("ignore_reasons", {})
        if not isinstance(ignore_reasons, dict) or set(ignore_reasons) != set(ignore):
            raise ValueError("comparison.ignore_reasons must document every ignored pointer exactly")
        if not all(isinstance(reason, str) and reason.strip() for reason in ignore_reasons.values()):
            raise ValueError("every ignored pointer requires a non-empty reason")
        rtol = comparison.get("rtol", DEFAULT_RTOL)
        atol = comparison.get("atol", DEFAULT_ATOL)
        if not isinstance(rtol, (int, float)) or not isinstance(atol, (int, float)):
            raise ValueError("comparison tolerances must be numeric")
        if rtol < 0 or atol < 0 or not math.isfinite(float(rtol)) or not math.isfinite(float(atol)):
            raise ValueError("comparison tolerances must be finite and non-negative")
        if (float(rtol), float(atol)) != (DEFAULT_RTOL, DEFAULT_ATOL) and not comparison.get("reason"):
            raise ValueError("non-default comparison tolerance requires a reason")
        if not (exp_dir / entry_rel).is_file():
            raise ValueError(f"entrypoint does not exist: {entry_rel}")
        if not (exp_dir / result_rel).is_file():
            raise ValueError(f"canonical result does not exist: {result_rel}")
        root = exp_dir.parents[1].resolve()
        for field, candidate, boundary in (
            ("entrypoint.path", exp_dir / entry_rel, exp_dir.resolve()),
            ("canonical_result", exp_dir / result_rel, exp_dir.resolve()),
        ):
            if candidate.is_symlink():
                raise ValueError(f"{field} may not be a symlink")
            try:
                candidate.resolve().relative_to(boundary)
            except ValueError as exc:
                raise ValueError(f"{field} resolves outside its experiment directory") from exc
        for index, item in enumerate(inputs):
            candidate = root / Path(item["path"])
            if candidate.is_symlink():
                raise ValueError(f"inputs[{index}].path may not be a symlink")
            try:
                candidate.resolve().relative_to(root)
            except ValueError as exc:
                raise ValueError(f"inputs[{index}].path resolves outside the repository") from exc
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return None, f"invalid reproduce_spec.json: {exc}"
    return raw, None


def resolve_entrypoint(exp_dir: Path) -> tuple[Path | None, str | None]:
    spec, spec_error = load_spec(exp_dir)
    if spec:
        return exp_dir / Path(spec["entrypoint"]["path"]), None
    if (exp_dir / SPEC_NAME).exists():
        return None, spec_error
    reproduce = exp_dir / "reproduce.py"
    if reproduce.is_file():
        return reproduce, None
    exact = exp_dir / f"{exp_dir.name}.py"
    if exact.is_file():
        return exact, None
    for path in exp_dir.glob("*.py"):
        if path.stem.casefold() == exp_dir.name.casefold():
            return path, None
    excluded = ("test", "render", "figure", "fig_", "plot", "review", "audit", "check")
    candidates = [
        path
        for path in exp_dir.glob("*.py")
        if not path.stem.casefold().startswith(excluded)
    ]
    if len(candidates) == 1:
        return candidates[0], None
    if not candidates:
        return None, "no executable experiment entrypoint"
    return None, f"ambiguous entrypoint ({len(candidates)} candidates)"


def resolve_result(exp_dir: Path) -> tuple[Path | None, str | None]:
    spec, spec_error = load_spec(exp_dir)
    if spec:
        return exp_dir / Path(spec["canonical_result"]), None
    if (exp_dir / SPEC_NAME).exists():
        return None, spec_error
    results = _result_files(exp_dir)
    exact_name = f"{exp_dir.name}_results.json".casefold()
    exact = [path for path in results if path.name.casefold() == exact_name]
    if len(exact) == 1:
        return exact[0], None
    if len(results) == 1:
        return results[0], None
    if not results:
        return None, "no archived *_results.json"
    return None, f"ambiguous result artifact ({len(results)} candidates)"


@dataclass(frozen=True)
class ExperimentRecord:
    experiment: str
    path: str
    priority_sources: tuple[str, ...]
    code_count: int
    results_count: int
    reproduce_report: bool
    report_status: str | None
    report_stale: bool | None
    spec_file: str | None
    entrypoint: str | None
    result_file: str | None
    classification: str
    blocker: str | None


def _report_status(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        data = _read_json_strict(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return "malformed_report"
    if not isinstance(data, dict) or data.get("schema_version") != REPORT_SCHEMA:
        return "invalid_schema"
    outcome = data.get("outcome")
    if not isinstance(outcome, dict) or not isinstance(outcome.get("status"), str):
        return "missing_status"
    status = outcome["status"]
    if status in PASS_REPORT_STATUSES:
        comparison = data.get("comparison")
        integrity = data.get("integrity")
        valid_pass = (
            outcome.get("reproducible") is True
            and isinstance(comparison, dict)
            and comparison.get("mismatch_count") == 0
            and isinstance(integrity, dict)
            and integrity.get("canonical_unchanged") is True
        )
        return status if valid_pass else "invalid_pass_report"
    return status


def _report_is_stale(path: Path, root: Path) -> bool | None:
    if not path.exists():
        return None
    try:
        data = _read_json_strict(path)
        subject_files = data.get("discovery", {}).get("subject_files")
        if not isinstance(subject_files, list) or not subject_files:
            return True
        for item in subject_files:
            rel = _safe_relative_path(item.get("path"), field="subject_files.path")
            current = root / rel
            if not current.is_file() or _sha256(current) != item.get("sha256"):
                return True
        environment = data.get("environment", {})
        engine = data.get("engine", {})
        if engine.get("sha256") != _sha256(Path(__file__).resolve()):
            return True
        lock = root / "uv.lock"
        if environment.get("uv_lock_sha256") != (_sha256(lock) if lock.is_file() else None):
            return True
        if environment.get("package_versions") != _package_versions():
            return True
        if environment.get("python") != sys.version:
            return True
        if environment.get("platform") != platform.platform():
            return True
        if environment.get("machine") != platform.machine():
            return True
    except (OSError, ValueError, json.JSONDecodeError, AttributeError):
        return True  # silent-ok: an unreadable stamp is indistinguishable from a stale one, and both mean rerun
    return False


def classify_experiment(exp_dir: Path, sources: Iterable[str] = ()) -> ExperimentRecord:
    code = _python_files(exp_dir)
    results = _result_files(exp_dir)
    entrypoint, entry_error = resolve_entrypoint(exp_dir)
    result_file, result_error = resolve_result(exp_dir)
    spec, spec_error = load_spec(exp_dir)

    if code and not results:
        classification = "not_reproducible_missing_archived_results"
        blocker = result_error
    elif results and not code:
        classification = "not_reproducible_missing_code"
        blocker = "archived results exist but no Python source is present"
    elif not code and not results:
        classification = "metadata_only"
        blocker = "no Python source and no archived results"
    elif entry_error:
        classification = "manual_mapping_required"
        blocker = entry_error
    elif result_error:
        classification = "manual_mapping_required"
        blocker = result_error
    elif not spec:
        classification = "unverified_missing_spec"
        blocker = spec_error
    else:
        classification = "runnable"
        blocker = None

    report = exp_dir / REPORT_NAME
    return ExperimentRecord(
        experiment=exp_dir.name,
        path=f"experiments/{exp_dir.name}",
        priority_sources=tuple(sorted(set(sources))),
        code_count=len(code),
        results_count=len(results),
        reproduce_report=report.exists(),
        report_status=_report_status(report),
        report_stale=_report_is_stale(report, exp_dir.parents[1]),
        spec_file=SPEC_NAME if spec else None,
        entrypoint=entrypoint.relative_to(exp_dir).as_posix() if entrypoint else None,
        result_file=result_file.relative_to(exp_dir).as_posix() if result_file else None,
        classification=classification,
        blocker=blocker,
    )


def _resolve_ref_dir(ref: str, dirs: list[Path]) -> Path | None:
    key = PAPER_REF_ALIASES.get(ref.upper(), ref).casefold().replace("-", "_")
    exact = [path for path in dirs if path.name.casefold().replace("-", "_") == key]
    if len(exact) == 1:
        return exact[0]
    prefixed = [
        path
        for path in dirs
        if path.name.casefold().replace("-", "_").startswith(f"{key}_")
    ]
    return prefixed[0] if len(prefixed) == 1 else None


def build_inventory(root: Path = ROOT, feed_limit: int = 60) -> dict[str, Any]:
    refs = discover_priority_refs(root, feed_limit=feed_limit)
    exp_root = root / "experiments"
    dirs = sorted(
        path
        for path in exp_root.iterdir()
        if path.is_dir() and re.match(r"^[Kk]\d", path.name)
    ) if exp_root.exists() else []
    resolved_refs: dict[str, str] = {}
    source_by_dir: dict[str, set[str]] = {}
    for source in ("paper", "recent_feed"):
        for ref in refs[source]:
            resolved = _resolve_ref_dir(ref, dirs)
            if resolved:
                resolved_refs[ref] = resolved.name
                source_by_dir.setdefault(resolved.name.casefold(), set()).add(source)
    records = [classify_experiment(path, source_by_dir.get(path.name.casefold(), ())) for path in dirs]
    by_name = {record.experiment.casefold(): record for record in records}

    missing_refs = [ref for ref in refs["priority"] if ref not in resolved_refs]
    priority_records = [
        by_name[resolved_refs[ref].casefold()]
        for ref in refs["priority"]
        if ref in resolved_refs
    ]
    priority_records = list({record.experiment.casefold(): record for record in priority_records}.values())
    code_without_results = [
        record for record in records
        if record.classification == "not_reproducible_missing_archived_results"
    ]
    broken_reports = [
        record for record in records
        if record.reproduce_report and record.report_status not in PASS_REPORT_STATUSES
    ]
    status_counts = Counter(record.report_status for record in records if record.report_status)

    # A finished experiment that never reached knowledge.json is invisible to topic
    # dedup and article selection — the pipeline will happily re-run it.
    recorded_kids = knowledge_recorded_ids(root)
    results_without_knowledge = [] if recorded_kids is None else [
        record for record in records
        if record.results_count > 0 and (_k_id(record.experiment) or "") not in recorded_kids
    ]

    counts = {
        "experiment_dirs": len(records),
        "with_code": sum(record.code_count > 0 for record in records),
        "with_results": sum(record.results_count > 0 for record in records),
        "with_reproduce_report": sum(record.reproduce_report for record in records),
        "runnable": sum(record.classification == "runnable" for record in records),
        "unverified_missing_spec": sum(
            record.classification == "unverified_missing_spec" for record in records
        ),
        "code_without_results": len(code_without_results),
        "results_without_code": sum(
            record.classification == "not_reproducible_missing_code" for record in records
        ),
        "priority_refs": len(refs["priority"]),
        "priority_existing": len(priority_records),
        "priority_missing_dirs": len(missing_refs),
        "priority_runnable": sum(record.classification == "runnable" for record in priority_records),
        "priority_with_reproduce_report": sum(record.reproduce_report for record in priority_records),
        "priority_reproduced_match": sum(
            record.report_status in PASS_REPORT_STATUSES and record.report_stale is False
            for record in priority_records
        ),
        "priority_stale_reports": sum(record.report_stale is True for record in priority_records),
        "priority_unverified": sum(
            not record.reproduce_report
            or record.report_status not in PASS_REPORT_STATUSES
            or record.report_stale is True
            for record in priority_records
        ),
        "priority_code_without_results": sum(
            record.classification == "not_reproducible_missing_archived_results"
            for record in priority_records
        ),
        "broken_reports": len(broken_reports),
        "stale_reports": sum(record.report_stale is True for record in records),
        "knowledge_base_readable": recorded_kids is not None,
        "results_without_knowledge": len(results_without_knowledge),
    }

    candidates = [record for record in priority_records if record.classification == "runnable"]
    candidates.sort(
        key=lambda record: (
            record.entrypoint != "reproduce.py",
            "recent_feed" not in record.priority_sources,
            record.experiment.casefold(),
        )
    )

    return {
        "schema_version": INVENTORY_SCHEMA,
        "generated_at": _utc_now(),
        "repo_head": _git_head(root),
        "scope": {
            "paper_sources": "paper/*/experiments.md plus canonical submission compile closures; README fallback only when both are absent",
            "recent_feed_articles": f"latest {feed_limit} records with status=published",
            "experiment_root": "experiments/",
        },
        "methodology_references": METHODOLOGY_REFERENCES,
        "references": refs,
        "reference_resolution": dict(sorted(resolved_refs.items())),
        "counts": counts,
        "report_status_counts": dict(sorted(status_counts.items())),
        "missing_priority_experiment_dirs": missing_refs,
        "priority_experiments": [asdict(record) for record in priority_records],
        "code_without_results": [asdict(record) for record in code_without_results],
        "results_without_knowledge": [asdict(record) for record in results_without_knowledge],
        "broken_reports": [asdict(record) for record in broken_reports],
        "sample_candidates": [asdict(record) for record in candidates],
    }


def build_status(root: Path = ROOT, feed_limit: int = 60) -> dict[str, Any]:
    """Build the daily-checkup projection without executing or writing anything."""
    inventory = build_inventory(root, feed_limit=feed_limit)
    counts = inventory["counts"]
    issues: list[dict[str, Any]] = []

    def add(code: str, severity: str, records: list[Any], message: str) -> None:
        ids = [item if isinstance(item, str) else item.get("experiment") for item in records]
        ids = [value for value in ids if value]
        issues.append(
            {
                "experiment_id": ids[0] if len(ids) == 1 else "aggregate",
                "experiment_ids": ids[:5],
                "count": len(ids),
                "code": code,
                "severity": severity,
                "message": message,
                "recovery": "uv run python scripts/reproduce_check.py inventory --no-write",
            }
        )

    mismatches = [item for item in inventory["broken_reports"] if item["report_status"] == "fail_mismatch"]
    failures = [item for item in inventory["broken_reports"] if item["report_status"] != "fail_mismatch"]
    stale = [item for item in inventory["priority_experiments"] if item["report_stale"] is True]
    unverified = [
        item
        for item in inventory["priority_experiments"]
        if (
            not item["reproduce_report"]
            or item["report_status"] not in PASS_REPORT_STATUSES
        )
        and item["classification"] != "not_reproducible_missing_archived_results"
    ]
    code_without = inventory["code_without_results"]
    missing = inventory["missing_priority_experiment_dirs"]
    if mismatches:
        add("RESULT_MISMATCH", "critical", mismatches, f"{len(mismatches)} reproduction report(s) disagree with canonical results")
    if failures:
        add("AUDIT_FAILED", "warn", failures, f"{len(failures)} reproduction audit(s) did not complete cleanly")
    if stale:
        add("REPORT_STALE", "warn", stale, f"{len(stale)} priority report(s) no longer match their audited subject hashes")
    if unverified:
        add(
            "PRIORITY_UNVERIFIED",
            "warn",
            unverified,
            f"{len(unverified)} referenced experiment(s) lack a current passing reproduction report",
        )
    if missing:
        add("PRIORITY_REFERENCE_UNRESOLVED", "warn", missing, f"{len(missing)} paper/feed reference(s) do not resolve to an experiment directory")
    if code_without:
        add("CODE_WITHOUT_RESULTS", "warn", code_without, f"{len(code_without)} K-family directories have code but no archived *_results.json")
    unrecorded = inventory["results_without_knowledge"]
    if unrecorded:
        add(
            "KNOWLEDGE_UNRECORDED",
            "warn",
            unrecorded,
            f"{len(unrecorded)} finished experiment(s) never reached knowledge.json — "
            "invisible to dedup/topic selection, so the pipeline can re-run them",
        )
    if not counts["knowledge_base_readable"]:
        add("KNOWLEDGE_BASE_UNREADABLE", "critical", [], "knowledge.json could not be parsed — coverage unknown")

    overall = "critical" if any(item["severity"] == "critical" for item in issues) else ("warn" if issues else "ok")
    return {
        "schema_version": STATUS_SCHEMA,
        "generated_at": _utc_now(),
        "overall_severity": overall,
        "counts": counts,
        "issues": issues,
    }


def _pointer_part(value: Any) -> str:
    return str(value).replace("~", "~0").replace("/", "~1")


def _flatten_scalars(
    value: Any,
    prefix: str = "",
    *,
    ignore_pointers: set[str] | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    ignored = ignore_pointers or set()
    if prefix in ignored:
        return out
    if isinstance(value, dict):
        if not value:
            out[prefix or "/"] = {"container": "object"}
        for key in sorted(value):
            child = f"{prefix}/{_pointer_part(key)}"
            out.update(_flatten_scalars(value[key], child, ignore_pointers=ignored))
    elif isinstance(value, list):
        if not value:
            out[prefix or "/"] = {"container": "array"}
        for index, item in enumerate(value):
            child = f"{prefix}/{index}"
            out.update(_flatten_scalars(item, child, ignore_pointers=ignored))
    else:
        out[prefix or "/"] = value
    return out


def compare_json(
    archived: Any,
    rerun: Any,
    *,
    rtol: float = DEFAULT_RTOL,
    atol: float = DEFAULT_ATOL,
    ignore_pointers: Iterable[str] = DEFAULT_IGNORE_POINTERS,
    mismatch_limit: int = 100,
) -> dict[str, Any]:
    ignored = set(ignore_pointers)
    left = _flatten_scalars(archived, ignore_pointers=ignored)
    right = _flatten_scalars(rerun, ignore_pointers=ignored)
    mismatches: list[dict[str, Any]] = []
    numeric_compared = 0
    matched = 0

    for path in sorted(set(left) | set(right)):
        if path not in left:
            mismatches.append({"path": path, "kind": "added", "archived": None, "rerun": right[path]})
            continue
        if path not in right:
            mismatches.append({"path": path, "kind": "missing", "archived": left[path], "rerun": None})
            continue
        old, new = left[path], right[path]
        if type(old) is float and type(new) is float:
            numeric_compared += 1
            threshold = atol + rtol * max(abs(old), abs(new))
            difference = abs(old - new)
            if difference <= threshold:
                matched += 1
                continue
            mismatches.append(
                {
                    "path": path,
                    "kind": "numeric_mismatch",
                    "archived": old,
                    "rerun": new,
                    "absolute_difference": difference,
                    "threshold": threshold,
                }
            )
        elif type(old) is type(new) and old == new:
            matched += 1
        else:
            mismatches.append(
                {"path": path, "kind": "value_mismatch", "archived": old, "rerun": new}
            )

    total_mismatches = len(mismatches)
    return {
        "rtol": rtol,
        "atol": atol,
        "ignore_pointers": sorted(ignored),
        "archived_scalar_count": len(left),
        "rerun_scalar_count": len(right),
        "numeric_compared": numeric_compared,
        "matched_scalars": matched,
        "mismatch_count": total_mismatches,
        "mismatches_truncated": total_mismatches > mismatch_limit,
        "mismatches": mismatches[:mismatch_limit],
    }


def _seed_evidence(entrypoint: Path) -> list[str]:
    try:
        lines = entrypoint.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        # An empty list reads as "this experiment sets no seed" — a real audit verdict.
        warn("reproduce_check", "seed scan could not read entrypoint", path=str(entrypoint), err=str(exc))
        return []
    return [f"{index}: {line.strip()}" for index, line in enumerate(lines, 1) if SEED_RE.search(line)][:20]


def _seed_evidence_for_paths(paths: Iterable[Path], root: Path) -> list[str]:
    evidence: list[str] = []
    for path in sorted(set(paths)):
        if path.suffix != ".py" or not path.is_file():
            continue
        prefix = path.relative_to(root).as_posix()
        evidence.extend(f"{prefix}:{line}" for line in _seed_evidence(path))
    return evidence[:100]


def _tail(value: str | bytes | None, limit: int = 4000) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    return value[-limit:]


def _subject_file_records(root: Path, paths: Iterable[Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for path in sorted(paths):
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        rel = resolved.relative_to(root.resolve())
        records.append({"path": rel.as_posix(), "sha256": _sha256(resolved), "size": resolved.stat().st_size})
    return records


def _subject_digest(records: Iterable[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for item in records:
        digest.update(str(item["path"]).encode())
        digest.update(b"\0")
        digest.update(str(item["sha256"]).encode())
        digest.update(b"\n")
    return digest.hexdigest()


def _hashes_unchanged(root: Path, records: Iterable[dict[str, Any]]) -> tuple[bool, list[str]]:
    changed: list[str] = []
    for item in records:
        path = root / item["path"]
        if not path.is_file() or _sha256(path) != item["sha256"]:
            changed.append(str(item["path"]))
    return not changed, changed


def _sandbox_profile(allowed_root: Path, *, network: str) -> str:
    # sandbox-exec resolves /tmp to /private/tmp before applying subpath rules.
    read_roots = {
        allowed_root.resolve(),
        Path(sys.prefix).resolve(),
        Path(sys.base_prefix).resolve(),
        Path("/Applications"),
        Path("/Library"),
        Path("/System"),
        Path("/dev"),
        Path("/private/etc"),
        Path("/private/var/db"),
        Path("/usr"),
        Path("/opt"),
    }

    def quoted(path: Path) -> str:
        return str(path).replace("\\", "\\\\").replace('"', '\\"')

    allowed = quoted(allowed_root.resolve())
    lines = [
        "(version 1)",
        '(import "system.sb")',
        "(deny default)",
        "(allow process*)",
        "(allow sysctl-read)",
        "(allow mach-lookup)",
        "(allow ipc-posix*)",
        "(allow dynamic-code-generation)",
        "(allow file-read-metadata)",
        '(allow file-read* file-test-existence (literal "/"))',
        f'(allow file-write* (subpath "{allowed}"))',
    ]
    lines.extend(
        f'(allow file-read* file-map-executable (subpath "{quoted(path)}"))'
        for path in sorted(read_roots, key=str)
        if path.exists()
    )
    lines.extend(
        f'(allow process-exec (subpath "{quoted(path)}"))'
        for path in sorted(read_roots, key=str)
        if path.exists()
    )
    if network == "allow":
        lines.append("(allow network*)")
    return "\n".join(lines) + "\n"


def _package_versions() -> dict[str, str | None]:
    names = ("numpy", "pandas", "scipy", "statsmodels", "arch", "yfinance", "scikit-learn")
    versions: dict[str, str | None] = {}
    for name in names:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def _set_outcome(
    report: dict[str, Any],
    *,
    status: str,
    reason_code: str,
    severity: str,
    reproducible: bool | None,
    summary: str,
) -> None:
    report["outcome"] = {
        "status": status,
        "reason_code": reason_code,
        "severity": severity,
        "reproducible": reproducible,
        "summary": summary,
    }


def _write_immutable_receipt(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        if _read_json_strict(path) != payload:
            raise FileExistsError(f"immutable reproduction receipt collision: {path}")
        return
    _atomic_write_json(path, payload)


def _finish_report(report: dict[str, Any], path: Path, write_report: bool) -> dict[str, Any]:
    if write_report:
        repo_root = path.parents[2]
        receipt_dir = repo_root / "storage" / "ops" / "reproducibility" / "runs" / path.parent.name
        if path.is_file():
            try:
                previous = _read_json_strict(path)
            except (OSError, ValueError, json.JSONDecodeError, AttributeError) as exc:
                # The prior report is about to be overwritten; failing to archive it loses audit history.
                raise RuntimeError(f"could not archive previous report {path}: {exc}") from exc
            if not isinstance(previous, dict):
                raise RuntimeError(f"could not archive non-object previous report {path}")
            stamp = re.sub(r"[^0-9A-Za-z]+", "", str(previous.get("generated_at", "unknown")))
            previous_receipt = receipt_dir / f"{stamp or 'unknown'}.json"
            # Do not catch receipt collisions: immutability violations must stop
            # the write before the latest report can be replaced.
            _write_immutable_receipt(previous_receipt, previous)
        stamp = re.sub(r"[^0-9A-Za-z]+", "", str(report.get("generated_at", "unknown")))
        _write_immutable_receipt(receipt_dir / f"{stamp or 'unknown'}.json", report)
        _atomic_write_json(path, report)
    return report


def _kill_process_tree(proc: subprocess.Popen[str]) -> bool:
    try:
        from scripts.dispatch_supervisor import procutil
    except ModuleNotFoundError:  # direct ``python scripts/reproduce_check.py``
        from dispatch_supervisor import procutil
    return bool(procutil.kill_tree(proc.pid))


def audit_experiment(
    experiment: str,
    *,
    root: Path = ROOT,
    timeout: int | None = None,
    write_report: bool = True,
) -> dict[str, Any]:
    exp_root = root / "experiments"
    matches = [path for path in exp_root.iterdir() if path.is_dir() and path.name.casefold() == experiment.casefold()]
    if len(matches) != 1:
        return {
            "schema_version": REPORT_SCHEMA,
            "generated_at": _utc_now(),
            "experiment_id": experiment,
            "outcome": {
                "status": "unverified",
                "reason_code": "EXPERIMENT_MISSING",
                "severity": "warn",
                "reproducible": None,
                "summary": "experiment directory was not found",
            },
        }

    exp_dir = matches[0]
    record = classify_experiment(exp_dir)
    spec, spec_error = load_spec(exp_dir)
    engine_path = Path(__file__).resolve()
    try:
        engine_rel = engine_path.relative_to(root.resolve()).as_posix()
    except ValueError:
        engine_rel = str(engine_path)
    engine_sha = _sha256(engine_path)
    report: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA,
        "generated_at": _utc_now(),
        "experiment_id": exp_dir.name,
        "engine": {
            "name": "scripts/reproduce_check.py",
            "schema": REPORT_SCHEMA,
            "path": engine_rel,
            "sha256": engine_sha,
            "committed_at_repo_head": _git_file_sha256(root, engine_rel) == engine_sha
            if not Path(engine_rel).is_absolute()
            else False,
        },
        "repo_head": _git_head(root),
        "methodology_references": METHODOLOGY_REFERENCES,
        "discovery": {"inventory_record": asdict(record), "subject_files": []},
        # Stamped up-front, not after the run: _report_is_stale() reads these five
        # fields to decide whether a report still describes the current tree, and
        # every early return below (SPEC_MISSING, SANDBOX_UNAVAILABLE, ...) writes a
        # report too. Filling them only on the success path made those reports
        # permanently stale — on Linux, where no sandbox exists, every report was.
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "machine": platform.machine(),
            "uv_lock_sha256": _sha256(root / "uv.lock") if (root / "uv.lock").exists() else None,
            "pythonhashseed": "0",
            "package_versions": _package_versions(),
        },
        "execution": None,
        "comparison": None,
        "integrity": None,
    }
    report_path = exp_dir / REPORT_NAME
    if record.classification != "runnable" or not record.entrypoint or not record.result_file or not spec:
        reason = "INVALID_SPEC" if (exp_dir / SPEC_NAME).exists() else "SPEC_MISSING"
        if record.classification == "not_reproducible_missing_archived_results":
            reason = "BASELINE_MISSING"
        elif record.classification == "not_reproducible_missing_code":
            reason = "CODE_MISSING"
        elif record.classification == "manual_mapping_required":
            reason = "AMBIGUOUS_DISCOVERY"
        _set_outcome(
            report,
            status="unverified",
            reason_code=reason,
            severity="warn",
            reproducible=None,
            summary=spec_error or record.blocker or "experiment is not safely runnable",
        )
        return _finish_report(report, report_path, write_report)

    randomness = spec.get("randomness")
    if not isinstance(randomness, dict) or randomness.get("status") not in {"declared", "not_applicable"}:
        _set_outcome(
            report,
            status="unverified",
            reason_code="SEED_UNDECLARED",
            severity="warn",
            reproducible=None,
            summary="reproduce_spec.json must declare randomness and seeds",
        )
        return _finish_report(report, report_path, write_report)

    entry_rel = Path("experiments") / exp_dir.name / record.entrypoint
    result_rel = Path("experiments") / exp_dir.name / record.result_file
    input_paths = [root / _safe_relative_path(item["path"], field="inputs.path") for item in spec["inputs"]]
    missing_inputs = [str(path.relative_to(root)) for path in input_paths if not path.is_file()]
    bad_inputs = [
        str(path.relative_to(root))
        for path, item in zip(input_paths, spec["inputs"])
        if path.is_file() and _sha256(path) != item["sha256"]
    ]
    if missing_inputs or bad_inputs:
        _set_outcome(
            report,
            status="unverified",
            reason_code="INPUT_MISSING" if missing_inputs else "INPUT_HASH_MISMATCH",
            severity="warn",
            reproducible=None,
            summary=f"missing={missing_inputs}; hash_mismatch={bad_inputs}",
        )
        return _finish_report(report, report_path, write_report)

    subject_paths = [root / entry_rel, root / result_rel, exp_dir / SPEC_NAME, *input_paths]
    subject_paths.extend(_code_surface_files(exp_dir))
    try:
        engine_path.relative_to(root.resolve())
    except ValueError:
        pass  # silent-ok: engine outside the repo is not a subject file, not a failure
    else:
        subject_paths.append(engine_path)
    subject_records = _subject_file_records(root, subject_paths)
    seed_evidence = _seed_evidence_for_paths(subject_paths, root)
    if randomness["status"] == "declared":
        missing_seed_values = [
            seed["value"]
            for seed in randomness["seeds"]
            if str(seed["value"]) not in "\n".join(seed_evidence)
        ]
        if missing_seed_values:
            _set_outcome(
                report,
                status="unverified",
                reason_code="SEED_DECLARATION_UNVERIFIED",
                severity="warn",
                reproducible=None,
                summary=f"declared seed values lack code evidence: {missing_seed_values}",
            )
            return _finish_report(report, report_path, write_report)
    report["discovery"].update(
        {
            "entrypoint": entry_rel.as_posix(),
            "canonical_result": result_rel.as_posix(),
            "spec_sha256": _sha256(exp_dir / SPEC_NAME),
            "subject_files": subject_records,
            "subject_sha256": _subject_digest(subject_records),
        }
    )
    baseline_bytes = (root / result_rel).read_bytes()
    try:
        archived_json = _loads_json_strict(baseline_bytes)
    except (ValueError, json.JSONDecodeError) as exc:
        _set_outcome(
            report,
            status="unverified",
            reason_code="INVALID_CANONICAL_JSON",
            severity="warn",
            reproducible=None,
            summary=str(exc),
        )
        return _finish_report(report, report_path, write_report)

    started = time.monotonic()
    try:
        with tempfile.TemporaryDirectory(prefix="volpred-reproduce-") as tmp:
            temp_root = Path(tmp).resolve()
            sandbox = Path(tmp) / "repo"
            clone = subprocess.run(
                ["git", "clone", "--quiet", "--shared", "--no-checkout", str(root), str(sandbox)],
                capture_output=True,
                text=True,
                check=False,
            )
            if clone.returncode != 0:
                report["execution"] = {"stderr_tail": _tail(clone.stderr), "exit_code": clone.returncode}
                _set_outcome(report, status="error", reason_code="SNAPSHOT_CHECKOUT_FAILED", severity="warn", reproducible=None, summary="git clone failed")
                return _finish_report(report, report_path, write_report)
            checkout = subprocess.run(
                ["git", "checkout", "--quiet", "--detach", report["repo_head"] or "HEAD"],
                cwd=sandbox,
                capture_output=True,
                text=True,
                check=False,
            )
            if checkout.returncode != 0:
                report["execution"] = {"stderr_tail": _tail(checkout.stderr), "exit_code": checkout.returncode}
                _set_outcome(report, status="error", reason_code="SNAPSHOT_CHECKOUT_FAILED", severity="warn", reproducible=None, summary="git checkout failed")
                return _finish_report(report, report_path, write_report)

            sandbox_entry = sandbox / entry_rel
            sandbox_result = sandbox / result_rel
            checkout_mismatches = []
            for item in subject_records:
                checkout_path = sandbox / item["path"]
                if not checkout_path.is_file() or _sha256(checkout_path) != item["sha256"]:
                    checkout_mismatches.append(item["path"])
            if checkout_mismatches:
                _set_outcome(
                    report,
                    status="unverified",
                    reason_code="WORKING_TREE_DRIFT",
                    severity="warn",
                    reproducible=None,
                    summary=f"committed snapshot differs for: {checkout_mismatches}",
                )
                return _finish_report(report, report_path, write_report)

            sandbox_result.unlink()
            runtime_dir = temp_root / "runtime"
            runtime_dir.mkdir()
            profile_path = temp_root / "reproduce.sb"
            if platform.system() != "Darwin" or not Path("/usr/bin/sandbox-exec").is_file():
                _set_outcome(report, status="unverified", reason_code="SANDBOX_UNAVAILABLE", severity="warn", reproducible=None, summary="OS write/network sandbox is unavailable")
                return _finish_report(report, report_path, write_report)
            profile_path.write_text(_sandbox_profile(temp_root, network=spec.get("network", "deny")), encoding="utf-8")
            env = os.environ.copy()
            env["PYTHONHASHSEED"] = "0"
            env["MPLBACKEND"] = "Agg"
            env["PYTHONPATH"] = str(sandbox / "src")
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            env["HOME"] = str(runtime_dir)
            env["TMPDIR"] = str(runtime_dir)
            env["XDG_CACHE_HOME"] = str(runtime_dir / "xdg")
            env["MPLCONFIGDIR"] = str(runtime_dir / "mpl")
            env["NUMBA_CACHE_DIR"] = str(runtime_dir / "numba")
            env["VOLPRED_NO_EMAIL"] = "1"
            env["VOLPRED_NO_REMOTE_WRITE"] = "1"
            env["VOLPRED_NO_REMOTE_READ"] = "1"
            env["VOLPRED_NO_CANONICAL_WRITE"] = "1"
            child_command = [sys.executable, str(sandbox_entry), *spec["entrypoint"].get("args", [])]
            command = ["/usr/bin/sandbox-exec", "-f", str(profile_path), *child_command]
            effective_timeout = min(timeout, spec["timeout_seconds"]) if timeout else spec["timeout_seconds"]
            proc = subprocess.Popen(
                command,
                cwd=sandbox,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
            try:
                stdout, stderr = proc.communicate(timeout=effective_timeout)
            except subprocess.TimeoutExpired as first_timeout:
                killed = _kill_process_tree(proc)
                try:
                    stdout, stderr = proc.communicate(timeout=5)
                except subprocess.TimeoutExpired as drain_timeout:
                    killed = False
                    stdout = drain_timeout.stdout or first_timeout.stdout or ""
                    stderr = drain_timeout.stderr or first_timeout.stderr or ""
                    if proc.stdout:
                        proc.stdout.close()
                    if proc.stderr:
                        proc.stderr.close()
                report["execution"] = {
                    "command": [sys.executable, entry_rel.as_posix(), *spec["entrypoint"].get("args", [])],
                    "backend": "macos_sandbox_exec",
                    "network": spec.get("network", "deny"),
                    "timeout_seconds": effective_timeout,
                    "duration_seconds": round(time.monotonic() - started, 3),
                    "stdout_tail": _tail(stdout),
                    "stderr_tail": _tail(stderr),
                    "kill_confirmed": killed,
                }
                intact, changed = _hashes_unchanged(root, subject_records)
                report["integrity"] = {"canonical_unchanged": intact, "changed_paths": changed}
                reason = "TIMEOUT_KILLED" if killed else "TIMEOUT_KILL_UNVERIFIED"
                severity = "warn" if killed else "critical"
                _set_outcome(report, status="timeout", reason_code=reason, severity=severity, reproducible=None, summary=f"experiment exceeded {effective_timeout}s timeout")
                return _finish_report(report, report_path, write_report)

            execution = {
                "command": [sys.executable, entry_rel.as_posix(), *spec["entrypoint"].get("args", [])],
                "backend": "macos_sandbox_exec",
                "network": spec.get("network", "deny"),
                "exit_code": proc.returncode,
                "timeout_seconds": effective_timeout,
                "duration_seconds": round(time.monotonic() - started, 3),
                "stdout_sha256": hashlib.sha256(stdout.encode()).hexdigest(),
                "stderr_sha256": hashlib.sha256(stderr.encode()).hexdigest(),
                "stdout_tail": _tail(stdout),
                "stderr_tail": _tail(stderr),
                "clean_snapshot": True,
                "sandbox_removed_after_run": True,
            }
            report["execution"] = execution
            intact, changed = _hashes_unchanged(root, subject_records)
            report["integrity"] = {"canonical_unchanged": intact, "changed_paths": changed}
            if not intact:
                _set_outcome(report, status="error", reason_code="CANONICAL_MUTATION_DETECTED", severity="critical", reproducible=None, summary=f"canonical files changed: {changed}")
                return _finish_report(report, report_path, write_report)
            if proc.returncode != 0:
                _set_outcome(report, status="error", reason_code="NONZERO_EXIT", severity="warn", reproducible=None, summary=f"experiment exited {proc.returncode}")
                return _finish_report(report, report_path, write_report)
            if not sandbox_result.exists():
                _set_outcome(report, status="error", reason_code="OUTPUT_MISSING", severity="warn", reproducible=None, summary="exit 0 but canonical result was not regenerated")
                return _finish_report(report, report_path, write_report)
            try:
                sandbox_result.resolve().relative_to(sandbox.resolve())
            except ValueError:
                _set_outcome(report, status="error", reason_code="OUTPUT_PATH_ESCAPE", severity="critical", reproducible=None, summary="regenerated result resolves outside the disposable clone")
                return _finish_report(report, report_path, write_report)
            result_stat = sandbox_result.lstat()
            if sandbox_result.is_symlink() or not stat.S_ISREG(result_stat.st_mode) or result_stat.st_nlink != 1:
                _set_outcome(report, status="error", reason_code="OUTPUT_UNSAFE_FILE_TYPE", severity="critical", reproducible=None, summary="regenerated result must be a non-linked regular file")
                return _finish_report(report, report_path, write_report)

            try:
                rerun_json = _read_json_strict(sandbox_result)
            except (ValueError, json.JSONDecodeError) as exc:
                _set_outcome(report, status="error", reason_code="OUTPUT_INVALID_JSON", severity="warn", reproducible=None, summary=str(exc))
                return _finish_report(report, report_path, write_report)
            comparison_spec = spec.get("comparison", {})
            comparison = compare_json(
                archived_json,
                rerun_json,
                rtol=float(comparison_spec.get("rtol", DEFAULT_RTOL)),
                atol=float(comparison_spec.get("atol", DEFAULT_ATOL)),
                ignore_pointers=comparison_spec.get("ignore_pointers", sorted(DEFAULT_IGNORE_POINTERS)),
            )
            comparison["ignore_reasons"] = comparison_spec.get("ignore_reasons", {})
            report["comparison"] = comparison
            rerun_sha = _sha256(sandbox_result)
            report["canonical_results"] = [{
                "archived_result": result_rel.as_posix(),
                "archived_sha256": hashlib.sha256(baseline_bytes).hexdigest(),
                "rerun_sha256": rerun_sha,
                "bit_identical": hashlib.sha256(baseline_bytes).hexdigest() == rerun_sha,
            }]
            report["environment"].update({
                "seed_evidence": seed_evidence,
                "declared_randomness": randomness,
            })
            if comparison["mismatch_count"]:
                _set_outcome(report, status="fail_mismatch", reason_code="RESULT_MISMATCH", severity="critical", reproducible=False, summary=f"{comparison['mismatch_count']} scalar mismatches")
            elif spec.get("network", "deny") != "deny":
                _set_outcome(report, status="unverified", reason_code="NETWORK_ALLOWED", severity="warn", reproducible=None, summary="matching output used a network-enabled execution and is not a pinned reproduction")
            elif report["canonical_results"][0]["bit_identical"]:
                _set_outcome(report, status="pass_exact", reason_code="BIT_IDENTICAL", severity="info", reproducible=True, summary="regenerated result is bit-identical")
            else:
                _set_outcome(report, status="pass_tolerated", reason_code="WITHIN_PREDECLARED_TOLERANCE", severity="info", reproducible=True, summary="all scalar values match within predeclared tolerance")
    except (OSError, ValueError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        report["execution"] = {
            "duration_seconds": round(time.monotonic() - started, 3),
            "error": f"{type(exc).__name__}: {exc}",
        }
        intact, changed = _hashes_unchanged(root, subject_records)
        report["integrity"] = {"canonical_unchanged": intact, "changed_paths": changed}
        reason = "CANONICAL_MUTATION_DETECTED" if not intact else "AUDIT_INTERNAL_ERROR"
        severity = "critical" if not intact else "warn"
        _set_outcome(report, status="error", reason_code=reason, severity=severity, reproducible=None, summary=f"{type(exc).__name__}: {exc}")

    return _finish_report(report, report_path, write_report)


def _inventory_output_path(root: Path, value: str | None) -> Path:
    path = Path(value) if value else DEFAULT_INVENTORY
    return path if path.is_absolute() else root / path


def _print_summary(inventory: dict[str, Any]) -> None:
    counts = inventory["counts"]
    print(
        "[reproduce] "
        f"experiments={counts['experiment_dirs']} runnable={counts['runnable']} "
        f"reports={counts['with_reproduce_report']} code_without_results={counts['code_without_results']}"
    )
    print(
        "[reproduce] priority "
        f"refs={counts['priority_refs']} existing={counts['priority_existing']} "
        f"runnable={counts['priority_runnable']} matched={counts['priority_reproduced_match']} "
        f"missing_dirs={counts['priority_missing_dirs']}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(ROOT), help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="command", required=True)

    inventory_cmd = sub.add_parser("inventory", help="Fast read-only inventory; no experiment execution.")
    inventory_cmd.add_argument("--feed-limit", type=int, default=60)
    inventory_cmd.add_argument("--output", default=None)
    inventory_cmd.add_argument("--no-write", action="store_true")

    run_cmd = sub.add_parser("run", help="Re-run one or more experiments in disposable clean clones.")
    run_cmd.add_argument("--experiment", action="append", required=True)
    run_cmd.add_argument("--timeout", type=int, default=None, help="Optional stricter operational timeout.")
    run_cmd.add_argument("--output", default=None)

    sample_cmd = sub.add_parser("sample", help="Run a bounded priority sample.")
    sample_cmd.add_argument("--limit", type=int, default=3)
    sample_cmd.add_argument("--timeout", type=int, default=None, help="Optional stricter operational timeout.")
    sample_cmd.add_argument("--feed-limit", type=int, default=60)
    sample_cmd.add_argument("--output", default=None)

    args = parser.parse_args()
    root = Path(args.root).resolve()

    if args.command == "inventory":
        inventory = build_inventory(root, feed_limit=args.feed_limit)
        if not args.no_write:
            _atomic_write_json(_inventory_output_path(root, args.output), inventory)
        _print_summary(inventory)
        return 0

    if args.command == "run":
        reports = [
            audit_experiment(
                experiment,
                root=root,
                timeout=args.timeout,
            )
            for experiment in args.experiment
        ]
    else:
        inventory = build_inventory(root, feed_limit=args.feed_limit)
        candidates = [item["experiment"] for item in inventory["sample_candidates"][: args.limit]]
        if not candidates:
            print("[reproduce] no priority experiment has a valid reproduce_spec.json", file=sys.stderr)
            return 2
        reports = [
            audit_experiment(
                experiment,
                root=root,
                timeout=args.timeout,
            )
            for experiment in candidates
        ]

    for report in reports:
        outcome = report["outcome"]
        print(f"[reproduce] {report['experiment_id']}: {outcome['status']} ({outcome['reason_code']})")
    inventory = build_inventory(root)
    _atomic_write_json(_inventory_output_path(root, args.output), inventory)
    _print_summary(inventory)
    statuses = {report["outcome"]["status"] for report in reports}
    reasons = {report["outcome"]["reason_code"] for report in reports}
    if "TIMEOUT_KILL_UNVERIFIED" in reasons:
        return 125
    if "timeout" in statuses:
        return 124
    if "error" in statuses:
        return 3
    if "unverified" in statuses:
        return 2
    if "fail_mismatch" in statuses:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
