from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from scripts.supabase_sync import (
    SUPABASE_KEY,
    SUPABASE_URL,
    _patch_where,
    _post,
    _select_rows,
)

from .common import project_path

PAPER_SELECT = (
    "id,title,authors,abstract,status,target_journal,pdf_url,pages,figures,tables,"
    "citations,score,tags,display_order,storage_bucket,storage_path,created_at,updated_at"
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_paper(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "title": row.get("title") or "",
        "authors": row.get("authors") or "",
        "abstract": row.get("abstract") or "",
        "status": row.get("status") or "working",
        "target_journal": row.get("target_journal"),
        "pdf_url": row.get("pdf_url"),
        "pages": row.get("pages"),
        "figures": row.get("figures"),
        "tables": row.get("tables"),
        "citations": row.get("citations"),
        "score": row.get("score"),
        "tags": row.get("tags") if isinstance(row.get("tags"), list) else [],
        "display_order": row.get("display_order") or 0,
        "storage_bucket": row.get("storage_bucket"),
        "storage_path": row.get("storage_path"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def list_papers() -> list[dict[str, Any]]:
    rows = _select_rows("papers", select=PAPER_SELECT)
    rows.sort(
        key=lambda row: (
            int(row.get("display_order") or 0),
            str(row.get("updated_at") or ""),
        ),
        reverse=False,
    )
    return [_normalize_paper(row) for row in rows]


def get_paper(paper_id: str) -> dict[str, Any] | None:
    rows = _select_rows("papers", select=PAPER_SELECT, id=paper_id)
    if not rows:
        return None
    return _normalize_paper(rows[0])


def upsert_paper_metadata(
    *,
    paper_id: str,
    title: str,
    authors: str,
    abstract: str | None = None,
    status: str = "working",
    target_journal: str | None = None,
    pdf_url: str | None = None,
    pages: int | None = None,
    figures: int | None = None,
    tables: int | None = None,
    citations: int | None = None,
    score: float | None = None,
    tags: list[str] | None = None,
    display_order: int = 0,
    storage_bucket: str | None = None,
    storage_path: str | None = None,
) -> dict[str, Any]:
    payload = {
        "id": paper_id.strip(),
        "title": title.strip(),
        "authors": authors.strip(),
        "abstract": abstract.strip() if isinstance(abstract, str) and abstract.strip() else None,
        "status": status.strip() if isinstance(status, str) and status.strip() else "working",
        "target_journal": target_journal.strip()
        if isinstance(target_journal, str) and target_journal.strip()
        else None,
        "pdf_url": pdf_url.strip() if isinstance(pdf_url, str) and pdf_url.strip() else None,
        "pages": pages,
        "figures": figures,
        "tables": tables,
        "citations": citations,
        "score": score,
        "tags": [str(tag).strip() for tag in (tags or []) if str(tag).strip()],
        "display_order": int(display_order or 0),
        "storage_bucket": storage_bucket.strip()
        if isinstance(storage_bucket, str) and storage_bucket.strip()
        else None,
        "storage_path": storage_path.strip()
        if isinstance(storage_path, str) and storage_path.strip()
        else None,
        "updated_at": _utc_now(),
    }
    if not _post("papers", payload):
        raise RuntimeError(f"Failed to upsert paper metadata: {paper_id}")
    paper = get_paper(payload["id"])
    if not paper:
        raise RuntimeError(f"Paper row not found after upsert: {paper_id}")
    return paper


def _storage_headers(content_type: str) -> dict[str, str]:
    if not SUPABASE_KEY:
        raise RuntimeError("Missing SUPABASE_SERVICE_ROLE_KEY for storage upload")
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": content_type,
        "x-upsert": "true",
        "cache-control": "3600",
    }


def _public_storage_url(bucket: str, object_path: str) -> str:
    if not SUPABASE_URL:
        raise RuntimeError("Missing SUPABASE_URL for storage URL")
    return f"{SUPABASE_URL}/storage/v1/object/public/{bucket}/{quote(object_path, safe='/')}"


def _upload_storage_object(
    *,
    bucket: str,
    object_path: str,
    file_bytes: bytes,
    content_type: str = "application/pdf",
) -> str:
    if not SUPABASE_URL:
        raise RuntimeError("Missing SUPABASE_URL for storage upload")

    url = f"{SUPABASE_URL}/storage/v1/object/{bucket}/{quote(object_path, safe='/')}"
    req = Request(
        url,
        data=file_bytes,
        headers=_storage_headers(content_type),
        method="POST",
    )
    try:
        with urlopen(req, timeout=60):
            pass
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Storage upload failed ({exc.code}): {body or exc.reason}") from exc
    return _public_storage_url(bucket, object_path)


def upload_paper_pdf(
    *,
    paper_id: str,
    file_path: str,
    bucket: str = "papers",
    file_name: str | None = None,
) -> dict[str, Any]:
    paper = get_paper(paper_id)
    if not paper:
        raise RuntimeError(f"Paper not found: {paper_id}")

    source = Path(file_path)
    if not source.exists():
        raise RuntimeError(f"PDF file not found: {source}")

    safe_name = (file_name or source.name).replace(" ", "-")
    object_path = f"{paper_id.strip()}/{safe_name}"
    public_url = _upload_storage_object(
        bucket=bucket,
        object_path=object_path,
        file_bytes=source.read_bytes(),
        content_type="application/pdf",
    )

    if not _patch_where(
        "papers",
        {"id": paper_id},
        {
            "pdf_url": public_url,
            "storage_bucket": bucket,
            "storage_path": object_path,
            "updated_at": _utc_now(),
        },
    ):
        raise RuntimeError(f"Failed to update paper PDF URL after upload: {paper_id}")

    updated = get_paper(paper_id)
    if not updated:
        raise RuntimeError(f"Paper row not found after PDF upload: {paper_id}")
    return updated


def _resolve_static_pdf_path(pdf_url: str | None) -> Path | None:
    if not isinstance(pdf_url, str) or not pdf_url.startswith("/paper/"):
        return None
    relative = pdf_url.lstrip("/")
    candidates = [
        project_path("frontend-v2-fix", "public", relative),
        project_path("frontend-v2", "public", relative),
        project_path("frontend", "public", relative),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def migrate_paper_pdf_to_storage(
    *,
    paper_id: str,
    file_path: str | None = None,
) -> dict[str, Any]:
    paper = get_paper(paper_id)
    if not paper:
        raise RuntimeError(f"Paper not found: {paper_id}")

    source = Path(file_path) if file_path else _resolve_static_pdf_path(paper.get("pdf_url"))
    if source is None:
        raise RuntimeError(f"Could not resolve local PDF source for paper: {paper_id}")
    return upload_paper_pdf(paper_id=paper_id, file_path=str(source))
