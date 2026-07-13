#!/usr/bin/env python3
"""Async lazypack (懶人包圖組) pipeline — enqueue + deterministic render/install.

Root cause (docs/error_log.md 2026-07-02 15:15 #4): the writing agent's 50-min
hard cap was shared between article body writing and the old agentic lazypack
render, squeezing body depth. The 2026-07-13 3-STRIKE refactor keeps this async
install lane but makes rendering deterministic and sub-second for typical sets.
off the writing fire onto the EXISTING compute_queue async lane
(storage/ops/compute_queue/ + */15 compute-worker; 0 Claude tokens — same split
as reference_compute_queue_token_split):

    writing agent : body done → publish draft (lazypack NOT required at draft
                    stage) → `lazypack_async_render.py enqueue --article-id
                    mile_x --experiment Kxxxx --plan plan.json`
    compute worker: `run` → lazypack_render.py (strict plan + JSON evidence,
                    no LLM/code generation) → upload PNGs → append
                    `## 懶人包圖組` to the article → single-article re-sync
    release gate  : release_pool refuses to flip a general draft/scheduled
                    article to published until the section exists
                    (src/volpred/ops/content.py release audit gate)

Immediate-publish paths (event_article / trending_repost going live now) keep
the synchronous render — the publish-time gate still requires the section when
an article is created with status='published' (see publisher.lazypack_required_at).

Usage:
  # writing agent, after the draft is published into the pool:
  uv run python scripts/lazypack_async_render.py enqueue \
    --article-id mile_31b2b0bb --experiment K1576 \
    --plan /tmp/k1576_plan.json --title "K1576 懶人包"

  # compute worker executes (enqueued automatically as the job command):
  uv run python scripts/lazypack_async_render.py run \
    --article-id mile_31b2b0bb --experiment K1576 \
    --plan storage/lazypack_jobs/mile_31b2b0bb/plan.json \
    --out-dir storage/lazypack_jobs/mile_31b2b0bb/panels

plan.json uses the strict, versioned schema owned by scripts/lazypack_render.py.
Each numeric value is a JSON-field binding; one PNG is emitted per panel.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "src"), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

JOB_ID_PREFIX = "lazypack-"
DEFAULT_TIMEOUT_S = 300  # deterministic render is seconds; keep upload/sync headroom


def _resolve(path_like: str | Path) -> Path:
    p = Path(path_like)
    return p if p.is_absolute() else ROOT / p


def _load_plan(plan_path: Path) -> dict:
    """Use the renderer's single validator; legacy free-prose lists fail closed."""
    from lazypack_render import load_plan

    document, _evidence = load_plan(plan_path)
    return document


def _panel_specs(panels: list[dict]) -> list[tuple[str, str]]:
    """[(png-stem, alt-text)] in display order."""
    specs: list[tuple[str, str]] = []
    for i, p in enumerate(panels, 1):
        name = str(p.get("name") or f"{i}_panel")
        alt = str(p.get("alt") or f"懶人包圖 {i}")
        specs.append((name, alt))
    return specs


def _find_article(article_id: str, storage_dir: Path) -> dict | None:
    feed_path = storage_dir / "reports" / "feed.json"
    feed = json.loads(feed_path.read_text(encoding="utf-8"))
    return next(
        (x for x in feed if isinstance(x, dict) and x.get("id") == article_id),
        None,
    )


# ---------------------------------------------------------------- enqueue ----

