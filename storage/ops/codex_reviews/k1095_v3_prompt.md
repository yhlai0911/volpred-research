# Adversarial re-review — K1095-v3 (frozen bytes)

You are the independent adversarial reviewer. You previously reviewed K1095-**v2** and
returned **FAIL** with four blocking defects. This is the remediation run, **v3**, a new
experiment directory (v2 and its FAIL review stay frozen as historical evidence; v3 does
not rehabilitate them).

Your job: decide **PASS** or **FAIL** on the frozen bytes listed below. Default to FAIL if
uncertain. A PASS here authorises a merge into `main`, so treat it as a certification, not
an opinion.

## Where the bytes are

Registered linked worktree (read-only for you):

```
/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-6ec34837-k1095v3
```

Branch `wt/dispatch-slot-1-6ec34837-k1095v3`, HEAD `2519fd345d38a05604f6fea6e1366692f50f6799`,
working tree clean at freeze time.

### SHA-256 pin (relative to `experiments/k1095_v3/`)

| file | sha256 |
|---|---|
| `README.md` | `8a08b157aa61b06092420bc908754add542be915bb60ba416f39a6d6e87477db` |
| `k1095_v3.py` | `f7835f6447237475e4ce0e16462b4300afbda804e8dd585a1ed81d936b1a4b81` |
| `test_k1095_v3.py` | `c0f840dba9f1a1968d6bf13906f090700c2841eed2f7eb201afc5bc7a1974bb5` |
| `k1095_v3_results.json` | `020256ff1e5f43f2241f2c491c5adf323c4465571915fd1b252e4a51dd605828` |
| `reproduce_spec.json` | `ec014c5f799842ea33b857b887da674fdb7360461641a89e323742be313b1eb4` |
| `reproduce_report.json` | `26cabb82ecbcacd8f5ce0025dbf16d7bd7859b2497e38a2c59d21560f9d00001` |
| `input_manifest.json` | `8c86f5b69e7a41f05037eb63f44adbc177fa5e450fbf0744e39f2c3b1938a6a8` |
| `k1095_v3_schedule_grid.png` | `33b4f7466e57bb4f61e7aeb25a90d7f885cf60de5f12464a7b7bc1e22c953a99` |

**First action: re-hash these eight files yourself** (`shasum -a 256`) and record whether
each matches. If any digest differs, stop and return `FAIL` with reason
`BYTES_NOT_FROZEN` — you are then not reviewing what was certified.

## What you must adjudicate

The four blocking defects you raised on v2 are written up in
`experiments/k1095_v2/CODEX_REVIEW.md` (same worktree), section
"Required remediation before re-review". Read it first, then judge each one **independently**
on v3's bytes and mark PASS / FAIL per defect:

1. **TIMING (T+2 leak).** v2's `switch_weight()` re-shifted already-lagged
   `w_vix_raw` / `w_a4f_raw` and the mask, so the primary cell actually traded T+2. v3
   claims a single timing convention: weights use information through t-1, `mask[t]`
   selects the engine for `return[t]` with no second shift. Verify in
   `k1095_v3.py` (`switch_weights`, `net_returns`, the `vix.shift(1)` site, the A4f
   snapshot semantics) and in the focused tests (weekday event, weekend event, the
   2024-04-04/05 TWSE holiday gap, inclusive window endpoints, the exact date where the
   chosen engine's weight meets the traded return). Say explicitly whether any lookahead
   or double-lag remains.

2. **S1 point-in-time statutory calendar.** Check the pre-2013 listed consolidated 45-day
   rule and Aug-31 half-year endpoint, the FY2022+ 75-day annual regime for issuers with
   PIT paid-in capital ≥ TWD 10bn (FSC GL000593), the financial-sector Q1/Q3 handling under
   FSC GL000473 (45-day filing + documented 60-day correction endpoint, both event rows
   preserved), the financial-holding H1 endpoint (must be 8/31, not +61d), and that the
   Securities and Exchange Act change date reads 2010-06-02 (the v2 "1999-06-02 (民國99)"
   year error). Frozen primary sources are hashed in `input_manifest.json` and stored under
   `experiments/k1095_v3/sources/`. Also judge whether narrowing the empirical statutory
   period to FY2008–FY2021 (no reliable frozen PIT capital panel) is disclosed honestly
   rather than papered over, and confirm current company size is never substituted for PIT
   size (a missing classification must raise `ContractBlocked`).

3. **Inference.** v2 claimed Sharpe results from a HAC test that only tested mean-return
   differences. v3 adds a paired circular moving-block bootstrap on the Sharpe difference
   (block `ceil(n^(1/3))`, 1,000 paired resamples, seed 42) and keeps HAC but renames it
   mean-return inference. Verify: the bootstrap is genuinely paired and block-structured;
   the primary cell (S1/t1/±5) is pre-specified rather than picked post hoc; the multiplicity
   correction covers the full declared family (27 cells × 2 comparisons = 54 tests) under
   both Bonferroni and BH-FDR; and no surviving sentence claims significance that the
   corrected p-values do not support. v2's S2/t1 p=0.0111 → 0.133 corrected must not be
   reported as a finding.

4. **Capture estimand.** v2's capture rate mixed sample definitions. v3 reports
   event-level rates with no deduplication: full scheduled-period 350/560 = 62.50%,
   strictly OOS 115/210 = 54.76%, and OOS actual-traded/eligible mask 115/210 = 54.76%.
   Your own v2 recompute produced 57.89% all-sample / 50.83% OOS / 47.50% OOS traded-mask.
   **Explain the gap**: decide whether v3's numbers follow from an honestly stated,
   internally consistent estimand (event rows, no dedup, mask reconciliation asserted in
   code) or whether the definition was reshaped to flatter numbers. Check the code assertion
   that the OOS mask compared against actual events is byte-identical to the mask selecting
   the traded branch. If a de-duplicated unique-trading-day rate is still reported anywhere,
   it must be separately named.

## Also check (not among the original four, but blocking if wrong)

- The headline verdict — "among tested schedule family no event-switch setting OOS Sharpe
  point estimate above both pure strategies" — must not be overstated into a causal,
  equivalence, or universal no-benefit claim anywhere in README or results JSON.
- Reported OOS numbers must reconcile to `k1095_v3_results.json`: n=1,438 close-to-close
  returns 2017-02-15→2022-12-30, pure VIX Sharpe 0.9960, pure A4f 0.9634, primary cell
  0.7492, 27-cell range 0.7413–0.9348, `cells_beating_both_pures` empty, min raw Sharpe
  p=0.0849, min Bonferroni 1.0, min BH-FDR 0.5513.
- Transaction cost (20bp per one-way weight change) applied identically to pure and
  switching policies — no baseline handicap.
- No fabricated review artifact: `experiments/k1095_v3/` must contain **no**
  `review_verdict.json` at freeze time (the run correctly refused to self-certify).

## Output format

Return markdown. Start with a single line:

```
VERDICT: PASS
```
or
```
VERDICT: FAIL
```

Then:

- **Byte-freeze check** — table of the eight files, expected vs recomputed sha256, match yes/no.
- **Per-defect adjudication** — one section per defect 1–4, each opening with `DEFECT n: PASS`
  or `DEFECT n: FAIL`, followed by the specific file/line evidence you relied on. Cite line
  numbers.
- **Additional findings** — anything blocking that the four defects did not cover.
- **Required remediation before re-review** — only if FAIL; numbered, each item concrete
  enough to act on without re-reading your prose.

Rules: cite evidence for every claim; if you cannot verify something, say "unverified" and
treat it as blocking rather than assuming good faith. You have read-only sandbox access —
do not modify any file, and do not write `review_verdict.json` yourself; the collecting
main thread writes it from your verdict.
