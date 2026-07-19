# Primary-path review — K741/K904 canonical NFP calendar re-run (round 2)

You are reviewing a **frozen, already-committed** experiment branch that wants to enter `main`.
Sandbox is read-only. Do not propose diffs you cannot verify; read the actual bytes.

## Where the code is

Worktree: `.claude/worktrees/dispatch-slot-1-5741c175-k741` (branch `k741-nfp-canonical`)

Read these, in this order:

1. `experiments/k741/nfp_canonical_vs_proxy_comparison.md` — the report. §7 records what round 1
   claimed and why it was wrong.
2. `experiments/k741/k741_nfp_event_study_canonical.py` — the implementation.
3. `experiments/k741/k741_nfp_event_study_canonical_results.json` — the numbers.
4. `experiments/k904/k904_task_s4_nfp_canonical.py` + `..._results.json` — the corroborating arm.
5. `paper/volatility-absorption/main_v3.tex` — §sec:nfp and the intro paragraph that cites it.
6. `paper/volatility-absorption/reproduce.py` — the T5 gate block that binds the paper's printed
   numbers to the JSON.

Diff against `main` with: `git -C .claude/worktrees/dispatch-slot-1-5741c175-k741 diff main...HEAD`

## Context: round 1 FAILed, this is the remediation

Round 1 (2026-07-19) returned FAIL on three defects, all claimed fixed here:

- **B1** the report quoted a single proxy→canonical delta as a *pure date-source effect*, when the
  two arms differed in both the event calendar and the release→trading-day mapping. Claimed fix: a
  full 2×2 factorial (`factorial_cells`, `factor_decomposition`) that quotes a date effect only at
  a fixed mapper.
- **B2** the k741 estimation frame leaked 21 pre-2010 control days while the label said
  "January 2010 to March 2026". Claimed fix: warm-up retained for lags, estimation sliced to
  2010-01-01. This moves headline p from 0.0479 to 0.0506 — across the 5% line.
- **B3** the archived release→trading-day mapper resolved *backward* on market holidays
  (a lookahead, 5 Good Fridays). Claimed fix: forward-only mapping, asserted.

## What to decide

Answer each, with the file:line or JSON path you checked:

1. **Is the 2×2 real?** Do `factorial_cells` actually hold four distinct cells computed from four
   distinct specifications, or is any cell a copy/derivation of another? Does
   `factor_decomposition` isolate each factor at a fixed level of the other, as it claims?
2. **Is the estimation window honest?** Verify the frame is sliced to 2010-01-01 for estimation
   while lags still see warm-up data. Confirm `n_nfp=194`, `n_non_nfp=3890` are what the code
   actually produces, not constants.
3. **Is the forward mapper leak-free?** Verify no event maps to a trading day strictly before its
   release date, for every one of the 194 releases. Check the assertion is real and reachable.
4. **Is the calendar itself right?** `provenance` claims FRED/ALFRED release id 50, 161 exact
   matches, 33 shifted months, 1 phantom proxy month (2025-10, shutdown). Spot-check at least four
   shifted months against the stated cause; a `+7d` shift should correspond to the 1st falling on a
   Friday.
5. **Does the paper match the JSON?** Every number in `main_v3.tex` §sec:nfp — the table, the two
   footnotes, the intro paragraph — must trace to `k741_nfp_event_study_canonical_results.json`.
   Flag any number in the tex with no JSON source.
6. **Is the weakened claim weak enough?** The paper now says the regime contrast is *not*
   established (bootstrap CI [-0.10, 0.79] includes zero) and rests inference on the SAR evidence.
   Is any sentence still stronger than the evidence supports? Is the "difference in significance is
   not significance of difference" correction applied everywhere, including the intro paragraph?
7. **Bootstrap validity.** 20-day circular moving-block, B=10000, regime ratios re-derived per
   replicate, seed 20260719. Is the block bootstrap appropriate for a statistic defined on a
   *subset* of days selected by calendar? Does re-deriving regime membership per replicate do what
   the report says?

## Output format

Plain markdown. Start with a single line: `VERDICT: PASS` or `VERDICT: FAIL`.
Then per-question findings. Then, if FAIL, a numbered list of **bounded** required fixes — each one
must name the file and the specific defect, not a direction of travel.

PASS means: the numbers are reproducible from the code on the pinned snapshot, the paper's prose
does not outrun them, and nothing in the correction introduces a new lookahead or leak. A defect
that only affects an archived, uncited part of the experiment is a NOTE, not a FAIL.