def cmd_enqueue(a: argparse.Namespace) -> int:
    import compute_queue as cq  # scripts/compute_queue.py — existing async lane

    storage_dir = _resolve(a.storage_dir)
    art = _find_article(a.article_id, storage_dir)
    if art is None:
        print(f"error: article {a.article_id} not found in "
              f"{storage_dir / 'reports' / 'feed.json'} — publish the draft first",
              file=sys.stderr)
        return 2

    plan_src = _resolve(a.plan)
    document = _load_plan(plan_src)  # validate evidence and every binding before queueing
    panels = document["panels"]

    from volpred.publisher.publisher import has_lazypack_section
    if has_lazypack_section(str(art.get("content") or "")):
        print(f"note: {a.article_id} already carries a 懶人包圖組 section — "
              f"the async render will REPLACE it on completion.")

    jobs_dir = storage_dir / "lazypack_jobs" / a.article_id
    base_id = f"{JOB_ID_PREFIX}{a.article_id}"

    def _rel(p: Path) -> str:
        try:
            return str(p.relative_to(ROOT))
        except ValueError:
            return str(p)

    # The plan and output directory are shared by sequential retries for one
    # article. Serialize check → persist → receipt creation so a duplicate fire
    # cannot overwrite the plan underneath an already queued/running worker.
    # Concurrent --force used to create two jobs racing on those same paths; it
    # now fails explicitly instead of pretending isolation exists.
    with cq._receipt_lock():
        existing = (
            sorted(cq.QUEUE_DIR.glob(f"{base_id}*.json"))
            if cq.QUEUE_DIR.exists() else []
        )
        job_id = base_id
        taken: set[str] = set()
        active: dict | None = None
        for path in existing:
            try:
                job = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:
                print(f"warn: unreadable queue file {path}: {exc}", file=sys.stderr)
                taken.add(path.stem)
                continue
            taken.add(str(job.get("id") or path.stem))
            if job.get("status") in ("queued", "running"):
                active = job
                break
        if active is not None:
            if a.force:
                print(
                    f"error: cannot --force a concurrent lazypack render for "
                    f"{a.article_id}; active job={active.get('id')} "
                    f"status={active.get('status')}",
                    file=sys.stderr,
                )
                return 2
            print(
                f"skip: lazypack job already {active.get('status')} for "
                f"{a.article_id} ({active.get('id')})"
            )
            return 0
        n = 2
        while job_id in taken:
            job_id = f"{base_id}-r{n}"
            n += 1

        run_dir = jobs_dir / "runs" / job_id
        panels_dir = run_dir / "panels"
        run_dir.mkdir(parents=True, exist_ok=True)
        stored_plan = run_dir / "plan.json"
        stored_plan.write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        script_args = [
            "run",
            "--job-id", job_id,
            "--article-id", a.article_id,
            "--plan", _rel(stored_plan),
            "--out-dir", _rel(panels_dir),
            "--storage-dir", a.storage_dir,
            "--title", a.title or f"{a.article_id} 懶人包",
        ]
        for k in a.experiment:
            script_args += ["--experiment", k]
        for source in a.source:
            script_args += ["--source", source]

        ns = argparse.Namespace(
            id=job_id,
            title=f"lazypack render {a.article_id}",
            script="scripts/lazypack_async_render.py",
            interpreter="uv run python",
            script_args=script_args,
            env=None,
            result_artifact=_rel(panels_dir),
            output_paths=[
                _rel(stored_plan),
                *(
                    _rel(panels_dir / f"{stem}.png")
                    for stem, _ in _panel_specs(panels)
                ),
            ],
            followup_brief=None,
            followup_task_type=None,
            followup_priority=None,
            timeout=a.timeout,
        )
        rc = cq.enqueue(ns)
    if rc == 0:
        print(f"lazypack render queued for {a.article_id}; the */15 compute "
              f"worker will render + append + sync. Inspect: "
              f"uv run python scripts/compute_queue.py show {job_id}")
    return rc


# -------------------------------------------------------------------- run ----


def _record_job_outputs(
    job_id: str | None,
    out_dir: Path,
    specs: list[tuple[str, str]],
    before: dict[Path, tuple[int, str]],
) -> None:
    """Write back every file the renderer actually placed in its owned directory.

    This runs even when the render subprocess exits non-zero.  The enqueue-time
    declaration is the recovery floor; this observation is the precise receipt.
    A failed metadata write does not hide the render result because the hourly
    reaper can still inspect the declared paths.
    """
    job_id = job_id or os.environ.get("VOLPRED_COMPUTE_JOB_ID")
    if not job_id:
        return
    candidates = [out_dir / f"{stem}.png" for stem, _ in specs]
    actual = [
        path for path in candidates
        if path.is_file() and before.get(path) != _file_fingerprint(path)
    ]
    if not actual:
        return
    try:
        import compute_queue as cq

        if not cq.record_output_paths(job_id, actual):
            print(f"warn: could not record output paths for {job_id}", file=sys.stderr)
    except Exception as exc:  # metadata must not mask the renderer's real result
        print(f"warn: output path write-back failed for {job_id}: {exc}", file=sys.stderr)


