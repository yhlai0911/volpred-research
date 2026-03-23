from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from .common import require_research_mirror_token, storage_path

router = APIRouter(dependencies=[Depends(require_research_mirror_token)])

ALLOWED_MEMORY_FILES = {
    "thinking_journal.json",
    "knowledge.json",
    "experiments.json",
    "research_log.json",
}


def _memory_file_path(filename: str) -> Path:
    if filename not in ALLOWED_MEMORY_FILES:
        raise HTTPException(status_code=404, detail="unsupported mirror file")
    return storage_path("memory", filename)


def _json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str).encode("utf-8")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _file_meta(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "exists": False,
            "size_bytes": 0,
            "sha256": None,
            "updated_at": None,
        }

    payload = path.read_bytes()
    stat = path.stat()
    return {
        "exists": True,
        "size_bytes": stat.st_size,
        "sha256": _sha256(payload),
        "updated_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
    }


@router.put("/memory/{filename}")
async def put_memory_file(filename: str, request: Request):
    path = _memory_file_path(filename)
    payload = await request.json()
    if not isinstance(payload, list):
        raise HTTPException(status_code=400, detail="memory mirror payload must be a JSON array")

    path.parent.mkdir(parents=True, exist_ok=True)
    data = _json_bytes(payload)
    tmp_path = path.with_name(f".{path.name}.tmp")
    tmp_path.write_bytes(data)
    tmp_path.replace(path)

    return {
        "status": "ok",
        "file": filename,
        "entries": len(payload),
        **_file_meta(path),
    }


@router.get("/health")
def get_mirror_health():
    files = {name: _file_meta(_memory_file_path(name)) for name in sorted(ALLOWED_MEMORY_FILES)}
    ready = all(item["exists"] for item in files.values())
    return {
        "status": "ok",
        "ready": ready,
        "storage_dir": str(storage_path()),
        "files": files,
    }


@router.get("/manifest")
def get_mirror_manifest():
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "storage_dir": str(storage_path()),
        "files": {name: _file_meta(_memory_file_path(name)) for name in sorted(ALLOWED_MEMORY_FILES)},
    }
