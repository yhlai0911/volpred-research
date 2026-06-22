from __future__ import annotations

import sys
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

from ..config.runtime import (
    get_active_frontend_paper_dir,
    get_frontend_path,
    iter_frontend_paper_public_dirs,
)
from .common import project_path

PAPER_SELECT = (
    "id,title,authors,abstract,status,target_journal,pdf_url,pages,figures,tables,"
    "citations,score,tags,display_order,storage_bucket,storage_path,created_at,updated_at"
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _warn_paper_ops(message: str, *, paper_id: str, value: Any, exc: Exception) -> None:
    print(
        f"[papers] WARN {message}: paper_id={paper_id} value={value!r} "
        f"error={type(exc).__name__}: {exc}",
        file=sys.stderr,
    )


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

    # Find the current main tex file. 2026-06-11 fix (leverage-direction
    # incident): a fixed version-priority list picked the STALE main_v3.tex
    # over the actively-edited main.tex, pushing an outdated abstract (with
    # superseded claims) to the live site. Among existing candidates, prefer
    # the most recently modified one — the file the main thread actually
    # edits and compiles is the current version, regardless of its suffix.
    main_candidates = [paper_dir / n for n in
                       ["main_v4.tex", "main_v3.tex", "main_v2.tex", "main.tex"]]
    body_candidates = [paper_dir / n for n in
                       ["body.tex", "body_v5.tex", "body_v4.tex", "body_v3.tex"]]
    mains = [c for c in main_candidates if c.exists()]
    bodies = [c for c in body_candidates if c.exists()]
    if mains:
        # main* wrappers carry \title/\begin{abstract}; pick the most recently
        # edited one (NOT the body file, whose mtime is usually newer but which
        # lacks the abstract environment — picking it left the stale Supabase
        # abstract untouched).
        tex = max(mains, key=lambda c: c.stat().st_mtime)
    elif bodies:
        tex = max(bodies, key=lambda c: c.stat().st_mtime)
    else:
        return metrics

    content = tex.read_text(errors="ignore")

    # Extract \title{...} — paper-update previously never synced the title,
    # so papers whose title was never explicitly upserted displayed their
    # paper-id on the frontend (crypto-fear-channel, eav-universal-magnitude).
    # Brace-match to span the closing }, then strip LaTeX line breaks/markup.
    tm = re.search(r"\\title\s*\{", content)
    if tm:
        i, depth, buf = tm.end(), 1, []
        while i < len(content) and depth:
            ch = content[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    break
            buf.append(ch)
            i += 1
        title = "".join(buf)
        title = re.sub(r"%.*", "", title)            # strip LaTeX line comments
        title = title.split(r"\thanks")[0]           # drop \thanks{...} onward
        title = re.sub(r"\\\\(\[[^\]]*\])?", " ", title)  # \\ and \\[0.5em]
        title = re.sub(r"\\[a-zA-Z]+", " ", title)   # other \commands (\large …)
        title = re.sub(r"\s+", " ", title).strip(" {}")
        if title:
            metrics["title"] = title

    # Extract \author{...} — like \title above, the author was NEVER synced, so
    # freshly auto-synced papers showed a BLANK author line on the public page
    # (2026-06-22 boss report: crypto-fear-channel + eav-universal-magnitude had
    # authors=''). Brace-match the \author{...} span, drop \thanks{...}/\footnote{...}
    # footnotes (they hold the affiliation/email, not the name), turn \and into
    # commas. Makes the .tex the single source of truth for the author string.
    am = re.search(r"\\author\s*\{", content)
    if am:
        i, depth, buf = am.end(), 1, []
        while i < len(content) and depth:
            ch = content[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    break
            buf.append(ch)
            i += 1
        author = "".join(buf)
        # Drop \thanks{...} / \footnote{...} (brace-matched; may contain braces/email)
        for cmd in ("thanks", "footnote"):
            while True:
                fm = re.search(r"\\" + cmd + r"\s*\{", author)
                if not fm:
                    break
                j, d = fm.end(), 1
                while j < len(author) and d:
                    if author[j] == "{":
                        d += 1
                    elif author[j] == "}":
                        d -= 1
                    j += 1
                author = author[: fm.start()] + author[j:]
        author = re.sub(r"%.*", "", author)               # strip line comments
        author = re.sub(r"\\and\b", ",", author)           # \and → comma separator
        author = re.sub(r"\\\\(\[[^\]]*\])?", " ", author)  # \\ and \\[..] line breaks
        author = re.sub(r"\\[a-zA-Z]+", " ", author)       # other \commands
        author = author.replace("{", " ").replace("}", " ")
        author = re.sub(r"\s*,\s*", ", ", author)           # tidy comma spacing
        author = re.sub(r"\s+", " ", author).strip(" ,")
        if author:
            metrics["authors"] = author

    # Count \bibitem entries (citations)
    citations = len(re.findall(r"\\bibitem", content))
    # Also check body files
    for body_name in ["body_v3.tex", "body_v2.tex", "body.tex"]:
        body = paper_dir / body_name
        if body.exists():
            body_content = body.read_text(errors="ignore")
            citations += len(re.findall(r"\\bibitem", body_content))
            break
    if citations > 0:
        metrics["citations"] = citations

    # Count pages from PDF. Keep this in-process: invoking `python3 -c
    # import fitz` from a uv-managed command can inherit an environment where
    # the system fitz package is not importable, silently preserving stale page
    # counts in Supabase metadata.
    pdf_name = tex.stem + ".pdf"
    pdf = paper_dir / pdf_name
    if pdf.exists():
        try:
            from PyPDF2 import PdfReader

            metrics["pages"] = len(PdfReader(str(pdf)).pages)
        except Exception as primary_exc:
            try:
                result = subprocess.run(
                    ["python3", "-c", f"import fitz; print(fitz.open('{pdf}').page_count)"],
                    capture_output=True, text=True, timeout=10,
                )
                if result.returncode == 0 and result.stdout.strip().isdigit():
                    metrics["pages"] = int(result.stdout.strip())
                else:
                    print(
                        f"  [papers] WARN page count fallback failed for {pdf}: "
                        f"PyPDF2={primary_exc}; fitz_exit={result.returncode}; "
                        f"stderr={result.stderr.strip()[:200]!r}"
                    )
            except Exception as fallback_exc:
                print(
                    f"  [papers] WARN page count failed for {pdf}: "
                    f"PyPDF2={primary_exc}; fitz={fallback_exc}"
                )

    # Extract abstract from \begin{abstract} … \end{abstract}. main_v*.tex
    # often only `\input{body_v*}` and has no \begin{abstract}; resolve \input
    # chain so we read the body file that actually carries the abstract.
    # (2026-05-27 vt-trend-following incident: main_v3.tex won the file
    # priority, lacked \begin{abstract}, so Supabase abstract stayed stale.)
    abstract_re = re.compile(
        r"\\begin\{abstract\}\s*(?:\\noindent\s*)?(.*?)\\end\{abstract\}",
        re.DOTALL,
    )
    search_sources: list[str] = [content]
    for input_name in re.findall(r"\\input\{([^}]+)\}", content):
        stem = input_name.strip()
        for candidate in (paper_dir / stem, paper_dir / f"{stem}.tex"):
            if candidate.is_file():
                search_sources.append(candidate.read_text(errors="ignore"))
                break
    def _clean_abstract(raw: str) -> str:
        """Strip LaTeX comments/markup so the site shows readable prose.
        2026-06-11 fix: the live abstract opened with a literal '% v2: ...'
        editor comment and exposed \\medskip/\\textbf/Keywords markup."""
        # Drop comment lines (and trailing inline comments) BEFORE whitespace
        # collapsing, while line structure still exists.
        lines = []
        for line in raw.splitlines():
            stripped = line.lstrip()
            if stripped.startswith("%"):
                continue
            # strip inline unescaped comments
            line = re.sub(r"(?<!\\)%.*$", "", line)
            lines.append(line)
        text = " ".join(lines)
        # Cut at the keywords/JEL block — not part of the abstract prose.
        text = re.split(r"\\medskip|\\textbf\{Keywords|\\textbf\{JEL", text)[0]
        # De-LaTeX the most common inline markup.
        text = re.sub(r"\\(?:textbf|textit|emph|texttt|mbox)\{([^{}]*)\}", r"\1", text)
        text = re.sub(r"\\(?:citet|citep|cite)\{[^{}]*\}", "", text)
        text = re.sub(r"\\(?:noindent|smallskip|bigskip|par)\b", " ", text)
        text = text.replace(r"\%", "%").replace(r"\&", "&").replace(r"\$", "$")
        text = text.replace("---", "—").replace("--", "–").replace("~", " ")
        text = text.replace(r"\,", " ").replace("``", '"').replace("''", '"')
        # $...$ math: keep contents, drop the delimiters (mathless frontend).
        text = re.sub(r"\$([^$]*)\$", r"\1", text)
        text = re.sub(r"\\(rho|gamma|beta|alpha|sigma|tau|nu|lambda|Delta)(?![a-zA-Z])",
                      lambda m: {"rho": "ρ", "gamma": "γ", "beta": "β", "alpha": "α",
                                 "sigma": "σ", "tau": "τ", "nu": "ν", "lambda": "λ",
                                 "Delta": "Δ"}[m.group(1)], text)
        text = re.sub(r"\\(?:le|leq)\b", "≤", text)
        text = re.sub(r"\\(?:ge|geq)\b", "≥", text)
        text = re.sub(r"\\times\b", "×", text)
        text = text.replace("\\\\", " ")          # forced line breaks
        text = re.sub(r"\\'\{?([a-zA-Z])\}?", r"\1", text)  # accents: Sz\'{e}kely → Szekely
        text = re.sub(r"\\[`^\"~=.]\{?([a-zA-Z])\}?", r"\1", text)
        text = text.replace("\\ ", " ")           # escaped interword space (U.S.\ VT)
        text = re.sub(r"\\[a-zA-Z]+", "", text)  # any leftover commands
        text = text.replace("{", "").replace("}", "")
        return re.sub(r"\s+", " ", text).strip()

    for src in search_sources:
        m = abstract_re.search(src)
        if not m:
            continue
        cleaned = _clean_abstract(m.group(1))
        if cleaned:
            metrics["abstract"] = cleaned
            break

    return metrics


def _select_current_main_artifact(paper_dir: Path, suffix: str) -> Path | None:
    """Pick the current main artifact by mtime, not version suffix.

    Some paper folders keep stale `main_v3.*` files beside actively edited
    `main.*` files. Suffix priority can therefore upload an old PDF while
    metrics come from the current TeX source.
    """
    candidates = [
        paper_dir / f"main_v4{suffix}",
        paper_dir / f"main_v3{suffix}",
        paper_dir / f"main_v2{suffix}",
        paper_dir / f"main{suffix}",
    ]
    existing = [candidate for candidate in candidates if candidate.exists()]
    if not existing:
        return None
    return max(existing, key=lambda candidate: candidate.stat().st_mtime)


def sync_all_papers(
    *,
    only_stale: bool = True,
    dry_run: bool = False,
    paper_root: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Auto-sync every paper in paper/<id>/ whose .tex or .pdf is newer than its
    Supabase updated_at timestamp.

    2026-05-11 user-driven fix: main-thread edits to body.tex / main_v3.tex
    abstract / etc. were not being pushed to Supabase because paper-update CLI
    requires manual invocation per paper. Result: 6/9 papers showed April
    updated_at on the website despite recent edits. Sync-all closes that loop.

    Args:
        only_stale: if True (default), skip papers where Supabase updated_at
            is newer than all local .tex/.pdf mtime.
        dry_run: if True, return planned actions without invoking Supabase.

    Returns: list of dicts with {paper_id, action, reason, ...}.
    """
    PROJECT = Path(__file__).resolve().parent.parent.parent.parent
    paper_root = Path(paper_root) if paper_root is not None else PROJECT / "paper"
    if not paper_root.is_dir():
        return []

    # Existing papers in Supabase (id → updated_at)
    existing_papers = {p["id"]: p for p in list_papers()}

    results: list[dict[str, Any]] = []
    for paper_dir in sorted(paper_root.iterdir()):
        if not paper_dir.is_dir():
            continue
        paper_id = paper_dir.name
        if paper_id.startswith(".") or paper_id.startswith("_"):
            continue

        # Newest .tex / .pdf mtime in this paper dir
        candidates = list(paper_dir.glob("*.tex")) + list(paper_dir.glob("*.pdf"))
        if not candidates:
            results.append({"paper_id": paper_id, "action": "skip", "reason": "no_tex_or_pdf"})
            continue
        latest_local_mtime = max(c.stat().st_mtime for c in candidates)

        existing = existing_papers.get(paper_id)
        if existing is not None and only_stale:
            db_updated_str = existing.get("updated_at") or ""
            try:
                db_updated = datetime.fromisoformat(db_updated_str.replace("Z", "+00:00"))
                if db_updated.tzinfo is None:
                    db_updated = db_updated.replace(tzinfo=timezone.utc)
                if db_updated.timestamp() >= latest_local_mtime:
                    results.append({"paper_id": paper_id, "action": "skip", "reason": "supabase_newer"})
                    continue
            except (ValueError, AttributeError) as exc:
                _warn_paper_ops(
                    "Supabase updated_at parse failed; treating paper as stale",
                    paper_id=paper_id,
                    value=db_updated_str,
                    exc=exc,
                )

        if dry_run:
            results.append({"paper_id": paper_id, "action": "would_update", "in_db": existing is not None})
            continue

        # If paper doesn't exist in Supabase yet, create minimal record first
        # so update_paper_full's get_paper() lookup succeeds.
        if existing is None:
            try:
                upsert_paper_metadata(paper_id=paper_id)
            except Exception as exc:
                results.append({"paper_id": paper_id, "action": "create_failed", "error": str(exc)})
                continue

        try:
            paper = update_paper_full(paper_id=paper_id, paper_dir=paper_dir)
            results.append({
                "paper_id": paper_id,
                "action": "updated",
                "pages": paper.get("pages"),
                "citations": paper.get("citations"),
                "updated_at": paper.get("updated_at"),
            })
        except Exception as exc:
            results.append({"paper_id": paper_id, "action": "update_failed", "error": str(exc)})

    return results


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

    # 2. Find current PDF by mtime, matching _count_tex_metrics' current-TeX
    # semantics. Do not prefer stale versioned PDFs over fresh main.pdf.
    pdf_path = _select_current_main_artifact(paper_dir, ".pdf")

    if not pdf_path:
        raise RuntimeError(f"No PDF found in {paper_dir}")

    # 3. Upload PDF
    paper = upload_paper_pdf(paper_id=paper_id, file_path=str(pdf_path))

    # 4. Update metadata with auto-detected metrics
    kwargs: dict[str, Any] = {"paper_id": paper_id}
    if "title" in metrics:
        kwargs["title"] = metrics["title"]
    if "authors" in metrics:
        kwargs["authors"] = metrics["authors"]
    if "pages" in metrics:
        kwargs["pages"] = metrics["pages"]
    if "citations" in metrics:
        kwargs["citations"] = metrics["citations"]
    if "abstract" in metrics:
        kwargs["abstract"] = metrics["abstract"]

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
        frontend_dir = get_frontend_path()
        frontend_paper_dir = get_active_frontend_paper_dir()
        if frontend_paper_dir is not None and frontend_dir.exists():
            frontend_paper_dir.mkdir(parents=True, exist_ok=True)
            import shutil
            shutil.copy2(pdf_path, frontend_paper_dir / frontend_name)

    return paper


def _resolve_static_pdf_path(pdf_url: str | None) -> Path | None:
    if not isinstance(pdf_url, str) or not pdf_url.startswith("/paper/"):
        return None
    relative = pdf_url.lstrip("/")
    for paper_dir in iter_frontend_paper_public_dirs(active_first=True):
        candidate = paper_dir.parent / relative
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
