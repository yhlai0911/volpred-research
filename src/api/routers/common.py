from __future__ import annotations

import os
from pathlib import Path

from fastapi import Header, HTTPException


def get_storage_dir() -> str:
    return os.environ.get("VOLPRED_STORAGE_DIR", "storage")


def storage_path(*parts: str) -> Path:
    return Path(get_storage_dir()).joinpath(*parts)


def require_research_mirror_token(
    x_research_mirror_token: str | None = Header(default=None, alias="x-research-mirror-token"),
) -> None:
    expected = os.environ.get("RESEARCH_MIRROR_TOKEN", "").strip()
    if not expected:
        return
    if x_research_mirror_token != expected:
        raise HTTPException(status_code=401, detail="unauthorized")
