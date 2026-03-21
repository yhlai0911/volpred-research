from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TypeVar

PROJECT_ROOT = Path(__file__).resolve().parents[3]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

T = TypeVar("T")


def project_path(*parts: str) -> Path:
    return PROJECT_ROOT.joinpath(*parts)


def load_json(path: Path, default: T) -> T:
    if not path.exists():
        return default
    return json.loads(path.read_text())


def dump_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str))


def ops_snapshot_path(name: str, storage_dir: str = "storage") -> Path:
    safe_name = name.strip().replace("/", "-")
    return project_path(storage_dir, "ops", f"{safe_name}.json")


def write_ops_snapshot(name: str, payload: object, storage_dir: str = "storage") -> Path:
    path = ops_snapshot_path(name, storage_dir=storage_dir)
    dump_json(path, payload)
    return path
