# K1121: Alt-data for Portfolio Construction (NOT Forecasting)

**Status**: Complete | **Period**: 2019-01-15 to 2026-04-10 (1,817 days, SPY+GLD daily) | **Date**: 2026-04-13

## Motivation (paradigm pivot)

K1116 / K1118 (9 experiments total) confirmed **alt-data is NULL for forecasting weekly RV**
(native VIX / GVZ / MOVE already sufficient; EPU, NFCI, STLFSI add nothing, often hurt).

This experiment asks a different question:
> Can alt-data add value in *allocation* (regime-based portfolio weights)
> even if it cannot forecast next-period vol?

Hypothesis: VIX captures **implied vol**, but EPU / NFCI may capture **regime shifts**
that affect optimal equity/safe-asset mix even when they do not predict tomorrow's realized vol.

## Design

**Universe**: SPY + GLD (CLAUDE.md 50/50 moat baseline; K2-K89 verified).
**Assets & signals**: yfinance SPY, GLD, ^VIX (daily); FRED USEPUINDXD (daily), NFCI (weekly).
**Rebalance**: daily, with all signals lagged.

### 6 Strategies

| # | Strategy       | Rule                                                | Signal source |
|---|---------------|-----------------------------------------------------|---------------|
| S1 | Static 50/50 | wSPY = 0.5 always                                   | (baseline)    |
| S2 | Vol-targeted | wSPY = clip(0.15 / sigma_SPY_20d_ann, 0.2, 1.0)     | log-r SPY     |
| S3 | VIX-regime   | wSPY = 0.7 if VIX < 20 else 0.3                     | CBOE VIX      |
| S4 | EPU-regime   | wSPY = 0.7 if EPU_252d_pct_rank < 0.7 else 0.3      | FRED USEPUINDXD |
| S5 | NFCI-regime  | wSPY = 0.7 if NFCI_252d_pct_rank < 0.7 else 0.3     | FRED NFCI     |
| S6 | Hybrid       | Average of S3, S4, S5 signals (each lagged)         | combined      |

### No-lookahead lags (release-timing corrected)

- S2: `sigma.shift(1)`  (1-day lag on past 20d window)
- S3: `VIX.shift(1)` (VIX is intraday, 1-day is sufficient)
- S4: `epu_signal.shift(2)` (USEPUINDXD obs date X published day X+1)
- S5: `nfci_signal.shift(5)` (NFCI obs Friday published following Wednesday)
- Warm-up: 252-day rolling rank + 5-day release lag → backtest starts 2019-01-15

### Evaluation

- **Metrics**: Sharpe, Sortino, Max Drawdown, Calmar, annualized return / vol
- **IS / OOS split**: IS = 2019-2022 (1,001 days), OOS = 2023-2026 (816 days)
- **Stationary bootstrap** (Politis-Romano 1994): 1000 reps, block_mean=20, seed=42;
  tests Sharpe-difference vs S1 and vs S2
- **OOS rolling Sharpe**: 252d window
- **Stress episodes**: COVID 2020/02-04, Rate-shock 2022, SVB 2023/03

## Results

### Headline table

| Strategy | Sharpe (full) | Sharpe (OOS) | MDD | Calmar | Sortino | avg wSPY |
|----------|--------------:|-------------:|----:|-------:|--------:|---------:|
| **S1 50/50**  | **1.309** | 1.975 | -0.203 | 0.888 | 1.88 | 0.500 |
| S2 Vol-target | 1.072 | 1.474 | -0.220 | 0.720 | 1.53 | 0.880 |
| S3 VIX-regime | 1.210 | 1.748 | -0.179 | 0.883 | 1.76 | 0.543 |
| S4 EPU-regime | 1.283 | 1.856 | -0.232 | 0.752 | 1.87 | 0.566 |
| **S5 NFCI-regime** | **1.312** | 1.656 | **-0.179** | **0.950** | 1.90 | 0.594 |
| S6 Hybrid     | 1.305 | 1.806 | -0.184 | 0.911 | 1.91 | 0.568 |

### Bootstrap Sharpe-difference vs S1 (50/50)

