# K1439: USD Regime Conditional Cross-Asset Realized Volatility

- **K id**: K1439
- **Status**: completed, Codex follow-up integrated
- **Verdict**: **CONDITIONAL_PASS** (naive Welch = 4/5 significant, but HAC/Newey-West + Bonferroni leaves only USO robustly significant)
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
- **Primary inference**: OLS-HAC / Newey-West (`maxlags=21`) on strong-minus-weak mean RV
- **Welch t-test** (strong vs weak) per asset, two-sided, **descriptive only**
- **Levene** (equality of variances) per asset, descriptive variance check
- **Bonferroni correction**: α = 0.05 / 5 = **0.01**

### Lookahead protection
- `bucket.shift(1)` embedded in both regime constructors (see `k1439.py:105,116`).
- 21-day rolling RV is backward-looking by construction.
- `seed=42` (no random ops in current pipeline, fixed for any future bootstrap).

### Codex follow-up (2026-06-13)
- **VERDICT**: follow-up completed, LOOKAHEAD_RISK=NONE.
- `reproduce.py` added; `uv run python experiments/k1439/reproduce.py` now regenerates
  the outputs and checks the saved verdict.
- 21d rolling RV has extreme overlap autocorrelation, so **HAC/Newey-West is now the
  canonical inference path** and Welch is downgraded to descriptive output only.
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

### Level regime — robust HAC inference (canonical)

| Asset | strong-weak RV diff | HAC t | HAC p | Bonferroni sig |
|-------|--------|--------|---------|------|
| EEM   | +0.0132 | +1.10 | 0.269 | ✘ |
| GLD   | +0.0016 | +0.20 | 0.839 | ✘ |
| DBC   | +0.0179 | +2.13 | 0.033 | ✘ |
| USO   | +0.0588 | +2.61 | 0.0091 | ✔ |
| DBB   | +0.0097 | +1.23 | 0.220 | ✘ |

### Trend regime — robustness

| Asset | Welch t | p-value | Bonferroni sig |
|-------|---------|---------|------|
| EEM   | +5.59   | 2.5e-08 | ✔ |
| GLD   | −0.60   | 0.548   | ✘ |
| DBC   | +8.35   | 9.1e-17 | ✔ |
| USO   | +11.30  | 3.8e-29 | ✔ |
| DBB   | +4.37   | 1.3e-05 | ✔ |

### Trend regime — HAC robustness

| Asset | strong-weak RV diff | HAC t | HAC p | Bonferroni sig |
|-------|--------|--------|---------|------|
| EEM   | +0.0151 | +1.49 | 0.136 | ✘ |
| GLD   | -0.0013 | -0.16 | 0.870 | ✘ |
| DBC   | +0.0160 | +2.20 | 0.027 | ✘ |
| USO   | +0.0569 | +2.90 | 0.0038 | ✔ |
| DBB   | +0.0083 | +1.14 | 0.253 | ✘ |

- HAC Bonferroni-sig assets concordant across two regime definitions: **5/5** (only USO survives in both)
- Sign of `mean(strong) − mean(weak)` concordant across two definitions: **4/5** (GLD flips sign but both null)
- **Most sensitive asset**: **USO** (~5.7-5.9 vol-points higher under strong USD; HAC t ≈ 2.6-2.9)

### Overlap diagnostics

21d rolling RV is highly persistent for every asset, which is why the Welch p-values were too optimistic:

| Asset | ACF(1) | ACF(5) | ACF(21) |
|-------|--------|--------|---------|
| EEM | 0.989 | 0.917 | 0.470 |
| GLD | 0.984 | 0.904 | 0.469 |
| DBC | 0.984 | 0.899 | 0.428 |
| USO | 0.990 | 0.935 | 0.592 |
| DBB | 0.984 | 0.909 | 0.501 |

## Interpretation

1. **Naive broad signal shrinks materially after robust inference** — the 4/5 Welch result is
   mostly an overlap-autocorrelation artifact once HAC is applied.
2. **Oil (USO) remains genuinely regime-sensitive** — it is the only asset that survives
   HAC + Bonferroni under both level and trend definitions.
3. **Gold (GLD) remains null** — both descriptive and HAC inference support the safe-haven
   offset story.
4. **DBC/DBB/EEM are directionally positive but not paper-grade significant** — these can be
   discussed as suggestive conditioning evidence, not strong cross-asset facts.

## Verdict & Reason

**CONDITIONAL_PASS** — after correcting for overlap with HAC/Newey-West, only USO remains
Bonferroni-significant under both regime definitions. The broader 4/5 pattern still points in
the same direction, but the paper-grade claim must be narrowed from "uniform cross-asset effect"
to "oil stands out; other commodities/EM are suggestive only."

## Mission Contribution

- **Mission #2** (research rigor): adds a clean conditioning-based cross-asset
  finding, but now with overlap-aware HAC inference; new factor for the
  vol-prediction model library (USD regime indicator), with honest downscoping.
- **Mission #1/5** (article quality / exposure): clear publishable finding —
  "強美元下哪些波動率最敏感" is reader-facing and concrete.
- **Mission #3** (paper): potential covariate for cross-asset vol-prediction paper —
  documents an asymmetry that GLD vs commodities decomposition can exploit.

## Files

- `k1439.py` — self-contained script (`uv run python experiments/k1439/k1439.py`)
- `reproduce.py` — rerun + verify saved verdict (`uv run python experiments/k1439/reproduce.py`)
- `k1439_results.json` — full structured results (period, n_obs, per-asset stats, tests, verdict)
- `figures/rv_by_regime_level.png` — primary bar chart
- `figures/rv_by_regime_trend.png` — robustness bar chart

## Next Steps

1. Main thread to update `knowledge.json` with the **downscoped** conclusion: only USO is
   robust after HAC; broad commodity/EM effect is suggestive only.
2. Any article or paper text must cite **HAC** as the canonical test and avoid causal wording.
3. If stronger inference is needed later, add moving-block bootstrap as a second robustness layer.