def _file_fingerprint(path: Path) -> tuple[int, str] | None:
    if not path.is_file():
        return None
    raw = path.read_bytes()
    return len(raw), hashlib.sha256(raw).hexdigest()


def _snapshot_outputs(
    out_dir: Path, specs: list[tuple[str, str]],
) -> dict[Path, tuple[int, str]]:
    snapshot: dict[Path, tuple[int, str]] = {}
    for stem, _ in specs:
        path = out_dir / f"{stem}.png"
        fingerprint = _file_fingerprint(path)
        if fingerprint is not None:
            snapshot[path] = fingerprint
    return snapshot


def _validate_render_receipt(
    receipt_path: Path,
    *,
    run_token: str,
    plan_path: Path,
    out_dir: Path,
    specs: list[tuple[str, str]],
) -> None:
    if not receipt_path.is_file():
        raise RuntimeError(f"renderer produced no fresh receipt: {receipt_path}")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("run_token") != run_token:
        raise RuntimeError("renderer receipt run_token mismatch")
    expected_plan = hashlib.sha256(plan_path.read_bytes()).hexdigest()
    if receipt.get("plan_sha256") != expected_plan:
        raise RuntimeError("renderer receipt plan hash mismatch")
    expected = []
    for stem, _ in specs:
        path = out_dir / f"{stem}.png"
        if not path.is_file():
            raise RuntimeError(f"renderer receipt panel missing: {path}")
        expected.append({
            "name": path.name,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        })
    if receipt.get("panels") != expected:
        raise RuntimeError("renderer receipt output set/hash mismatch")