| Pair | Obs diff | p-value | 95% CI | Verdict |
|------|---------:|--------:|-------:|---------|
| S2 vs S1 | -0.238 | 0.264 | [-0.67, +0.17] | NS (loss) |
| S3 vs S1 | -0.099 | 0.388 | [-0.34, +0.13] | NS |
| S4 vs S1 | -0.026 | 0.860 | [-0.31, +0.26] | NS |
| S5 vs S1 | +0.003 | 0.966 | [-0.23, +0.25] | NS (tie) |
| S6 vs S1 | -0.005 | 0.948 | [-0.19, +0.17] | NS (tie) |

### Bootstrap vs S2 (vol-targeted)

| Pair | Obs diff | p-value | Verdict |
|------|---------:|--------:|---------|
| S4 vs S2 | +0.212 | 0.280 | NS |
| S5 vs S2 | +0.241 | 0.166 | NS (best, still NS) |
| S6 vs S2 | +0.233 | 0.194 | NS |

### Hypothesis results

| # | Hypothesis | Result |
|---|-----------|--------|
| H1 | S4 or S5 Sharpe > S2 (with significance) | **FAIL** — diffs NS (p > 0.16) |
| H2 | Alt-data Sharpe ≥ S1 (50/50) | **PASS** (S5 = S1 + 0.003, effectively tied) |
| H3 | Alt-data reduces SPY in stress | **PARTIAL** — NFCI (S5) reduced wSPY in all 3 stress windows; EPU (S4) only reduced in COVID, not in 2022 |
| H4 | S6 Hybrid > max(S3,S4,S5) single | **FAIL** — S6 (1.305) < S5 (1.312) |

### Stress-episode wSPY

| Episode | Period | S1 | S3 (VIX) | S4 (EPU) | S5 (NFCI) | S6 (Hybrid) |
|---------|--------|---:|---:|---:|---:|---:|
| COVID-2020 | 2020-02-15 to 2020-04-30 | 0.50 | 0.34 | 0.36 | 0.30 | 0.33 |
| Rate-shock-2022 | 2022-01-01 to 2022-10-31 | 0.50 | 0.34 | 0.56 | 0.30 | 0.40 |
| SVB-2023 | 2023-03-01 to 2023-04-15 | 0.50 | 0.51 | 0.51 | 0.46 | 0.50 |

- NFCI (S5) reliably signals "reduce equity" in every stress period (wSPY → 0.30)
- EPU (S4) **increased** wSPY during 2022 rate shock (EPU was not elevated; stress was rate-driven, not uncertainty-driven) — illustrates that EPU is topic-specific, not general stress signal
- VIX (S3) responded to COVID/2022 but not SVB (vol was muted in March 2023)

## Interpretation

### Core finding: alt-data fails a second paradigm

After K1116/K1118 proved alt-data is NULL for *forecasting*, this experiment tests *allocation*
and finds:

1. **No alt-data strategy significantly beats 50/50 baseline** (all p > 0.26 on Sharpe difference)
2. The best alt-data strategy (S5 NFCI) edges S1 by Sharpe +0.003 — economically nil
3. All "wins" disappear when release-timing lookahead is corrected
   (Codex review found HIGH-severity bias: original `shift(1)` was not enough for weekly NFCI)
4. **50/50 SPY/GLD moat (CLAUDE.md) holds** — 8 replication studies + K1121 = 9 rejections of "beat 50/50" claims

### NFCI's one useful property

S5 (NFCI) has the **lowest MDD (-17.9%, tied with S3)** and highest Calmar (0.950 vs S1 0.888).
In stress periods NFCI reliably downshifts wSPY to 0.30 (versus S1 always 0.50).
This is **risk reduction, not alpha** — consistent with CLAUDE.md finding:
> "VT = drawdown insurance, not alpha generator" (K687/K697)

NFCI's -17.9% MDD and 0.950 Calmar suggest a marginal case for risk-averse investors,
but the Sharpe tie with S1 (p=0.966) means you buy MDD reduction with zero return per unit vol.

### Economic significance

- Best alt-data strategy (S5): Sharpe +0.003 over baseline = about 0.04 pct/year extra
  return per unit of risk — well below any reasonable transaction-cost floor
- At 5 bps / rebalance × ~50 weight-change days per year → ~0.25% cost drag
- **Net: alt-data allocation underperforms 50/50 after realistic costs**

