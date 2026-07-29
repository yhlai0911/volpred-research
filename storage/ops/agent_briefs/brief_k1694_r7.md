# K1694 round-7 — certify the FULL claim surface (the science already PASSed)

**Model**: opus / xhigh (per model_router, task_type=experiment, attempt=0 — this is NOT an
escalation. Round 6 returned **PASS** with zero blocking defects; nothing failed. Raising effort
for a passing experiment would be the wrong ladder, so the attempt counter stays at 0.)

**Task**: `k1694_cert_round7_20260730`
**Parent task**: `assign_3cf55dd4`
**Worktree (your cwd, already registered)**: `.claude/worktrees/dispatch-slot-1-e98b43fc-k1694`
**Branch HEAD**: `019b4e4f0` (main integrated into the round-6 branch on 2026-07-30)

## Read this first — you are NOT here to redo the science

Round 6 (`experiments/K1694/review_verdict.json`, reviewer Codex gpt-5.6-sol,
`reviewed_commit 2724b3587`) returned **verdict=PASS**, `blocking_defects: []`,
`merge_allowed: true`, `knowledge_promotion_allowed: true`. Both round-5 defects are RESOLVED.

The main thread has already independently re-verified that verdict and it holds:

- 7 of the 8 files in `reviewed_sha256` are still **byte-identical** on disk.
- `pytest experiments/K1694/test_K1694.py -q` → **50 passed** (the round-6 reviewer could not run
  it — read-only sandbox, no `linearmodels` — so the main thread ran it, twice: before and after
  the main integration).
- Round-5 defect 2 is genuinely fixed: `expected_month_endpoints()` appears in `test_K1694.py`
  only on the **asserted** side (line 397), checked against `calendar_fixtures.json`; the endpoint
  acceptance test (line 402) injects endpoints **from the fixtures**, never from the module.
- Every URL in `calendar_sources.md` resolves to `cmegroup.com` / `ice.com` / `ir.theice.com` /
  `cftc.gov`, or a `web.archive.org` snapshot of those domains. No secondhand aggregator.
- The knowledge entry is already written (main thread, item `e32f1aa8`, K1259-compliant).

**Do not re-litigate the NULL verdict, do not re-run the estimator, do not touch thresholds.**
If you find yourself editing `K1694.py`, stop — you have misread this brief.

## What is actually blocking the merge

`scripts/experiment_gates.py` review-certification refuses the merge, and it is **right** to:
`reviewed_sha256` pins only **3 of the 8** claim-surface files.

| path | state |
|---|---|
| `K1694.py`, `K1694_results.json`, `test_K1694.py` | pinned, hashes match |
| `README.md` | reviewed `6d54a151e63b…`, now `99da3402e8a2…` |
| `figures/fig2_regime_2x2.png` | in the claim surface, never pinned |
| `figures/fig3_interaction_coef.png` | in the claim surface, never pinned |
| `lag_sensitivity.py` | in the claim surface, never pinned |
| `gate_history/a5896554__K1694.py` | in the claim surface, never pinned |

Two things worth understanding before you start:

1. **The README drift is structural, not tampering.** Commit `1a4f43d90`
   (`[codex] record K1694 round-6 PASS`) flipped the README status line from "round 6 審查中" to
   "round 6 **PASS**". In other words, *the act of recording the verdict invalidated the verdict's
   own README hash*. Diff `2724b3587..1a4f43d90 -- experiments/K1694/README.md` and confirm this
   for yourself — it is 12 lines, all bookkeeping. If you find anything in that diff that changes
   a number, a thicket of claims, or a limitation, that IS a blocking defect and you must say so.
2. **The figures and `lag_sensitivity.py` were not unreviewed.** Round 6's
   `requirements_verified.full_rerun_no_hand_edits` explicitly states that `K1694.py`,
   `lag_sensitivity.py` and the figures were regenerated with consistent hashes. The reviewer
   looked at them; it just never listed them in `reviewed_sha256`. This is a **verdict-completeness
   gap**, not an unreviewed-artifact gap.

## Deliverable — one file, generated not transcribed

```bash
uv run python scripts/experiment_gates.py verdict-template \
  --path experiments/K1694 --out /tmp/k1694_r7_template.json
```

That template pins **all 8** current hashes for you. Read the frozen bytes, then fill it in and
write it to `experiments/K1694/review_verdict.json`:

- `kid`, `round: 7`, `reviewer` (model / effort), `reviewed_at` (**ISO8601 UTC with a real `Z`
  offset — round 6 wrote local Taipei time with a `Z` suffix, which is wrong; do not copy that**),
  `reviewed_commit` (the SHA you actually read), `review_artifact`.
- `verdict`: PASS or FAIL. `blocking_defects: []` iff PASS.
- `reviewed_sha256`: all 8 paths.
- **Preserve** round 6's `round5_defects_resolved`, `requirements_verified`,
  `accepted_limitations` and `reviewer_could_not_verify` content — this round supersedes the
  round-6 file, so anything you drop is lost from the record. Carry it forward, and mark that
  the pytest gap in `reviewer_could_not_verify` was closed by the main thread (50 passed).

### What you must actually verify for the 5 newly-pinned paths

- `README.md`: does every number in it match `K1694_results.json`? The README must not overstate
  the NULL. Verify the `2724b3587..1a4f43d90` diff is bookkeeping only.
- `figures/fig2_regime_2x2.png`, `figures/fig3_interaction_coef.png`: these are **reader-facing**.
  Do they depict what the results JSON says — including the fact that spec1 is NULL while spec2's
  continuous analogue is significantly **positive** (opposite to crowding-out)? A figure that
  reads as "crowding-out confirmed" would be a blocking defect.
- `lag_sensitivity.py`: check the lag convention. AGENTS.md rule 11 — signal from t-1, return at
  t; explicit `.shift(1)` or equivalent. Confirm the baseline uses the same lag.
- `gate_history/a5896554__K1694.py`: this is the preserved round-5 module the fixture oracle is
  tested against. Confirm it is genuinely the old frozen copy and is not imported by the live run.

## Rules

- `AGENTS.md` 研究誠實原則 — especially 9 (report NULL honestly), 10 (do not overclaim),
  11 (lookahead), 12 (seed).
- **Never hand-edit a verdict to make a gate pass.** K1709 reached main carrying a FAIL and turned
  CI red four times; that is why this gate exists. If the honest answer is FAIL, write FAIL.
- Do not modify `storage/memory/knowledge.json`, `storage/reports/feed.json`, or any shared state
  (K1259). Your writes belong under `experiments/K1694/`.
- Commit your work in the worktree before you finish.

## Success criterion

`experiments/K1694/review_verdict.json` exists, pins all 8 claim-surface hashes at the bytes you
read, and `uv run python scripts/experiment_gates.py certify --path experiments/K1694` (or the
merge script's certification step) passes — or it says FAIL with defects the main thread can act
on. Both are acceptable outcomes; a fabricated PASS is not.