def cmd_run(a: argparse.Namespace) -> int:
    storage_dir = _resolve(a.storage_dir)
    plan_path = _resolve(a.plan)
    out_dir = _resolve(a.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    document = _load_plan(plan_path)
    panels = document["panels"]
    specs = _panel_specs(panels)
    job_id = getattr(a, "job_id", None)
    run_token = uuid.uuid4().hex
    receipt_dir = Path(tempfile.gettempdir()) / "volpred-lazypack-render-receipts"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = receipt_dir / f"{run_token}.json"

    # 1) Render.  Deterministic rendering is cheap, so retries always recompute
    # from the hash-pinned plan instead of trusting stale PNGs by file size.
    if a.render_cmd:
        print(f"[lazypack_async] TEST HOOK ACTIVE: --render-cmd {a.render_cmd!r} "
              f"(bypasses lazypack_render.py; smoke/tests only)")
        cmd = shlex.split(a.render_cmd) + [str(plan_path), str(out_dir)]
    else:
        cmd = [
            sys.executable, str(ROOT / "scripts" / "lazypack_render.py"),
            "--plan", str(plan_path), "--out-dir", str(out_dir),
            "--receipt", str(receipt_path), "--run-token", run_token,
        ]

    before = _snapshot_outputs(out_dir, specs)
    try:
        proc = subprocess.run(cmd, cwd=str(ROOT))
    finally:
        # A test hook or interrupted renderer may have written a partial staging
        # result; record only final files that actually reached the owned path.
        _record_job_outputs(job_id, out_dir, specs, before)
    if proc.returncode != 0:
        receipt_path.unlink(missing_ok=True)
        print(f"error: render step failed rc={proc.returncode}", file=sys.stderr)
        return 2

    after = {out_dir / f"{stem}.png": _file_fingerprint(out_dir / f"{stem}.png")
             for stem, _ in specs}
    if a.render_cmd:
        stale = [str(path) for path, fingerprint in after.items()
                 if fingerprint is None or before.get(path) == fingerprint]
        if stale:
            print(
                f"error: test renderer returned success without freshly writing: {stale}",
                file=sys.stderr,
            )
            return 3
    else:
        try:
            _validate_render_receipt(
                receipt_path,
                run_token=run_token,
                plan_path=plan_path,
                out_dir=out_dir,
                specs=specs,
            )
        except Exception as exc:
            print(f"error: invalid render receipt: {exc}", file=sys.stderr)
            return 3
        finally:
            receipt_path.unlink(missing_ok=True)

    # 2) Verify every expected panel PNG exists (belt-and-suspenders — the
    # deterministic renderer verifies too, but --render-cmd paths must not skip it).
    missing = [
        str(out_dir / f"{stem}.png")
        for stem, _ in specs
        if not (out_dir / f"{stem}.png").exists()
        or (out_dir / f"{stem}.png").stat().st_size <= 1024
    ]
    if missing:
        print(f"error: missing/empty panel PNGs after render: {missing}",
              file=sys.stderr)
        return 3

    # 3) Upload + append `## 懶人包圖組` + single-article sync (shared module,
    # feed write under the publisher_feed lock).
    from volpred.publisher.lazypack_install import (
        install_lazypack_section,
        upload_panels,
    )

    uploader = None
    if a.upload_cmd:
        print(f"[lazypack_async] TEST HOOK ACTIVE: --upload-cmd {a.upload_cmd!r} "
              f"(bypasses Supabase upload; smoke/tests only)")

        def uploader(png_path: str) -> str:  # noqa: F811
            out = subprocess.check_output(
                shlex.split(a.upload_cmd) + [png_path], text=True
            )
            return out.strip()

    urls = upload_panels(a.article_id, out_dir, specs, uploader=uploader)
    result = install_lazypack_section(
        a.article_id,
        urls,
        storage_dir=storage_dir,
        update_action="lazypack_async_render",
        sync=not a.no_sync,
    )
    print(json.dumps(result, ensure_ascii=False))

    if result["status"] == "published" and not a.no_sync and result["synced"] is False:
        # A live article's remote copy is now stale — surface as job failure so
        # the compute_queue marks it failed (visible) instead of silent drift.
        print("error: article is published but sync_article failed — re-run "
              "scripts/supabase_sync.py sync-article", file=sys.stderr)
        return 4
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    common = {
        "--article-id": dict(required=True, help="feed.json article id (mile_...)"),
        "--experiment": dict(
            action="append", default=[],
            help="LEGACY metadata only; evidence must be declared in plan.json",
        ),
        "--source": dict(action="append", default=[],
                         help="LEGACY metadata only; ignored by the renderer"),
        "--title": dict(default=None),
        "--storage-dir": dict(default="storage",
                              help="storage root (tests only; default: storage)"),
    }

    e = sub.add_parser("enqueue", help="queue the render on compute_queue "
                                       "(writing agent, after draft publish)")
    for flag, kw in common.items():
        e.add_argument(flag, **kw)
    e.add_argument("--plan", required=True,
                   help="strict data-bound panel plan JSON (lazypack_render.py schema)")
    e.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_S)
    e.add_argument("--force", action="store_true",
                   help="deprecated; active concurrent renders are refused")
    e.set_defaults(func=cmd_enqueue)

    r = sub.add_parser("run", help="render + upload + append + sync "
                                   "(executed by the compute worker)")
    for flag, kw in common.items():
        r.add_argument(flag, **kw)
    r.add_argument("--plan", required=True)
    r.add_argument("--out-dir", required=True)
    r.add_argument("--job-id", default=None,
                   help="compute_queue receipt id for producer output write-back")
    r.add_argument("--render-cmd", default=None,
                   help="TEST HOOK: replace the deterministic render step; invoked as "
                        "`<cmd> <plan> <out_dir>`")
    r.add_argument("--upload-cmd", default=None,
                   help="TEST HOOK: replace Supabase upload; invoked as "
                        "`<cmd> <png>` and must print the URL")
    r.add_argument("--no-sync", action="store_true",
                   help="TEST HOOK: skip single-article Supabase sync")
    r.set_defaults(func=cmd_run)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
