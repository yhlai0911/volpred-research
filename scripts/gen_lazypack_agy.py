#!/usr/bin/env python3
"""Antigravity (agy) middle-layer lazypack code-writing harness.

Chain position (assign_5195e5ae D2, 2026-07-20): codex bespoke
(scripts/gen_lazypack_codex.py) → THIS harness → deterministic self-repair
(scripts/lazypack_render.py).  When codex is quota-walled (whole ChatGPT
windows at a time — e.g. the 2026-07-20 outage lasting to ~07-25), the async
caller fast-skips here instead of letting every lazypack job die against the
same wall.  agy is the free Google-OAuth Antigravity CLI; a failed or missing
agy still falls through to the deterministic renderer, never to a dead job.

Interface: drop-in sibling of gen_lazypack_codex.py — same CLI flags, same
plan/evidence contract, same rc semantics (0 ok, 1 real failure, 2 budget/
timeout, 3 CLI missing).  The write→local-render→bounded-repair loop itself is
REUSED from gen_lazypack_codex._generate (single owner of the prompt contract
and budget machinery); only the code-writing CLI differs:

  codex: `codex exec` reading the prompt on stdin
  agy  : `agy -p "<prompt>" --dangerously-skip-permissions` — the prompt is an
         ARGUMENT, never stdin (`echo .. | agy -p` dies with "flag needs an
         argument"; see memory reference_antigravity_cli).  Model override is
         the ANTIGRAVITY_MODEL env var; agy has no `-m` flag.

Usage (same as gen_lazypack_codex.py):
  uv run python scripts/gen_lazypack_agy.py \
    --article-id mile_x --title "..." \
    --plan storage/lazypack_jobs/mile_x/plan.json \
    --out-dir storage/lazypack_jobs/mile_x/panels \
    --source <evidence.json> ...
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

import gen_lazypack_codex as glc  # noqa: E402 — single owner of the loop
from dispatch_supervisor.procutil import kill_tree  # noqa: E402
from volpred.ops import termination  # noqa: E402
from volpred.ops.execution.registry import (  # noqa: E402
    ProviderRegistryError,
    authorize_provider_spawn,
    verify_spawn_receipt,
)


def _resolve_agy_bin() -> str:
    """Absolute agy path; PATH first, then the documented install location."""
    found = shutil.which("agy")
    if found:
        return found
    candidate = Path.home() / ".local" / "bin" / "agy"
    if os.access(candidate, os.X_OK):
        return str(candidate)
    return "agy"


AGY_BIN = _resolve_agy_bin()
AGY_DEFAULT_MODEL = "gemini-3.6-flash-high"


def _run_agy(prompt: str, out_dir: Path, timeout_s: float,
             model: str | None) -> tuple[int, str]:
    """One bounded headless agy call. Returns (rc, combined output tail).

    Mirrors gen_lazypack_codex._run_codex: rc 3 = CLI missing, rc 2 = timed
    out, never raises on agy failure — whether the render script landed is the
    only outcome the caller judges.  Runs in its own session so a timeout kill
    reaches agy's workers too (same escaped-descendant class as codex; see
    _kill_process_group in gen_lazypack_codex.py).
    """
    env = os.environ.copy()
    selected_model = model or AGY_DEFAULT_MODEL
    env["ANTIGRAVITY_MODEL"] = selected_model
    try:
        receipt = authorize_provider_spawn(
            contract_id="lazypack.agy",
            model_id=selected_model,
            executable_path=AGY_BIN,
            environment=env,
        )
        verify_spawn_receipt(receipt)
    except ProviderRegistryError as exc:
        return 4, f"provider policy denied agy: {exc}"
    cmd = [
        receipt.resolved_executable,
        "-p",
        prompt,
        "--dangerously-skip-permissions",
    ]
    env.update(receipt.environment())
    try:
        proc = subprocess.Popen(
            cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, cwd=str(ROOT), env=env,
            start_new_session=True,
        )
    except FileNotFoundError:
        return 3, ("agy CLI not found — install via the official "
                   "antigravity.google install.sh (memory reference_antigravity_cli)")
    try:
        out, err = proc.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        ledger = termination.DEFAULT_LEDGER_PATH
        intent = termination.arm(
            target_kind="pgid", target_id=proc.pid,
            reason="lazypack_agy_timeout", actor="gen_lazypack_agy",
            signal_sequence=termination.terminating_signals(),
            ledger_path=ledger,
        )
        if not kill_tree(proc.pid, intent=intent, ledger_path=ledger):
            print(f"[gen_lazypack_agy] WARNING: could not confirm agy pid "
                  f"{proc.pid} and its children are dead — a surviving worker "
                  f"may still write to the output dir", file=sys.stderr)
        try:
            out, err = proc.communicate(timeout=30)
        except Exception as e:  # noqa: BLE001
            from volpred.ops.diagnostics import warn

            warn("gen_lazypack_agy", "drain after kill failed", err=str(e))
            out, err = "", ""
        tail = ((out or "")[-1000:] + "\n" + (err or "")[-1000:]).strip()
        return 2, (f"agy timed out after {timeout_s:.0f}s "
                   f"(process tree killed)\n{tail}")
    out = out or ""
    err = err or ""
    return proc.returncode, (out[-2000:] + "\n" + err[-2000:]).strip()


def main() -> int:
    print("[gen_lazypack_agy] MIDDLE-LAYER bespoke data-bound renderer "
          "(codex → agy → deterministic)", file=sys.stderr)
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--experiment", action="append", default=[],
                    help="K-id — auto-adds experiments/<k>/ evidence files; repeatable")
    ap.add_argument("--source", action="append", default=[],
                    help="extra source file (data/refs/.md); repeatable")
    ap.add_argument("--article-id",
                    help="feed.json article id (mile_...) — adds article content as a source")
    ap.add_argument("--title", default="懶人包")
    ap.add_argument("--plan", required=True,
                    help="JSON file: [{name, info, must_show?, style?}] or strict {panels:[...]}")
    ap.add_argument("--out-dir", required=True, help="output dir for the PNG set")
    ap.add_argument("--model",
                    help="override agy model via ANTIGRAVITY_MODEL (default: agy config)")
    ap.add_argument("--budget-s", type=float, default=glc.DEFAULT_BUDGET_S,
                    help="wall-clock budget for agy write + local render + "
                         f"repair rounds combined (default: {glc.DEFAULT_BUDGET_S}s)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the prompt and exit (no agy call)")
    a = ap.parse_args()

    plan_document = json.loads(Path(a.plan).read_text(encoding="utf-8"))
    evidence_labels: dict[str, str] = {}
    if isinstance(plan_document, dict):
        evidence = plan_document.get("evidence")
        if isinstance(evidence, dict):
            evidence_labels = {
                str(alias): str(spec["label"])
                for alias, spec in evidence.items()
                if isinstance(spec, dict) and spec.get("label")
            }
    panels = plan_document
    if isinstance(plan_document, dict) and isinstance(plan_document.get("panels"), list):
        panels = plan_document["panels"]
    if not isinstance(panels, list) or not panels:
        print("ERROR: --plan must be a non-empty JSON list (or {panels:[...]})",
              file=sys.stderr)
        return 1

    out_dir = Path(a.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    sources = glc._gather_sources(a, out_dir)
    if not sources:
        print("ERROR: no sources — provide --experiment / --source / --article-id",
              file=sys.stderr)
        return 1

    title = a.title
    if title == "懶人包" and a.experiment:
        title = f"{a.experiment[0]} 懶人包"

    if a.dry_run:
        print(glc._build_prompt(
            title, panels, sources, out_dir,
            font=glc._resolve_cjk_font(),
            evidence_labels=evidence_labels,
        ))
        return 0

    return glc._generate(title, panels, sources, out_dir,
                         budget_s=a.budget_s, model=a.model,
                         evidence_labels=evidence_labels,
                         run_writer=_run_agy, writer_name="agy")


if __name__ == "__main__":
    sys.exit(main())
