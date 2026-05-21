# K570b: Earnings Season VT — Lookahead Fix & Methodology Corrections

**Parent experiment**: K570 (`experiments/k570/`)  
**Date**: 2026-05-18  
**Trigger**: Post-publish Codex review found HIGH-severity lookahead bias in K570  
**Review doc**: `experiments/k570/k570_post_publish_codex_review.md`

---

## What Was Fixed

K570's post-publish Codex review (2026-05-18) identified four issues. This experiment corrects all of them.

### Fix 1 — Lookahead Bias [HIGH]

**Problem**: `run_vt_strategy()` used `vix.values` (closing VIX at day *t*) to set `weights[t]` (applied to day-*t* return). VIX close is only available after the market closes on day *t*, so this was a one-day lookahead.

**Fix**: `vix_lag = vix.shift(1).bfill()` is applied at the top of `run_vt_strategy()`. All weight calculations use `vix_lag.values` instead of `vix.values`.

**Impact**: Baseline Sharpe dropped from **1.4251 → 0.3801** (−73.3%). The original K570 Sharpe of 1.43 was almost entirely an artefact of lookahead bias. The true VT Sharpe with this data and methodology is ~0.38.

### Fix 2 — HAC Test Rename [MEDIUM-HIGH]

**Problem**: `dm_test_sharpe()` was misnamed. It computes a HAC (Newey-West) mean return differential test — not a proper Diebold-Mariano forecast loss test.

**Fix**: Renamed to `hac_return_diff_test()`. Docstring updated: *"HAC return-differential test (Newey-West). Tests H0: mean return difference = 0. Note: NOT a proper Diebold-Mariano forecast loss test."* All call sites updated.

### Fix 3 — Block Bootstrap [MEDIUM]

**Problem**: `bootstrap_sharpe_diff()` used i.i.d. resampling, which ignores serial correlation in daily returns and produces confidence intervals that are too narrow.

**Fix**: Replaced with circular block bootstrap using `block_size = max(21, int(n^(1/3)))` (≈ 21 trading days ≈ 1 month). This properly accounts for autocorrelation. CIs are now wider and more honest.

### Fix 4 — OOS Period Labels [MEDIUM]

**Problem**: The three robustness subperiods were labelled "3 non-overlapping OOS periods". They overlap: 2012–2017 and 2016–2020 share 2016–2017; 2016–2020 and 2020–2025 share 2020.

**Fix**: Relabelled as "3 overlapping subperiod robustness checks" throughout code and JSON output.

---

## Results

### Full Sample (2005–2026)

| Strategy | Ann Ret | Ann Vol | Sharpe | MDD |
|---|---|---|---|---|
| Buy & Hold | 10.24% | 19.00% | 0.434 | −55.2% |
| 12/VIX Baseline | 5.59% | 9.45% | **0.380** | −29.5% |
| Earnings Enhanced (10/14) | 5.93% | 10.35% | 0.379 | −32.3% |
| Earnings-Only VT | 8.65% | 17.72% | 0.375 | −55.5% |
| Anti-Earnings VT | 6.65% | 11.66% | 0.399 | −33.7% |

### HAC Tests vs Baseline (Harvey |t| > 3.0 threshold)

| Strategy | HAC t-stat | p-value | Block-Boot 95% CI | Verdict |
|---|---|---|---|---|
| Earnings Enhanced | +1.336 | 0.182 | [−0.045, +0.054] | FAIL |
| Earnings-Only VT | +2.297 | 0.022 | [−0.141, +0.207] | FAIL |
| Anti-Earnings VT | +1.820 | 0.069 | [−0.095, +0.150] | FAIL |

None of the three alternatives clears Harvey's t > 3.0 threshold.

### Cross-Subperiod Consistency

| Subperiod | Earnings Enhanced | Earnings-Only | Anti-Earnings |
|---|---|---|---|
| 2012–2017 | FAIL (t=1.49) | PASS (t=3.25) | FAIL (t=2.58) |
| 2016–2020 | FAIL (t=1.11) | FAIL (t=1.36) | FAIL (t=0.35) |
| 2020–2025 | FAIL (t=1.04) | FAIL (t=1.65) | FAIL (t=0.88) |

Earnings-Only passes in subperiod 1 only; fails in 2 and 3. Not a consistent signal.

### Comparison with K570

| Metric | K570 (lookahead) | K570b (corrected) | Change |
|---|---|---|---|
| Baseline Sharpe | 1.4251 | 0.3801 | −73.3% |
| NULL result | Yes | Yes | Maintained |

---

## Conclusion

**NULL RESULT — confirmed after all four fixes.**

After correcting the lookahead bias, the baseline VT Sharpe collapses from 1.43 to 0.38 — confirming the original result was almost entirely driven by lookahead. Despite this, the *relative* conclusion is unchanged: none of the earnings-season adjustments beat 12/VIX at the Harvey (2016) t > 3.0 threshold. The NULL result from K570 is robust to methodology corrections.

VIX remains the sufficient statistic. Earnings-season timing adds no incremental value to VT.

**Implication for K570 feed article**: The published article's qualitative conclusion ("earnings season does not justify VT adjustment") stands. However, the Sharpe numbers cited (baseline 1.43, etc.) are lookahead-inflated and should carry a disclaimer. A correction note should be added to the article.

---

## Files

| File | Description |
|---|---|
| `k570b.py` | Corrected script with all four fixes applied |
| `k570b_results.json` | Full results with `comparison_with_k570` block |
| `README.md` | This file |

---

## References

- Moreira & Muir (2017, JoF): Volatility-managed portfolios
- Harvey (2016, JoF): t > 3 threshold for new factors
- K570: Original experiment (lookahead bias present)
- K498, K412, K80, N153: Prior null results at index level
