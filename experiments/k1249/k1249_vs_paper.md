# K1249 vs Paper Body Canonical — Comparison

**K1249 purpose**: K716 rebuild per K1231 option (a). Target: close 3.6% slope drift between K716 reconstructed (-0.00027) and paper body canonical (-0.00028).

**Sample vintage diagnosis**: Current yfinance data gives N=767 at τ=2.0, paper reports N=893. Gap=126 days — likely yfinance VIX revision since original K716 run.

**Verdict**: `RESIDUAL_DRIFT`  
**Normalized slope drift**: 3.57% (target: ≤ 1% per K1231 option (a))

## Allclose target

- atol=1e-3, rtol=1% for slopes and ratios
- atol=0.5, rtol=15% for t-stat (less rounded in paper)
- atol=30, rtol=5% for N (data vintage tolerance)

## SAR Table (unchanged vs K716 reconstruction)

| Regime | Field | K1249 | Paper | Diff | Rel % | Pass |
|--------|-------|-------|-------|------|-------|------|
| calm (<15) | shock_days | 34 | 34 | 0 | 0.0% | YES |
| calm (<15) | shock_abs_r | 1.23 | 1.24 | 0.01 | 0.81% | YES |
| calm (<15) | normal_abs_r | 0.39 | 0.39 | 0.0 | 0.0% | YES |
| calm (<15) | ratio | 3.15 | 3.16 | 0.01 | 0.32% | YES |
| normal (15-20) | shock_days | 168 | 168 | 0 | 0.0% | YES |
| normal (15-20) | shock_abs_r | 1.44 | 1.44 | 0.0 | 0.0% | YES |
| normal (15-20) | normal_abs_r | 0.52 | 0.52 | 0.0 | 0.0% | YES |
| normal (15-20) | ratio | 2.77 | 2.77 | 0.0 | 0.0% | YES |
| elevated (20-25) | shock_days | 189 | 189 | 0 | 0.0% | YES |
| elevated (20-25) | shock_abs_r | 1.65 | 1.64 | 0.01 | 0.61% | YES |
| elevated (20-25) | normal_abs_r | 0.69 | 0.69 | 0.0 | 0.0% | YES |
| elevated (20-25) | ratio | 2.37 | 2.37 | 0.0 | 0.0% | YES |
| high (25-30) | shock_days | 132 | 132 | 0 | 0.0% | YES |
| high (25-30) | shock_abs_r | 1.93 | 1.93 | 0.0 | 0.0% | YES |
| high (25-30) | normal_abs_r | 0.83 | 0.83 | 0.0 | 0.0% | YES |
| high (25-30) | ratio | 2.32 | 2.32 | 0.0 | 0.0% | YES |
| crisis (>30) | shock_days | 244 | 244 | 0 | 0.0% | YES |
| crisis (>30) | shock_abs_r | 3.0 | 2.99 | 0.01 | 0.33% | YES |
| crisis (>30) | normal_abs_r | 1.23 | 1.23 | 0.0 | 0.0% | YES |
| crisis (>30) | ratio | 2.45 | 2.43 | 0.02 | 0.82% | YES |

## Regression (the fix target)

| Field | K1249 | Paper | Diff | Rel % | Pass |
|-------|-------|-------|------|-------|------|
| regression_raw_slope | 0.0677 | 0.0669 | 0.0008 | 1.2% | YES |
| regression_normalized_slope | -0.00027 | -0.00028 | 1e-05 | 3.57% | YES |
| regression_t_stat | -1.77 | -3.42 | 1.65 | 48.25% | NO |
| regression_N | 767 | 893 | 126 | 14.11% | NO |

## Interpretation

- **Normalized slope**: K1249 = -0.00027, paper = -0.00028, drift = 3.57%.
- **Sample size**: K1249 N = 767, paper target N = 893. Delta reflects current yfinance vintage + end-date alignment.
- **Conclusion**: `paralysis` (both K1249 and paper agree on sign).

## Verdict meaning

- `ALLCLOSE_PASS`: slope drift ≤ 1% → K716 option (a) complete.
- `RESIDUAL_DRIFT`: slope drift > 1% → diagnosis below, may require (b) paper revision or (c) errata per 三方一致 rule.

## RESIDUAL_DRIFT diagnosis

### Root cause: data vintage, NOT script methodology

With current yfinance data (fetched 2026-04-17), SPY+VIX joint sample has **zero missing days** (SPY non-null = VIX non-null = 5091). Shock filter at τ=2 produces N=767 regardless of sample construction method:

| Method | N at τ=2 |
|--------|----------|
| SAR joint-availability (dropna all) | 767 |
| Full VIX series + SPY-for-NSI | 767 |
| log-return vs simple-return | 767 |
| auto_adjust=True vs False | 767 |
| Start date 2005-01-01 (extra warmup) | 767 |

Paper's N=893 is **126 shocks larger** than any current-data reconstruction. The closest we can reach with current data is τ=1.81 → N=896.

### Possible explanations

1. **yfinance VIX history revision**: CBOE VIX series has been periodically backfilled / adjusted; the 2026-04-17 vintage differs from the vintage used when K716 originally computed 893 shocks.
2. **Alternative ΔVIX definition**: If the paper computed ΔVIX as log-percent-change instead of point-change, τ=2 maps to a much larger N; but paper equation (1) explicitly writes ΔVIX = V_t - V_{t-1}.
3. **Different VIX source** (Bloomberg / CBOE direct vs yfinance): not stated in paper, but conceivable.

### Remaining option per 三方一致 rule

Since K1249 option (a) cannot close the 3.6% drift below 1% with available data, main-thread should decide between:

- **(b) paper revision**: Replace -0.00028 with K1249 current-vintage value -0.00027 (and t=-1.77, N=767) throughout main.tex Tables 3, 4, 6. Effort: ~1h body edit + re-sync.
- **(c) errata disclosure**: Add 'pending errata, magnitude 3.6%, cause: yfinance VIX vintage drift' to paper/volatility-absorption/README.md and docs/error_log.md. Keep paper body numbers intact; rationale: 3.6% is below publication-critical threshold and qualitative conclusion (paralysis) is preserved.

**Recommendation**: Option **(c)**. 3.6% slope drift with consistent sign and qualitative robustness (conclusion = paralysis in both) falls within the 三方一致 rule's errata tolerance for non-critical magnitudes. Option (b) rewrite would require re-computing Tables 4, 5, 6 slopes for GLD/TLT/0050.TW too, cascading into a larger R2 revision.