## Robustness notes / limitations

1. **Single asset pair (SPY+GLD)**: not tested on broader universe (TLT, bonds, international)
2. **Threshold sensitivity**: tested at 70th percentile only. Could vary; however given
   bootstrap p-values >0.25 across all pairs, it is unlikely threshold tuning alone
   recovers significance without data-mining
3. **Only two alt-data sources (EPU, NFCI)**. STLFSI, ANFCI, WLEMU also tested NULL in K1116/K1118 forecasting
4. **Stress sample small**: COVID (52 days), Rate-2022 (209 days), SVB (32 days) — 
   bootstrap cannot formally test on these windows
5. **OOS (2023-2026) was a bull market**: all strategies had high Sharpe; differentiation is limited
6. **No transaction costs** in the backtest: would further erode alt-data edge

## Paper 4 implication

**Adds a new "compendium chapter" to alt-data NULL corpus:**
- Before K1121: alt-data null for *forecasting* (K1116/K1118, 9 experiments)
- After K1121: alt-data also null for *allocation* under regime-based rules

Paper 4 compendium does not strengthen — it expands the territory covered by the null result.
"Alt-data cannot predict vol AND cannot improve SPY/GLD allocation."

## Derivative research directions (written back to research_program.md)

1. **Continuous weights** (not regime dummies): does soft EPU/NFCI loading
   (continuous function of z-score) improve over the 70th-percentile step function?
   Hypothesis: probably not (underlying info already in VIX) but worth 1 confirmatory experiment.

2. **Cross-asset alt-data allocation**: test EPU/NFCI on 3-asset (SPY+GLD+TLT) allocation
   under 60/40/20 style benchmarks. K1118 showed alt-data forecasting null cross-asset;
   allocation cross-asset is still open.

3. **Event-driven alt-data**: rather than rolling-percentile regime classification,
   use absolute-threshold "crisis flag" (e.g., NFCI > 0.5 for N consecutive days)
   to trigger *de-risking* only. Could avoid the "whipsaw" of frequent threshold crossings.

## Files

- `k1121.py` — experiment script (fixed lookahead, simple returns, retry-cached FRED fetch)
- `k1121_results.json` — all metrics, hypothesis tests, bootstrap outputs
- `k1121_plots.py` — plot generator
- `k1121_sharpe_comparison.png` — 6-strategy Sharpe bar (full / IS / OOS)
- `k1121_risk_metrics.png` — MDD + Calmar by strategy
- `k1121_equity_curves.png` — 2019-2026 cumulative wealth
- `k1121_bootstrap_vs_5050.png` — 95% CI for Sharpe difference vs S1
- `k1121_stress_weights.png` — avg wSPY by strategy × 3 stress episodes
- `data/panel.parquet` — merged daily panel (SPY, GLD, VIX, EPU, NFCI)
- `data/signals.parquet` — computed wSPY signals per strategy
- `data/backtest.parquet` — daily returns + weights for all 6 strategies
- `data/fred_USEPUINDXD.csv`, `data/fred_NFCI.csv` — cached FRED data
- `run.log` — runtime log

## References

- Baker, Bloom, Davis (2016) *QJE* — EPU index construction
- Brave, Butters (2011) — NFCI construction (Chicago Fed)
- Politis & Romano (1994) — Stationary bootstrap
- Opdyke (2007) — Sharpe ratio inference and comparison
- Harvey, Liu, Zhu (2016) — Harvey t > 3 threshold for Sharpe-based claims

## Code review trail

2026-04-13 Codex review (`codex exec -s read-only`):
- **HIGH**: Release-timing lookahead (USEPUINDXD observation date is published next day;
  NFCI weekly observation Friday published following Wednesday) — FIXED with shift(2) / shift(5)
- **MEDIUM**: Log returns used for portfolio-weight arithmetic; replaced with simple returns
  for exactness in daily rebalance (consistent with K2-K89 paper trading convention)
- After fixes: S4 edge over S1 eliminated (-0.026, p=0.86), confirming the original
  edge was release-timing artifact. S5 NFCI retains a nominal tie (diff=+0.003, p=0.966).

Seed: 42 (np.random.seed + rng.default_rng + bootstrap seed)
