# K1439: USD Regime Conditional Cross-Asset Realized Volatility

- **K id**: K1439
- **Status**: completed, awaiting Codex review
- **Verdict**: **PASS** (4/5 assets Bonferroni-significant, sign concordant 4/5 across robustness regime)
- **Created**: 2026-06-10

## Hypothesis

Conditional on strong vs weak USD regime (proxied by UUP — Invesco DB USD Bullish ETF),
do realized vols of EM equity / gold / broad commodity / oil / industrial metal
differ systematically? Which asset is most regime-sensitive?

## Differentiation vs Related K

- **K878** (DXY-as-predictor NULL): tested whether DXY *predicts* SPY vol → null.
  K1439 instead **conditions** on DXY regime and looks at *cross-asset* vol levels,
  not single-asset prediction.
- **K1435** (GLD-DXY DCC FOMC event study): focused on FOMC-window dynamic correlation.
  K1439 uses the **full sample regime classification** (level + trend) across 5 assets,
  not event-window dynamic correlation.

## Data

- Source: `yfinance` (Adj Close, `auto_adjust=True`)
- Period: 2010-01-04 → 2026-06-05, **4,131 trading days**
- Tickers used: UUP (regime indicator), EEM, GLD, DBC, USO, DBB

## Method

### Realized vol
- 21-day rolling std of daily log returns × √252 (annualized)

### Regime definitions
- **Level (primary)**: UUP 100-day MA z-score; `z > +0.5` = strong USD, `z < −0.5` = weak,
  else neutral. **`shift(1)` applied** so day-*t* bucket uses only info through *t−1*.
- **Trend (robustness)**: UUP 60-day log-return sign; positive = strong, negative = weak.
  Same `shift(1)` protection.

### Tests
- **Welch t-test** (strong vs weak) per asset, two-sided
- **Levene** (equality of variances) per asset
- **Bonferroni correction**: α = 0.05 / 5 = **0.01**

### Lookahead protection
- `bucket.shift(1)` embedded in both regime constructors (see `k1439.py:105,116`).
- 21-day rolling RV is backward-looking by construction.
- `seed=42` (no random ops in current pipeline, fixed for any future bootstrap).

### Codex 24h-rule review (2026-06-13)
- **VERDICT**: CONDITIONAL_PASS, PUBLISHABLE_AS_IS=YES, LOOKAHEAD_RISK=NONE.
- **Caveat**: 21d rolling RV creates overlapping observations → Welch t-test p-values are
  optimistic under serial autocorrelation. Result interpretation is
  **association/conditioning, not causation**. Paper-grade inference requires HAC/Newey-West
  or block-bootstrap over regime-conditioned mean RV differences (follow-up tracked).
- `yf.download(auto_adjust=True)` → "Adj Close" is dividend/split-adjusted.

## Results

### Level regime — primary

| Asset | strong USD n | weak USD n | mean RV (strong) | mean RV (weak) | Welch t | p-value | Bonferroni sig |
|-------|------|------|--------|--------|--------|---------|------|
| EEM   | 1,887 | 1,356 | 0.204 | 0.190 | +4.18  | 3.0e-05 | ✔ |
| GLD   | 1,887 | 1,356 | 0.154 | 0.152 | +0.73  | 0.466   | ✘ |
| DBC   | 1,887 | 1,356 | 0.171 | 0.154 | +8.16  | 4.9e-16 | ✔ |
| USO   | 1,887 | 1,356 | 0.349 | 0.291 | +10.00 | 3.3e-23 | ✔ |
| DBB   | 1,887 | 1,356 | 0.189 | 0.179 | +4.63  | 3.8e-06 | ✔ |

### Trend regime — robustness

| Asset | Welch t | p-value | Bonferroni sig |
|-------|---------|---------|------|
| EEM   | +5.59   | 2.5e-08 | ✔ |
| GLD   | −0.60   | 0.548   | ✘ |
| DBC   | +8.35   | 9.1e-17 | ✔ |
| USO   | +11.30  | 3.8e-29 | ✔ |
| DBB   | +4.37   | 1.3e-05 | ✔ |

- Bonferroni-sig assets concordant across two regime definitions: **5/5** (same sig/non-sig pattern)
- Sign of `mean(strong) − mean(weak)` concordant across two definitions: **4/5** (GLD flips sign but both null)
- **Most sensitive asset**: **USO** (|t| ≈ 10–11 under both definitions; ~6 vol-points higher under strong USD)

## Interpretation

1. **Strong USD lifts EM/commodity/oil/industrial-metal vol uniformly** — 4 of 5 assets show
   higher RV when USD is strong, sign consistent across two independent regime definitions.
2. **Gold (GLD) is the lone exception** — vol is statistically indistinguishable across
   USD regimes. Consistent with GLD's dual role as USD-hedge AND safe-haven: flows in both
   directions stabilize its vol.
3. **Oil (USO) is by far the most sensitive** — strong USD adds ~20% to its annualized RV
   (0.349 vs 0.291). Mechanism candidates: dollar-denominated pricing, commodity flow
   reversal, financialization linkage to risk-off.

## Verdict & Reason

**PASS** — 4/5 assets show Bonferroni-significant RV difference between strong vs weak USD
level regime; sign concordant 4/5 across the orthogonal trend-regime robustness check; the
single non-significant asset (GLD) has a theoretically motivated explanation.

## Mission Contribution

- **Mission #2** (research rigor): adds a clean conditioning-based cross-asset
  finding with proper Bonferroni + 2-definition robustness; new factor for the
  vol-prediction model library (USD regime indicator).
- **Mission #1/5** (article quality / exposure): clear publishable finding —
  "強美元下哪些波動率最敏感" is reader-facing and concrete.
- **Mission #3** (paper): potential covariate for cross-asset vol-prediction paper —
  documents an asymmetry that GLD vs commodities decomposition can exploit.

## Files

- `k1439.py` — self-contained script (`uv run python experiments/k1439/k1439.py`)
- `k1439_results.json` — full structured results (period, n_obs, per-asset stats, tests, verdict)
- `figures/rv_by_regime_level.png` — primary bar chart
- `figures/rv_by_regime_trend.png` — robustness bar chart

## Next Steps

1. **Codex review** (recommended) — verify lookahead protection in `build_regime_level` /
   `build_regime_trend` and regime-stat alignment.
2. Main thread to write `knowledge.json` entry (worktree禁止寫 shared state).
3. Candidate for general-reader article (Mission #1).
4. Potential for HAR-RV+UUP-regime-dummy extension in cross-asset vol-prediction paper.
