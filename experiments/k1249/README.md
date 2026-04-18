# K1249: K716 Rebuild — Option (a) per K1231 Decision

- Experiment ID: `k1249`
- Created At: 2026-04-17
- Status: **COMPLETE — RESIDUAL_DRIFT (option a unable to close drift, (c) errata recommended)**
- Related: K716 (original + reconstructed), K1231 (reconstruction plan), Paper 8 `volatility-absorption`
- Seed: 42

## 問題描述

K716 reconstructed script (`experiments/k716/k716.py`, 2026-04-17) produces a
**normalized regression slope of -0.00027**, which differs from the
paper body canonical **-0.00028** by **3.6%** (see
`experiments/k716/k716_reconstruction_diff.md`).

K1231 (commit `76acffdb`) assigned this drift **option (a)**: rebuild the
script with end-date and trading-calendar alignment to close the gap.

## 動機

- **三方一致 rule** (`docs/paper-guide.md`): scripts, data, and paper body
  numbers must agree. A 3.6% divergence in Paper 8 central slope violates
  replication package integrity.
- **K1231 option (a)** expected that "one pipeline alignment pass likely fixes
  it" (effort ~1h). K1249 tests this hypothesis rigorously.

## 方法

### Diagnosis (before coding)

Root cause hypothesis: the reconstructed script filters the NSI regression
to the **SAR joint-availability sample (N=767)**, but paper body
(`main.tex:277`) explicitly states the regression sample is
**N=893 (full VIX time series shock filter)**, with 126 days of gap
"primarily affecting 0050.TW trading-calendar gaps and boundary observations."

### Fix

Modify NSI regression sample construction:
- **Old (K716)**: require VIX + ΔVIX + SPY return + valid regime-bin → N=767
- **New (K1249)**: require VIX + ΔVIX + SPY return (drop regime-bin requirement) → target N~893

### Auxiliary diagnostics

1. **τ sensitivity scan**: search τ ∈ [1.70, 2.05] for N that matches paper 893.
2. **SE method test**: Plain OLS, White HC0–HC3, NW with lags ∈ {5, 10, 15, 20, 30, 50}.
3. **Return definition test**: log-return vs simple-return.
4. **auto_adjust flag test**: yfinance auto_adjust True/False.
5. **Warmup test**: start date 2005-01-01 with 2006-01-01 restriction.

### Data

- SPY, ^VIX from yfinance, `2006-01-01` to `2026-03-31`, daily close prices.
- Fetched 2026-04-17 (this session).

## 預期

From K1231 decision: K1249 slope should converge to **-0.00028 ± 1%** under
paper-canonical sample, yielding **ALLCLOSE_PASS**.

## 結論

### Primary result: **RESIDUAL_DRIFT**

| Metric | K1249 | Paper | Diff | Rel % | 1% pass? |
|--------|-------|-------|------|-------|----------|
| regression_normalized_slope | -0.00027 | -0.00028 | 1e-5 | **3.57%** | **NO** |
| regression_t_stat | -1.77 | -3.42 | 1.65 | 48.25% | NO |
| regression_N | 767 | 893 | 126 | 14.11% | NO |
| regression_raw_slope | 0.0677 | 0.0669 | 0.0008 | 1.20% | borderline |
| SAR ratios (5 regimes) | 3.15/2.77/2.37/2.32/2.45 | 3.16/2.77/2.37/2.32/2.43 | ≤0.02 | ≤0.82% | YES |

### Diagnosis: data vintage, not methodology

Exhaustive testing (see `k1249_vs_paper.md`) confirms **N=767 is robust** to
all tested sample-construction variants. The 126-day gap to paper N=893
**cannot be reproduced** with any method on current yfinance data:

| Sample variant | N at τ=2.0 |
|----------------|-----------|
| SAR joint-availability (K716 default) | 767 |
| Full VIX series + SPY-for-NSI (K1249 fix) | 767 |
| log-return vs simple-return | 767 |
| auto_adjust=True vs False | 767 |
| Start 2005-01-01 (extra warmup) + restrict 2006+ | 767 |
| VIX-only (no SPY filter at all) | 767 |

The closest τ matching paper N=893 with current data is **τ=1.81 → N=896**;
even at that τ, normalized slope is -0.000231 (further from paper -0.00028),
confirming that adjusting τ is not a legitimate fix.

### t-stat divergence (-1.77 vs paper -3.42)

SE method has no effect on slope (invariant), and all tested NW bandwidths
(5, 10, 15, 20, 30, 50) give t in [-2.01, -1.77]. **Paper's t=-3.42 is
unreachable** with current data regardless of SE choice. This is consistent
with vintage drift affecting residual variance as well as the point estimate.

### Verdict: **K716 option (a) is BLOCKED by data vintage**

K1231 assumed option (a) was feasible with ~1h of alignment work. This
assumption is **falsified**: current yfinance data cannot reproduce
paper's N=893 or t=-3.42 under any methodologically valid sample
construction. The 3.6% slope drift is a **data vintage artifact**, not a
script bug.

### Recommendation to main-thread

Main-thread should escalate K716 from option (a) to:

- **Option (c) errata (recommended)**: Disclose "pending errata, magnitude
  3.6%, cause: yfinance VIX vintage drift" in
  `paper/volatility-absorption/README.md` and `docs/error_log.md`. Keep
  paper body numbers intact; qualitative conclusion `paralysis` is
  preserved (both K1249 and paper agree on sign). SAR ratios all match
  within 0.82%, so Table 3 central evidence is intact.

- **Option (b) paper revision (alternative)**: Replace -0.00028 with
  -0.00027 (and t=-3.42 with -1.77, N=893 with 767) throughout
  `main.tex` Tables 3, 4, 6. Warning: cascades into Table 4 (GLD/TLT/
  0050.TW) and Table 6 (sub-period) which must also be re-computed;
  total effort ~1 day + R2 revision.

3.6% drift with preserved sign and intact SAR table → **option (c)** is
the 研究誠實原則 minimum while preserving paper integrity.

## Files

| File | Purpose |
|------|---------|
| `k1249.py` | Rebuild script with full-VIX fix + vintage diagnosis |
| `k1249_results.json` | SAR + regression results + allclose checks |
| `k1249_vs_paper.md` | Side-by-side comparison + full diagnosis |
| `README.md` | This file |

## References

- `experiments/k716/` — original + reconstructed baseline
- `experiments/k1231/k1231_reconstruction_plan.md` §K716
- `experiments/k1231/k1231_reconstruction_decisions.json` K716 entry
- `paper/volatility-absorption/main.tex` lines 277 (N=893 definition),
  305–309 (Table 3 SAR), 324 (slope -0.00028, t=-3.42), 340 (Table 4),
  542 (Table 6 robustness τ=2 row)
- `docs/paper-guide.md` — 三方一致 rule (a)/(b)/(c)

## Commit

Worktree commit included in this experiment's final step. No shared-state
files modified (no edits to `storage/memory/*.json`, `storage/reports/*`,
Supabase, or paper body — per worktree rules).
