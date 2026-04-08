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


_SENTINEL = object()  # distinguishes "not provided" from explicit None


def upsert_paper_metadata(
    *,
    paper_id: str,
    title: str | None = _SENTINEL,
    authors: str | None = _SENTINEL,
    abstract: str | None = _SENTINEL,
    status: str | None = _SENTINEL,
    target_journal: str | None = _SENTINEL,
    pdf_url: str | None = _SENTINEL,
    pages: int | None = _SENTINEL,
    figures: int | None = _SENTINEL,
    tables: int | None = _SENTINEL,
    citations: int | None = _SENTINEL,
    score: float | None = _SENTINEL,
    tags: list[str] | None = _SENTINEL,
    display_order: int | None = _SENTINEL,
    storage_bucket: str | None = _SENTINEL,
    storage_path: str | None = _SENTINEL,
) -> dict[str, Any]:
    # Merge mode: read existing paper first, only overwrite provided fields
    existing = get_paper(paper_id.strip()) or {}

    def _pick(new_val, field_name, *, strip=False):
        """Return new_val if explicitly provided, else keep existing."""
        if new_val is _SENTINEL:
            return existing.get(field_name)
        if strip and isinstance(new_val, str):
            return new_val.strip() or None
        return new_val

    payload = {
        "id": paper_id.strip(),
        "title": _pick(title, "title", strip=True) or paper_id,
        "authors": _pick(authors, "authors", strip=True) or "",
        "abstract": _pick(abstract, "abstract", strip=True),
        "status": _pick(status, "status", strip=True) or "working",
        "target_journal": _pick(target_journal, "target_journal", strip=True),
        "pdf_url": _pick(pdf_url, "pdf_url", strip=True),
        "pages": _pick(pages, "pages"),
        "figures": _pick(figures, "figures"),
        "tables": _pick(tables, "tables"),
        "citations": _pick(citations, "citations"),
        "score": _pick(score, "score"),
        "display_order": int(_pick(display_order, "display_order") or 0),
        "storage_bucket": _pick(storage_bucket, "storage_bucket", strip=True),
        "storage_path": _pick(storage_path, "storage_path", strip=True),
        "updated_at": _utc_now(),
    }
    # Tags: only overwrite if explicitly provided
    if tags is not _SENTINEL:
        payload["tags"] = [str(tag).strip() for tag in (tags or []) if str(tag).strip()]
    else:
        payload["tags"] = existing.get("tags") or []

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


def _count_tex_metrics(paper_dir: Path) -> dict[str, int | None]:
    """Auto-extract pages, citations from .tex files in a paper directory."""
    import re
    import subprocess

    metrics: dict[str, int | None] = {}

    # Find the best tex file (v2 preferred over v1)
    for name in ["main_v2.tex", "main.tex"]:
        tex = paper_dir / name
        if tex.exists():
            break
    else:
        return metrics

    content = tex.read_text(errors="ignore")

    # Count \bibitem entries (citations)
    citations = len(re.findall(r"\\bibitem", content))
    # Also check body files
    for body_name in ["body_v2.tex", "body.tex"]:
        body = paper_dir / body_name
        if body.exists():
            body_content = body.read_text(errors="ignore")
            citations += len(re.findall(r"\\bibitem", body_content))
            break
    if citations > 0:
        metrics["citations"] = citations

    # Count pages from PDF
    pdf_name = tex.stem + ".pdf"
    pdf = paper_dir / pdf_name
    if pdf.exists():
        try:
            result = subprocess.run(
                ["python3", "-c", f"import fitz; print(fitz.open('{pdf}').page_count)"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip().isdigit():
                metrics["pages"] = int(result.stdout.strip())
        except Exception:
            pass

    return metrics


def update_paper_full(
    *,
    paper_id: str,
    paper_dir: str | Path | None = None,
) -> dict[str, Any]:
    """One-command paper update: auto-detect metrics from .tex → upload PDF → sync metadata.

    Steps:
    1. Auto-count citations from \\bibitem in .tex files
    2. Auto-count pages from compiled PDF
    3. Upload PDF to Supabase Storage
    4. Update metadata (pages, citations, pdf_url)
    """
    PROJECT = Path(__file__).resolve().parent.parent.parent.parent

    if paper_dir is None:
        paper_dir = PROJECT / "paper" / paper_id
    paper_dir = Path(paper_dir)

    if not paper_dir.exists():
        raise RuntimeError(f"Paper directory not found: {paper_dir}")

    # 1. Auto-detect metrics
    metrics = _count_tex_metrics(paper_dir)

    # 2. Find best PDF (v2 preferred)
    pdf_path = None
    for name in ["main_v2.pdf", "main.pdf"]:
        candidate = paper_dir / name
        if candidate.exists():
            pdf_path = candidate
            break

    if not pdf_path:
        raise RuntimeError(f"No PDF found in {paper_dir}")

    # 3. Upload PDF
    paper = upload_paper_pdf(paper_id=paper_id, file_path=str(pdf_path))

    # 4. Update metadata with auto-detected metrics
    kwargs: dict[str, Any] = {"paper_id": paper_id}
    if "pages" in metrics:
        kwargs["pages"] = metrics["pages"]
    if "citations" in metrics:
        kwargs["citations"] = metrics["citations"]

    if len(kwargs) > 1:  # has something beyond paper_id
        paper = upsert_paper_metadata(**kwargs)

    # 5. Copy to frontend
    slug_map = {
        "leverage-direction": "leverage-direction-matters.pdf",
        "taiwan-vt": "taiwan-vt-tz-arbitrage.pdf",
        "vt-trend-following": "vt-trend-following.pdf",
        "volatility-absorption": "volatility-absorption.pdf",
        "vix-sufficiency": "vix-sufficiency.pdf",
    }
    frontend_name = slug_map.get(paper_id)
    if frontend_name:
        frontend_dst = PROJECT / "frontend-v2-fix" / "public" / "paper" / frontend_name
        if frontend_dst.parent.exists():
            import shutil
            shutil.copy2(pdf_path, frontend_dst)

    return paper


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
