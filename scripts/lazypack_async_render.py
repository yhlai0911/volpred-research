#!/usr/bin/env python3
"""Async lazypack (懶人包圖組) pipeline — `enqueue` (writing agent) + `run` (compute worker).

Root cause (docs/error_log.md 2026-07-02 15:15 #4): the writing agent's 50-min
hard cap was shared between article body writing and the codex-exec lazypack
render (2-4 poster PNGs, ~5-15 min), squeezing body depth. This moves the render
off the writing fire onto the EXISTING compute_queue async lane
(storage/ops/compute_queue/ + */15 compute-worker; 0 Claude tokens — same split
as reference_compute_queue_token_split):

    writing agent : body done → publish draft (lazypack NOT required at draft
                    stage) → `lazypack_async_render.py enqueue --article-id
                    mile_x --experiment Kxxxx --plan plan.json`
    compute worker: `run` → gen_lazypack_codex.py (codex exec writes+runs a
                    data-bound render script) → upload PNGs → append
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

plan.json = gen_lazypack_codex.py panel schema: [{name, info, must_show?,
style?, alt?}] — one PNG per panel; optional `alt` overrides the image alt text.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "src"), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

JOB_ID_PREFIX = "lazypack-"
DEFAULT_TIMEOUT_S = 1800  # codex render ≤900s + upload/append/sync headroom


def _resolve(path_like: str | Path) -> Path:
    p = Path(path_like)
    return p if p.is_absolute() else ROOT / p


def _load_panels(plan_path: Path) -> list[dict]:
    panels = json.loads(plan_path.read_text(encoding="utf-8"))
    if isinstance(panels, dict) and isinstance(panels.get("panels"), list):
        panels = panels["panels"]
    if not isinstance(panels, list) or not panels:
        raise ValueError(f"--plan must be a non-empty JSON list: {plan_path}")
    for i, p in enumerate(panels, 1):
        if not isinstance(p, dict):
            raise ValueError(f"plan panel {i} must be an object: {p!r}")
    return panels


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
    panels = _load_panels(plan_src)  # validate before queueing

    from volpred.publisher.publisher import has_lazypack_section
    if has_lazypack_section(str(art.get("content") or "")):
        print(f"note: {a.article_id} already carries a 懶人包圖組 section — "
              f"the async render will REPLACE it on completion.")

    # Persist the plan next to the job artifacts so the worker run is
    # self-contained and reproducible.
    jobs_dir = storage_dir / "lazypack_jobs" / a.article_id
    panels_dir = jobs_dir / "panels"
    jobs_dir.mkdir(parents=True, exist_ok=True)
    stored_plan = jobs_dir / "plan.json"
    stored_plan.write_text(
        json.dumps(panels, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    # Idempotency: a queued/running render for this article means the writing
    # fire double-called enqueue — skip instead of double-rendering.
    base_id = f"{JOB_ID_PREFIX}{a.article_id}"
    existing = sorted(cq.QUEUE_DIR.glob(f"{base_id}*.json")) if cq.QUEUE_DIR.exists() else []
    job_id = base_id
    taken: set[str] = set()
    for p in existing:
        try:
            j = json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"warn: unreadable queue file {p}: {exc}", file=sys.stderr)
            taken.add(p.stem)
            continue
        taken.add(str(j.get("id") or p.stem))
        if j.get("status") in ("queued", "running") and not a.force:
            print(f"skip: lazypack job already {j.get('status')} for "
                  f"{a.article_id} ({j.get('id')}); use --force to queue another")
            return 0
    n = 2
    while job_id in taken:
        job_id = f"{base_id}-r{n}"
        n += 1

    def _rel(p: Path) -> str:
        try:
            return str(p.relative_to(ROOT))
        except ValueError:
            return str(p)

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
    for s in a.source:
        script_args += ["--source", s]

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
            _rel(panels_dir / "render_lazypack.py"),
            *(_rel(panels_dir / f"{stem}.png") for stem, _ in _panel_specs(panels)),
        ],
        followup_brief=None,  # the job appends + syncs itself; no Claude followup
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
    candidates = [
        out_dir / "render_lazypack.py",
        *(out_dir / f"{stem}.png" for stem, _ in specs),
    ]
    actual = [path for path in candidates if path.is_file()]
    if not actual:
        return
    try:
        import compute_queue as cq

        if not cq.record_output_paths(job_id, actual):
            print(f"warn: could not record output paths for {job_id}", file=sys.stderr)
    except Exception as exc:  # metadata must not mask the renderer's real result
        print(f"warn: output path write-back failed for {job_id}: {exc}", file=sys.stderr)


def cmd_run(a: argparse.Namespace) -> int:
    storage_dir = _resolve(a.storage_dir)
    plan_path = _resolve(a.plan)
    out_dir = _resolve(a.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    panels = _load_panels(plan_path)
    specs = _panel_specs(panels)
    title = a.title or f"{a.article_id} 懶人包"
    job_id = getattr(a, "job_id", None)

    # 1) Render — codex exec writes + runs a data-bound render script.
    # 產出即交付：if every expected panel is already on disk (an earlier run —
    # or a hand-run of the generated render script — produced them before the
    # job died), the artifacts are finished goods. Re-rendering can only lose
    # them; deliver instead. This is what makes a retry of a failed job actually
    # rescue the article rather than replay the same failing render step.
    already = [
        stem for stem, _ in specs
        if (out_dir / f"{stem}.png").exists()
        and (out_dir / f"{stem}.png").stat().st_size > 1024
    ]
    if len(already) == len(specs):
        print(f"[lazypack_async] panels already rendered ({len(already)}/{len(specs)}) "
              f"in {out_dir} — skipping render, delivering existing artifacts")
    elif a.render_cmd:
        print(f"[lazypack_async] TEST HOOK ACTIVE: --render-cmd {a.render_cmd!r} "
              f"(bypasses gen_lazypack_codex.py; smoke/tests only)")
        cmd = shlex.split(a.render_cmd) + [str(plan_path), str(out_dir)]
    else:
        cmd = [sys.executable, str(ROOT / "scripts" / "gen_lazypack_codex.py"),
               "--plan", str(plan_path), "--out-dir", str(out_dir),
               "--title", title, "--article-id", a.article_id]
        for k in a.experiment:
            cmd += ["--experiment", k]
        for s in a.source:
            cmd += ["--source", s]

    if len(already) != len(specs):
        try:
            proc = subprocess.run(cmd, cwd=str(ROOT))
        finally:
            # Codex can write one or more panels and still return non-zero.  The
            # receipt must be updated before this function propagates failure.
            _record_job_outputs(job_id, out_dir, specs)
        if proc.returncode != 0:
            print(f"error: render step failed rc={proc.returncode}", file=sys.stderr)
            return 2
    else:
        _record_job_outputs(job_id, out_dir, specs)

    # 2) Verify every expected panel PNG exists (belt-and-suspenders — the
    # codex generator verifies too, but --render-cmd paths must not skip it).
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
        "--experiment": dict(action="append", default=[],
                             help="K-id evidence (repeatable)"),
        "--source": dict(action="append", default=[],
                         help="extra evidence file (repeatable)"),
        "--title": dict(default=None),
        "--storage-dir": dict(default="storage",
                              help="storage root (tests only; default: storage)"),
    }

    e = sub.add_parser("enqueue", help="queue the render on compute_queue "
                                       "(writing agent, after draft publish)")
    for flag, kw in common.items():
        e.add_argument(flag, **kw)
    e.add_argument("--plan", required=True,
                   help="panel plan JSON (gen_lazypack_codex.py schema)")
    e.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_S)
    e.add_argument("--force", action="store_true",
                   help="queue even if a render is already queued/running")
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
                   help="TEST HOOK: replace the codex render step; invoked as "
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
