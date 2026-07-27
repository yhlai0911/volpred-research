# Codex primary-path review — K1698 certification (round 5, re-anchored)

You are the primary-path reviewer for experiment **K1698**. This round certifies the
**salvage-consolidated canonical** that now lives in the main checkout. Produce an
independent PASS / FAIL. You have **no authority to fix** anything — read-only sandbox.

## Why this round is re-anchored (read first)

The rev-series worktree `dispatch-slot-2-c5cafe39-k1698` that carried rounds 1–4 was
**salvaged and retired** (adjudications `worktree_salvage_dispatch-slot-2-c5cafe39-k1698`
and `wsb_remed_dispatch-slot-2-c5cafe39-k1698` both succeeded). That worktree no longer
exists. Its rev-series filenames (`k1698_rev2_results.json`, `run_log_rev4.txt`,
`k1698_rev3_remediation.json`, …) and the old freeze
`storage/ops/codex_reviews/k1698_rev4_freeze.txt` are **obsolete** — do not read them,
do not review against them. A prior rerun (`k1698_rev4_codex_round5_rerun2`) aborted
precisely because it hashed those vanished files; that abort is the reason you are here.

The certify target is the **consolidated canonical** `experiments/k1698/` in the main
checkout. Review the bytes that are actually on disk now.

## History (background only — do NOT carry any prior verdict forward)

The rev-series reached round 4 with **every substantive item PASSed**; its FAIL rested on
two documentation-evidence MINORs that lived in rev-series files which no longer exist
(`NEW-MINOR-RUNTIME-EVIDENCE`, `NEW-MINOR-AUDIT-RECORD`). Those files are gone; those two
findings are moot by construction. You are not re-litigating them — you are certifying the
consolidated artifact on its own current bytes.

## The bytes under review (frozen)

`storage/ops/codex_reviews/k1698_rev5_freeze.txt` — sha256 of 7 files:
`experiments/k1698/{README.md, k1698.py, k1698_results.json, run_log.txt,
fig1_implied_scale_bootstrap.png, fig2_trinity_before_after.png, fig3_scale_factors.png}`.

If **any** file you read does not match its listed hash, **stop and say so** — the review
is invalidated (that is exactly how the last attempt correctly aborted).

Repo root (read-only): `/Users/yhlai0911/volpred-research/`

## What K1698 claims (verify against the bytes, don't take on faith)

K1698 is a scale-recalibration gating experiment (K1684 BLOCK 後合規重跑). Its headline
gate verdict, as stated in `README.md §1`:

- **GATE_VERDICT = H2_REJECTED** → route to FRL / Journal of Forecasting short note, not a
  full IJF paper.
- Trigger: leg-1 aligned target (0050 r²) HAR-vs-GJR non-nested QLIKE DM
  **t = +1.47 (p = 0.14, n = 436)** — no evidence HAR beats robust GJR; point estimate
  still favours GJR.
- Deeper v2 finding: even HAR's own-target headline t moves from **−5.25** (old K854 RV) to
  **−2.06** (new gap-complete aligned RV), isolating the effect to RV reconstruction via a
  bridge run that reproduces the K854 world.

## Your scope — a full certification pass

1. **Freeze integrity**: every read file matches its hash. State it explicitly.
2. **Claim–evidence match**: every quantitative claim in `README.md` must be traceable to
   `k1698_results.json` bytes. Spot-check at minimum: the leg-1 DM `t_stat = 1.4694` and
   `n = 436` (`/gate/leg1_qlike/aligned_target_r2_0050/`), `GATE_VERDICT = H2_REJECTED`,
   `n_oos = 450`, the own-target −5.25 vs −2.06 bridge/primary contrast, and the scale
   factors table. Any README number that is not in the results JSON, or contradicts it, is a
   blocker.
3. **No causal claim exceeding telemetry** — apply the same standard that produced the
   round-4 FAIL: no statement of evidence may overreach what the bytes show; no runtime /
   load attribution without a receipt in `run_log.txt`.
4. **Lookahead / methodology sanity**: confirm the lookahead audit assertions in the
   results JSON are all `True` and that the gate dataflow (nested-DM role vs gate) is not
   circular. Flag any lookahead risk (signal from t−1, return at t) as a blocker.
5. **Reproducibility surface**: seed pinned, data pinned, atomic write — confirm the README
   claims match what the code and results show.

## Output contract

Write a verdict document (this file's `OUT` path) containing:

- `## Freeze integrity` — pass/fail on hashes.
- `## Claim-by-claim` — per-claim PASS/FAIL, each citing the exact bytes checked.
- `## Standing numerics` — confirm the headline numbers above are what the JSON holds.
- `## 新問題` — any new claim–evidence gap (empty if none).
- A final line of **exactly** `VERDICT: PASS` or `VERDICT: FAIL`.

Any surviving claim–evidence gap means FAIL. Do not soften a FAIL because a defect is
"small" — round 4 correctly failed on two MINORs.

**Do NOT write `experiments/k1698/review_verdict.json`.** You are read-only; the sandbox
will not let you, and self-signing is forbidden. The main thread fills that file from your
verdict on collect. Your job ends at the `VERDICT:` line.
