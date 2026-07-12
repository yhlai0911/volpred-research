#!/usr/bin/env python3
"""Codex primary-path review of K1701 (realized dispersion -> index vol/tail).

Runs from the compute queue rather than inside an hourly fire: the fire's Bash
tool caps at 600s and codex needs longer than that on a 1600-line experiment,
so two in-fire attempts died on the cap (2026-07-13 hourly-04). subprocess with
an explicit timeout is the sanctioned way to call codex from Python.

Emits the verdict to storage/ops/reviews/k1701_codex_review.json so the next
fire can gate the knowledge.json write on it.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from glob import glob
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "storage" / "ops" / "reviews" / "k1701_codex_review.json"
TIMEOUT_S = 2400

PROMPT = """Adversarial code review. Read experiments/k1701/k1701.py and \
experiments/k1701/k1701_data.py; grep experiments/k1701/k1701_results.json for numbers \
(never dump that file whole, it is 190KB).

K1701 asks: does realized dispersion between an index and its constituents (avg \
constituent vol vs index vol; rdisp = avg_vol/idx_vol) predict forward index variance \
and tails, incrementally over a level-only HAR baseline? Reported result is essentially \
NULL: 1 of 6 primary cells passes the gate; 0 of 12 incremental cells survive BH-FDR \
under Clark-West.

Your job is to find reasons the NULL is NOT trustworthy, not to rubber-stamp it. A false \
NULL is as damaging as a false discovery. Rule PASS / CONDITIONAL PASS / FAIL on each:

1. LOOKAHEAD. Signals from data <= t, scored on forward targets t+1..t+h. Check the \
forward-target construction and the expanding/rolling refit: for a training row j at \
horizon h, the label window must end strictly before the forecast origin i (j + h < i). \
If the training tail can see the forecast day, that is fatal.
2. NESTED TEST CHOICE. The incremental models are nested in the level-only baseline. \
Clark-West must carry the incremental claim; any raw Diebold-Mariano on a nested pair \
must be labelled diagnostic only, never the publication claim.
3. HAC BANDWIDTH. Repo hard rule: HAC lag must not be h-1 (at h=1 that is lag 0, i.e. no \
HAC at all). Confirm the canonical volpred.stats.model_evaluation.dm_test bandwidth feeds \
the reported statistic, that the local _nw_dm helper is used only for lag-sensitivity \
reporting, that dm_parity_check genuinely asserts equality with the canonical statistic, \
and that loss-differential acf is reported. Note the direction: negative autocovariance \
makes |t| LARGER after HAC, so a NULL is not automatically safe from a missing HAC.
4. MULTIPLE TESTING. 6 + 12 cells. Is BH-FDR applied over the right family, and is the \
1-of-6 passing cell reported honestly as likely noise rather than as a finding?
5. SURVIVORSHIP / MEMBERSHIP BIAS. Constituent baskets change. Is the basket \
point-in-time, and is residual bias discussed honestly rather than hidden?
6. SEED / PROVENANCE / REPRODUCIBILITY.

End with exactly one line of the form
VERDICT: PASS
or
VERDICT: CONDITIONAL PASS
or
VERDICT: FAIL
then at most 5 bullets naming the material issues. No preamble."""


def resolve_codex() -> str:
    found = os.environ.get("CODEX_BIN") or shutil.which("codex")
    if found and os.access(found, os.X_OK):
        return found
    for pattern in (
        os.path.expanduser("~/.nvm/versions/node/*/bin/codex"),
        "/opt/homebrew/bin/codex",
        "/usr/local/bin/codex",
    ):
        for cand in glob(pattern):
            if os.access(cand, os.X_OK):
                return cand
    raise SystemExit("codex binary not found")


def main() -> int:
    codex = resolve_codex()
    env = dict(os.environ)
    env["PATH"] = f"{Path(codex).parent}:{env.get('PATH', '')}"

    proc = subprocess.run(
        [codex, "exec", "-s", "workspace-write", "-"],
        input=PROMPT,
        capture_output=True,
        text=True,
        cwd=REPO,
        env=env,
        timeout=TIMEOUT_S,
    )
    output = proc.stdout or ""
    match = re.search(r"VERDICT:\s*(PASS|CONDITIONAL PASS|FAIL)", output)
    verdict = match.group(1) if match else "UNPARSED"

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(
            {
                "experiment_id": "k1701",
                "reviewer": "codex",
                "reviewer_source": "codex_exec primary path (compute queue)",
                "verdict": verdict,
                "exit_code": proc.returncode,
                "reviewed_at": datetime.now(timezone.utc).isoformat(),
                "stdout": output[-20000:],
                "stderr": (proc.stderr or "")[-4000:],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[k1701-review] verdict={verdict} exit={proc.returncode} -> {OUT}")
    return 0 if verdict != "UNPARSED" else 1


if __name__ == "__main__":
    sys.exit(main())
