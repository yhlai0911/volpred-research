from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import fcntl

from .common import project_path

EXPERIMENT_ID_PATTERN = re.compile(r"^([A-Za-z]\d+[A-Za-z0-9]*)")
TEXT_REFERENCE_EXTENSIONS = {".py", ".md", ".json", ".txt", ".yaml", ".yml", ".tex", ".sh"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_root(root_path: str | Path | None = None) -> Path:
    return Path(root_path) if root_path is not None else project_path()


def _experiments_root(root_path: str | Path | None = None) -> Path:
    return _resolve_root(root_path) / "experiments"


def _relative(path: Path, *, root_path: Path) -> str:
    try:
        return str(path.relative_to(root_path))
    except ValueError:
        return str(path)


def _resolve_repo_file(path_value: str | Path, *, root_path: Path) -> tuple[Path, str]:
    path = Path(path_value)
    if not path.is_absolute():
        path = root_path / path
    resolved = path.resolve()
    root_resolved = root_path.resolve()
    try:
        relative = resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError(f"{path_value} is outside the project root") from exc
    return resolved, str(relative)


def infer_experiment_id(name: str) -> str | None:
    match = EXPERIMENT_ID_PATTERN.match(name)
    if not match:
        return None
    return match.group(1)


def _loose_files(root_path: str | Path | None = None) -> list[Path]:
    experiments_root = _experiments_root(root_path)
    if not experiments_root.exists():
        return []
    return sorted(path for path in experiments_root.iterdir() if path.is_file())


def _group_loose_files(root_path: str | Path | None = None) -> tuple[dict[str, list[Path]], list[Path]]:
    grouped: dict[str, list[Path]] = defaultdict(list)
    ungrouped: list[Path] = []
    for path in _loose_files(root_path):
        experiment_id = infer_experiment_id(path.stem)
        if experiment_id:
            grouped[experiment_id].append(path)
        else:
            ungrouped.append(path)
    return dict(grouped), ungrouped


def _canonical_dir(experiment_id: str, *, root_path: str | Path | None = None) -> Path:
    return _experiments_root(root_path) / experiment_id


def _canonical_script_path(experiment_id: str, *, root_path: str | Path | None = None) -> Path:
    return _canonical_dir(experiment_id, root_path=root_path) / f"{experiment_id}.py"


def _canonical_results_path(experiment_id: str, *, root_path: str | Path | None = None) -> Path:
    return _canonical_dir(experiment_id, root_path=root_path) / f"{experiment_id}_results.json"


def _canonical_readme_path(experiment_id: str, *, root_path: str | Path | None = None) -> Path:
    return _canonical_dir(experiment_id, root_path=root_path) / "README.md"


def _detect_target_name(experiment_id: str, source: Path) -> str:
    lower_name = source.name.lower()
    lower_id = experiment_id.lower()

    if lower_name in {f"{lower_id}_readme.md", f"{lower_id}-readme.md"}:
        return "README.md"
    if lower_name == f"{lower_id}.py":
        return f"{experiment_id}.py"
    if lower_name == f"{lower_id}_results.json":
        return f"{experiment_id}_results.json"
    return source.name


def _collect_reference_hits(
    relative_path: str,
    *,
    root_path: Path,
    max_hits: int | None = 10,
) -> dict[str, Any]:
    result = subprocess.run(
        [
            "rg",
            "-n",
            "-F",
            "--color",
            "never",
            "--glob",
            "!frontend-v2-fix/.next/**",
            "--glob",
            "!.git/**",
            "--glob",
            "!storage/ops/rollback_points/**",
            relative_path,
            ".",
        ],
        cwd=root_path,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode not in {0, 1}:
        raise RuntimeError(result.stderr.strip() or f"rg failed while searching for {relative_path}")

    hits: list[dict[str, Any]] = []
    for line in result.stdout.splitlines():
        parts = line.split(":", 2)
        if len(parts) < 3:
            continue
        file_path, line_number, preview = parts
        normalized_path = file_path[2:] if file_path.startswith("./") else file_path
        hits.append(
            {
                "path": normalized_path,
                "line": int(line_number),
                "preview": preview.strip(),
            }
        )

    sample = hits if max_hits is None else hits[: max(max_hits, 0)]
    return {"count": len(hits), "sample": sample}


def _rewrite_path_references(
    source_relative: str,
    target_relative: str,
    *,
    root_path: Path,
) -> list[dict[str, Any]]:
    hits = _collect_reference_hits(source_relative, root_path=root_path, max_hits=None)["sample"]
    touched: list[dict[str, Any]] = []
    rewritten: set[str] = set()

    for hit in hits:
        file_relative = str(hit["path"])
        if file_relative in rewritten:
            continue
        rewritten.add(file_relative)

        target_file = root_path / file_relative
        if target_file.suffix.lower() not in TEXT_REFERENCE_EXTENSIONS:
            touched.append({"path": file_relative, "updated": False, "reason": "unsupported-extension"})
            continue

        try:
            with target_file.open("r+", encoding="utf-8") as handle:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    original = handle.read()
                    replaced = original.replace(source_relative, target_relative)
                    if replaced == original:
                        touched.append({"path": file_relative, "updated": False, "reason": "no-op"})
                        continue

                    handle.seek(0)
                    handle.write(replaced)
                    handle.truncate()
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except UnicodeDecodeError:
            touched.append({"path": file_relative, "updated": False, "reason": "non-utf8"})
            continue

        touched.append({"path": file_relative, "updated": True, "reason": "rewritten"})

    return touched


def build_experiments_report(
    *,
    root_path: str | Path | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    root = _resolve_root(root_path)
    experiments_root = _experiments_root(root)
    grouped, ungrouped = _group_loose_files(root)
    loose_files = _loose_files(root)
    extension_counts = Counter(path.suffix or "<no_ext>" for path in loose_files)
    top_level_dirs = sorted(path for path in experiments_root.iterdir() if path.is_dir()) if experiments_root.exists() else []

    candidates: list[dict[str, Any]] = []
    for experiment_id, files in grouped.items():
        experiment_dir = _canonical_dir(experiment_id, root_path=root)
        candidates.append(
            {
                "experiment_id": experiment_id,
                "loose_count": len(files),
                "loose_files": [_relative(path, root_path=root) for path in files],
                "has_experiment_dir": experiment_dir.exists(),
                "has_readme": _canonical_readme_path(experiment_id, root_path=root).exists(),
                "has_canonical_script": _canonical_script_path(experiment_id, root_path=root).exists(),
                "has_canonical_results": _canonical_results_path(experiment_id, root_path=root).exists(),
                "recommended_action": "migrate_touched" if experiment_dir.exists() else "scaffold_then_migrate",
            }
        )

    candidates.sort(key=lambda item: (-int(item["loose_count"]), str(item["experiment_id"])))

    return {
        "experiments_root": _relative(experiments_root, root_path=root),
        "top_level_dir_count": len(top_level_dirs),
        "loose_file_count": len(loose_files),
        "loose_files_by_extension": dict(sorted(extension_counts.items())),
        "candidate_count": len(candidates),
        "grouped_candidates": candidates[: max(limit, 0)],
        "ungrouped_loose_files": [_relative(path, root_path=root) for path in ungrouped[: max(limit, 0)]],
    }


def _readme_template(experiment_id: str, title: str | None = None) -> str:
    heading = title.strip() if title else experiment_id
    return (
        f"# {heading}\n\n"
        f"- Experiment ID: `{experiment_id}`\n"
        f"- Status: planning\n"
        f"- Created At: {_utc_now()}\n\n"
        "## 問題描述\n\n"
        "- 待補充\n\n"
        "## 動機\n\n"
        "- 待補充\n\n"
        "## 方法\n\n"
        "- 待補充\n\n"
        "## 預期\n\n"
        "- 待補充\n\n"
        "## 結論\n\n"
        "- 待補充\n"
    )


def _script_template(experiment_id: str) -> str:
    return (
        'from __future__ import annotations\n\n'
        'import json\n'
        'from pathlib import Path\n\n\n'
        f'EXPERIMENT_ID = "{experiment_id}"\n\n\n'
        'def main() -> None:\n'
        '    base_dir = Path(__file__).resolve().parent\n'
        '    output_path = base_dir / f"{EXPERIMENT_ID}_results.json"\n'
        '    payload = {\n'
        '        "experiment_id": EXPERIMENT_ID,\n'
        '        "status": "draft",\n'
        '        "notes": ["replace with actual experiment output"],\n'
        '    }\n'
        '    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\\n", encoding="utf-8")\n'
        '    print(f"Wrote {output_path}")\n\n\n'
        'if __name__ == "__main__":\n'
        '    main()\n'
    )


def _results_template(experiment_id: str, title: str | None = None) -> dict[str, Any]:
    return {
        "experiment_id": experiment_id,
        "title": title.strip() if title else experiment_id,
        "status": "draft",
        "created_at": _utc_now(),
        "data_sources": [],
        "summary": "",
        "metrics": {},
        "notes": [],
    }


def _needs_gitkeep(directory: Path) -> bool:
    if not directory.exists():
        return True
    try:
        next(directory.iterdir())
    except StopIteration:
        return True
    return False


def build_experiment_scaffold_plan(
    experiment_id: str,
    *,
    title: str | None = None,
    root_path: str | Path | None = None,
    create_script: bool = True,
    create_results: bool = True,
) -> dict[str, Any]:
    root = _resolve_root(root_path)
    planned_create: list[str] = []
    existing: list[str] = []

    target_dir = _canonical_dir(experiment_id, root_path=root)
    readme_path = _canonical_readme_path(experiment_id, root_path=root)
    script_path = _canonical_script_path(experiment_id, root_path=root)
    results_path = _canonical_results_path(experiment_id, root_path=root)

    for child in ("references", "data"):
        child_dir = target_dir / child
        gitkeep = child_dir / ".gitkeep"
        if _needs_gitkeep(child_dir):
            planned_create.append(_relative(gitkeep, root_path=root))
        elif gitkeep.exists():
            existing.append(_relative(gitkeep, root_path=root))

    if readme_path.exists():
        existing.append(_relative(readme_path, root_path=root))
    else:
        planned_create.append(_relative(readme_path, root_path=root))

    if create_script:
        if script_path.exists():
            existing.append(_relative(script_path, root_path=root))
        else:
            planned_create.append(_relative(script_path, root_path=root))

    if create_results:
        if results_path.exists():
            existing.append(_relative(results_path, root_path=root))
        else:
            planned_create.append(_relative(results_path, root_path=root))

    return {
        "experiment_id": experiment_id,
        "target_dir": _relative(target_dir, root_path=root),
        "planned_create": planned_create,
        "existing": existing,
        "title": title.strip() if title else None,
    }


def scaffold_experiment(
    experiment_id: str,
    *,
    title: str | None = None,
    root_path: str | Path | None = None,
    create_script: bool = True,
    create_results: bool = True,
    overwrite: bool = False,
) -> dict[str, Any]:
    root = _resolve_root(root_path)
    target_dir = _canonical_dir(experiment_id, root_path=root)
    created: list[str] = []
    skipped: list[str] = []

    target_dir.mkdir(parents=True, exist_ok=True)
    for child in ("references", "data"):
        child_dir = target_dir / child
        child_dir.mkdir(parents=True, exist_ok=True)
        gitkeep = child_dir / ".gitkeep"
        if _needs_gitkeep(child_dir):
            if gitkeep.exists() and not overwrite:
                skipped.append(_relative(gitkeep, root_path=root))
            else:
                gitkeep.write_text("", encoding="utf-8")
                created.append(_relative(gitkeep, root_path=root))
        elif gitkeep.exists():
            skipped.append(_relative(gitkeep, root_path=root))

    readme_path = _canonical_readme_path(experiment_id, root_path=root)
    if readme_path.exists() and not overwrite:
        skipped.append(_relative(readme_path, root_path=root))
    else:
        readme_path.write_text(_readme_template(experiment_id, title), encoding="utf-8")
        created.append(_relative(readme_path, root_path=root))

    if create_script:
        script_path = _canonical_script_path(experiment_id, root_path=root)
        if script_path.exists() and not overwrite:
            skipped.append(_relative(script_path, root_path=root))
        else:
            script_path.write_text(_script_template(experiment_id), encoding="utf-8")
            created.append(_relative(script_path, root_path=root))

    if create_results:
        results_path = _canonical_results_path(experiment_id, root_path=root)
        if results_path.exists() and not overwrite:
            skipped.append(_relative(results_path, root_path=root))
        else:
            results_path.write_text(
                json.dumps(_results_template(experiment_id, title), indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            created.append(_relative(results_path, root_path=root))

    return {
        "experiment_id": experiment_id,
        "target_dir": _relative(target_dir, root_path=root),
        "created": created,
        "skipped": skipped,
    }


def build_experiment_migration_plan(
    experiment_id: str,
    *,
    root_path: str | Path | None = None,
) -> dict[str, Any]:
    root = _resolve_root(root_path)
    experiment_dir = _canonical_dir(experiment_id, root_path=root)
    matching = [
        path for path in _loose_files(root)
        if (infer_experiment_id(path.stem) or "").lower() == experiment_id.lower()
    ]

    moves: list[dict[str, str]] = []
    conflicts: list[dict[str, str]] = []
    for source in matching:
        target = experiment_dir / _detect_target_name(experiment_id, source)
        source_relative = _relative(source, root_path=root)
        target_relative = _relative(target, root_path=root)
        reference_hits = _collect_reference_hits(source_relative, root_path=root)
        if target.exists() and source.resolve() != target.resolve():
            conflicts.append(
                {
                    "source": source_relative,
                    "target": target_relative,
                    "reference_hit_count": reference_hits["count"],
                    "reference_hit_sample": reference_hits["sample"],
                }
            )
            continue
        moves.append(
            {
                "source": source_relative,
                "target": target_relative,
                "reference_hit_count": reference_hits["count"],
                "reference_hit_sample": reference_hits["sample"],
            }
        )

    return {
        "experiment_id": experiment_id,
        "experiment_dir": _relative(experiment_dir, root_path=root),
        "loose_matches": [_relative(path, root_path=root) for path in matching],
        "moves": moves,
        "conflicts": conflicts,
        "has_existing_dir": experiment_dir.exists(),
    }


def migrate_experiment_files(
    experiment_id: str,
    *,
    root_path: str | Path | None = None,
    apply_changes: bool = False,
    ensure_scaffold: bool = True,
    rewrite_references: bool = False,
    overwrite: bool = False,
    title: str | None = None,
) -> dict[str, Any]:
    root = _resolve_root(root_path)
    plan = build_experiment_migration_plan(experiment_id, root_path=root)
    scaffold_plan = build_experiment_scaffold_plan(
        experiment_id,
        title=title,
        root_path=root,
        create_script=False,
        create_results=False,
    )
    created: list[str] = []
    moved: list[dict[str, str]] = []
    reference_updates: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = [] if overwrite else list(plan["conflicts"])

    if ensure_scaffold and apply_changes:
        scaffold_result = scaffold_experiment(
            experiment_id,
            title=title,
            root_path=root,
            create_script=False,
            create_results=False,
            overwrite=overwrite,
        )
        created.extend(scaffold_result["created"])

    if apply_changes:
        pending_moves = list(plan["moves"])
        if overwrite:
            pending_moves.extend(plan["conflicts"])

        for item in pending_moves:
            source = root / item["source"]
            target = root / item["target"]
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                if overwrite:
                    if target.is_dir():
                        shutil.rmtree(target)
                    else:
                        target.unlink()
                else:
                    conflicts.append(item)
                    continue
            source.rename(target)
            moved.append(item)

        if rewrite_references:
            for item in moved:
                reference_updates.append(
                    {
                        "source": item["source"],
                        "target": item["target"],
                        "files": _rewrite_path_references(item["source"], item["target"], root_path=root),
                    }
                )

    return {
        **plan,
        "apply_changes": apply_changes,
        "rewrite_references": rewrite_references,
        "planned_created": scaffold_plan["planned_create"] if ensure_scaffold else [],
        "created": created,
        "moved": moved,
        "conflicts": conflicts,
        "reference_updates": reference_updates,
        "dry_run": not apply_changes,
    }


def adopt_experiment_files(
    experiment_id: str,
    *,
    source_files: list[str] | tuple[str, ...],
    root_path: str | Path | None = None,
    apply_changes: bool = False,
    ensure_scaffold: bool = True,
    rewrite_references: bool = False,
    overwrite: bool = False,
    title: str | None = None,
    create_placeholder_script: bool | None = None,
    create_placeholder_results: bool | None = None,
) -> dict[str, Any]:
    root = _resolve_root(root_path)
    target_dir = _canonical_dir(experiment_id, root_path=root)
    if not source_files:
        raise ValueError("source_files must not be empty")

    resolved_sources: list[tuple[Path, str]] = []
    seen_relative: set[str] = set()
    for value in source_files:
        source_path, source_relative = _resolve_repo_file(value, root_path=root)
        if not source_path.exists():
            raise FileNotFoundError(source_relative)
        if not source_path.is_file():
            raise ValueError(f"{source_relative} is not a file")
        if source_relative in seen_relative:
            continue
        seen_relative.add(source_relative)
        resolved_sources.append((source_path, source_relative))

    py_sources = [item for item in resolved_sources if item[0].suffix.lower() == ".py"]
    json_sources = [item for item in resolved_sources if item[0].suffix.lower() == ".json"]

    placeholder_script = create_placeholder_script if create_placeholder_script is not None else len(py_sources) == 0
    placeholder_results = create_placeholder_results if create_placeholder_results is not None else len(json_sources) == 0

    moves: list[dict[str, Any]] = []
    plan_conflicts: list[dict[str, Any]] = []
    for source_path, source_relative in resolved_sources:
        if source_path.suffix.lower() == ".py" and len(py_sources) == 1:
            target_name = f"{experiment_id}.py"
        elif source_path.suffix.lower() == ".json" and len(json_sources) == 1:
            target_name = f"{experiment_id}_results.json"
        else:
            target_name = source_path.name

        target = target_dir / target_name
        target_relative = _relative(target, root_path=root)
        reference_hits = _collect_reference_hits(source_relative, root_path=root)
        item = {
            "source": source_relative,
            "target": target_relative,
            "reference_hit_count": reference_hits["count"],
            "reference_hit_sample": reference_hits["sample"],
        }

        if target.exists() and source_path.resolve() != target.resolve():
            plan_conflicts.append(item)
            continue
        moves.append(item)

    scaffold_plan = build_experiment_scaffold_plan(
        experiment_id,
        title=title,
        root_path=root,
        create_script=placeholder_script,
        create_results=placeholder_results,
    )

    created: list[str] = []
    moved: list[dict[str, str]] = []
    reference_updates: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = [] if overwrite else list(plan_conflicts)

    if ensure_scaffold and apply_changes:
        scaffold_result = scaffold_experiment(
            experiment_id,
            title=title,
            root_path=root,
            create_script=placeholder_script,
            create_results=placeholder_results,
            overwrite=overwrite,
        )
        created.extend(scaffold_result["created"])

    if apply_changes:
        pending_moves = list(moves)
        if overwrite:
            pending_moves.extend(item for item in plan_conflicts if item not in pending_moves)

        for item in pending_moves:
            source = root / item["source"]
            target = root / item["target"]
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                if overwrite:
                    if target.is_dir():
                        shutil.rmtree(target)
                    else:
                        target.unlink()
                else:
                    conflicts.append(item)
                    continue
            source.rename(target)
            moved.append({"source": item["source"], "target": item["target"]})

        if rewrite_references:
            for item in moved:
                reference_updates.append(
                    {
                        "source": item["source"],
                        "target": item["target"],
                        "files": _rewrite_path_references(item["source"], item["target"], root_path=root),
                    }
                )

    return {
        "experiment_id": experiment_id,
        "source_files": [relative for _, relative in resolved_sources],
        "experiment_dir": _relative(target_dir, root_path=root),
        "moves": moves,
        "conflicts": conflicts,
        "apply_changes": apply_changes,
        "rewrite_references": rewrite_references,
        "planned_created": scaffold_plan["planned_create"] if ensure_scaffold else [],
        "created": created,
        "moved": moved,
        "reference_updates": reference_updates,
        "dry_run": not apply_changes,
    }
