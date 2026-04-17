# K1123: Cross-asset Alt-data Allocation (SPY + GLD + TLT)

**Status**: Complete | **Period**: 2019-01-14 -> 2026-04-13 (1,819 days) | **Date**: 2026-04-17

## Motivation

K1121 tested alt-data (NFCI / EPU) **regime signals** on a 2-asset SPY+GLD
portfolio and found S5 NFCI (best) tied the 50/50 baseline (Sharpe +0.003, p=0.966).
K1121 robustness note #1 explicitly flagged the limitation:
> "Single asset pair (SPY+GLD): not tested on broader universe (TLT, bonds, international)."

K1123 extends to 3 assets by adding **TLT (US long bond)** as a second safe-asset
leg. Hypothesis: stress-regime tilts can now rotate into bonds *and* gold, giving
alt-data a richer defensive playbook than 2-asset could provide. If this still
fails, it would fortify the "alt-data is null for allocation" conclusion.

## Design

**Universe**: SPY (equity) + GLD (gold) + TLT (US long bond)
**Data**: yfinance daily close (auto-adjust) + FRED cached (from K1121/K1122):
USEPUINDXD (daily), NFCI (weekly).
**Rebalance**: daily, all signals lagged per error_log 2026-04-13 publication delay.
**Transaction cost**: 5 bps per unit of turnover (`sum|dw|`) applied to day-t return.

### 7 strategies

| # | Strategy | Rule |
|---|----------|------|
| B0 | Static 50/50 SPY/GLD | K1121/K846 moat baseline (TLT=0) |
| B1 | Static 40/30/30 | equal-ish with TLT leg |
| B2 | Rolling Risk-Parity | inverse-vol (60d log-return stdev), shift(1) |
| S1 | NFCI-regime | stress = NFCI_252d_rank >= 0.80: normal 40/30/30 -> stress 20/40/40 |
| S2 | EPU-regime | stress = EPU_252d_rank >= 0.80: normal 40/30/30 -> stress 20/50/30 (uncertainty -> gold) |
| S3 | Combined OR | stress = (NFCI_rank >= 0.80) OR (EPU_rank >= 0.80): normal 40/30/30 -> stress 20/45/35 |
| S4 | Smooth tilt | z_stress = 0.5*z(NFCI, shift5) + 0.5*z(EPU, shift2); wSPY = clip(0.40 - 0.10*z, 0.15, 0.60); GLD/TLT split by z tilt |

### No-lookahead lags (publication-aware)

- **NFCI**: `shift(5)` trading days - weekly observation Fri published following Wed
- **EPU (USEPUINDXD)**: `shift(2)` trading days - daily obs X published X+1
- **Vol estimators (B2)**: `shift(1)`
- Weight at day t uses signal from day <=t-1

### Evaluation

- Sharpe / Sortino / MDD / Calmar / CAGR (full, IS 2019-2022, OOS 2023-2026)
- Stationary bootstrap (Politis-Romano 1994): n_boot=1000, block_mean=20, seed=42
  - Tested each alt-data strategy vs each baseline (full sample + OOS-only)
- Regime-conditional Sharpe: stress days (N=666) vs calm days (N=1,153)
- Harvey-like Sharpe t>2 threshold for stress+total (H4)
- Seed: np.random.seed(42) + rng.default_rng(42) + bootstrap seed=42

## Results

### Headline table (net of 5 bps TX)

| Strategy | Sharpe full | Sharpe IS | Sharpe OOS | MDD | CAGR | Calmar | avg wSPY | avg wTLT | TO/yr | TX drag |
|----------|------------:|----------:|-----------:|----:|-----:|-------:|---------:|---------:|------:|--------:|
| **B0 50/50 SPY/GLD** | **1.310** | 0.818 | **1.980** | -0.203 | **18.6%** | **0.887** | 0.500 | 0.000 | 0.00 | 0.00% |
| B1 40/30/30 | 1.128 | 0.718 | 1.669 | -0.226 | 12.6% | 0.551 | 0.400 | 0.300 | 0.00 | 0.00% |
| B2 Rolling RP | 1.094 | 0.665 | 1.671 | -0.219 | 11.3% | 0.514 | 0.321 | 0.342 | 2.76 | 0.14% |
| S1 NFCI | 1.161 | 0.781 | 1.630 | -0.230 | 12.5% | 0.538 | 0.359 | 0.320 | 1.16 | 0.06% |
| S2 EPU | 1.014 | 0.631 | 1.496 | -0.246 | 11.0% | 0.451 | 0.353 | 0.300 | 21.78 | 1.09% |
| S3 Combined | 1.074 | 0.738 | 1.486 | -0.218 | 11.5% | 0.526 | 0.327 | 0.318 | 17.29 | 0.86% |
| S4 Smooth tilt | 1.082 | 0.745 | 1.524 | -0.231 | 11.7% | 0.504 | 0.405 | 0.289 | 23.81 | 1.19% |

### Stationary bootstrap (full sample) - alt-data vs baselines

| | vs B0 | vs B1 | vs B2 |
|---|---|---|---|
| **S1** (NFCI) | diff=-0.149 p=0.492 t=-0.70 | diff=+0.033 p=0.682 t=+0.38 | diff=+0.067 p=0.392 t=+0.86 |
| **S2** (EPU) | diff=-0.295 p=0.134 t=-1.42 | diff=-0.113 p=0.274 t=-1.10 | diff=-0.079 p=0.334 t=-0.91 |
| **S3** (comb) | diff=-0.236 p=0.296 t=-1.06 | diff=-0.054 p=0.664 t=-0.46 | diff=-0.020 p=0.804 t=-0.24 |
| **S4** (smooth) | diff=-0.228 p=0.232 t=-1.19 | diff=-0.046 p=0.600 t=-0.54 | diff=-0.012 p=0.896 t=-0.14 |

### OOS bootstrap (2023+)

| | vs B0 | vs B1 | vs B2 |
|---|---|---|---|
| S1 | diff=-0.350 p=0.102 | diff=-0.039 p=0.186 | diff=-0.041 p=0.720 |
| S2 | diff=-0.484 p=0.076 | diff=-0.173 p=0.328 | diff=-0.175 p=0.300 |
| S3 | diff=-0.495 p=0.066 | diff=-0.183 p=0.266 | diff=-0.186 p=0.234 |
| S4 | diff=-0.456 p=0.082 | diff=-0.144 p=0.260 | diff=-0.147 p=0.326 |

All diffs < 0 (alt-data loses to B0) or tiny and NS. Harvey t>3 threshold: far exceeded.

### Regime-conditional Sharpe (stress = NFCI_rank>=0.80 OR EPU_rank>=0.80)

| Strategy | Stress (N=666) | Calm (N=1,153) |
|----------|---------------:|---------------:|
| **B0 50/50** | **0.827** | **1.794** |
| B1 40/30/30 | 0.575 | 1.651 |
| B2 Rolling RP | 0.540 | 1.588 |
| S1 NFCI | 0.596 | 1.649 |
| S2 EPU | 0.391 | 1.578 |
| S3 Combined | 0.492 | 1.577 |
| S4 Smooth | 0.590 | 1.543 |

**B0 50/50 is best in both stress and calm regimes.** Alt-data strategies
under-perform B0 *even during stress days* that alt-data was designed to help.
The regime-conditional test also fails: alt-data offers no stress-period alpha.

### Hypothesis tests

| # | Hypothesis | Result |
|---|-----------|--------|
| H1 | Alt-data Sharpe > max(B0, B1, B2) with p<0.05 vs all 3 | **FAIL** (best alt S1=1.161 < B0=1.310; bootstrap 0 candidates) |
| H2 | 3-asset edge > K1121 2-asset edge (+0.003) | **FAIL** (3-asset edge vs B0 = -0.149, below K1121) |
| H3 | S4 smooth > max(S1, S2, S3) step-function | **FAIL** (S4=1.082 < S1=1.161) |
| H4 | Stress t>2 AND total t>2 (Harvey-like) | **FAIL** (no candidate strategy) |

**0/4 hypotheses pass.**

## Verdict: FAIL

Strategy Sharpe (full 2019-04-14 -> 2026-04-13, net 5 bps TX):

| Strategy | Sharpe | MDD | CAGR | DM vs B0 | DM vs B1 | DM vs B2 | 95% CI (vs B2) |
|----------|-------:|-----:|------:|---------:|---------:|---------:|-----------------|
| B0 50/50 | 1.310 | -0.203 | 18.6% | - | - | - | - |
| B1 40/30/30 | 1.128 | -0.226 | 12.6% | - | - | - | - |
| B2 RP | 1.094 | -0.219 | 11.3% | - | - | baseline | - |
| **Best alt S1 NFCI** | 1.161 | -0.230 | 12.5% | t=-0.70 p=0.49 | t=+0.38 p=0.68 | t=+0.86 p=0.39 | [-0.085, +0.221] |
| S2 EPU | 1.014 | -0.246 | 11.0% | t=-1.42 p=0.13 | t=-1.10 p=0.27 | t=-0.91 p=0.33 | [-0.251, +0.093] |
| S3 Combined | 1.074 | -0.218 | 11.5% | t=-1.06 p=0.30 | t=-0.46 p=0.66 | t=-0.24 p=0.80 | [-0.196, +0.140] |
| S4 Smooth | 1.082 | -0.231 | 11.7% | t=-1.19 p=0.23 | t=-0.54 p=0.60 | t=-0.14 p=0.90 | [-0.197, +0.161] |

**Regime conditional**: B0 50/50 beats all alt-data strategies in BOTH stress
(0.827 vs alt max 0.596) AND calm (1.794 vs alt max 1.649). Alt-data gives no
stress-period alpha - the very channel it was supposed to help.

**vs K1121 comparison**: K1121 2-asset best edge +0.003 vs 50/50. K1123 3-asset
best edge -0.149 vs 50/50 (B0 > all alt). Cross-asset extension actively makes
things worse because:

1. TLT had a brutal 2019-2026 (CAGR -0.14%/yr, 15.6% vol). Adding TLT to the
   default weight *structurally* drags returns before alt-data signals even fire.
2. Step-function thresholds (S1, S2, S3) still flip-flop: S2 turnover 21.8x/yr
   (~2 flips/day around percentile boundaries), TX drag 1.09%/yr.
3. Smooth tilt (S4) has even higher turnover (23.8x/yr, 1.19% TX drag) because
   continuous z-score moves every day, costing every day.

**Investor implication**: DO NOT upgrade 50/50 SPY/GLD to a 3-asset alt-data
strategy. TLT's decade-of-pain + alt-data's weak signal combine to give a
worse Sharpe AND worse MDD than the simple moat. K846 50/50 SPY/GLD remains
unchallenged. Cross-asset is not a free lunch - the bond leg's drawdown
(2020-2024) is a veto.

**Research finding**: Alt-data is now null across three paradigms:
- K1116/K1118 (9 experiments): null for *forecasting* realized vol
- K1121 (6 strategies, 2-asset): null for 2-asset *allocation*
- **K1123 (7 strategies, 3-asset, this study): null for cross-asset *allocation***

Paper 4 compendium gains a 10th cross-asset null result. "Alt-data cannot
predict vol, cannot improve 2-asset allocation, and cannot improve 3-asset
allocation" - the null is increasingly robust.

## Robustness notes / limitations

1. **TLT bear market dominates**: TLT 2022 drawdown -42% pushes down all
   3-asset strategies. Finding is period-specific (2019-2026) but unavoidable
   given public data. Different period (e.g., 2010-2020) might show different
   result - left for future work.
2. **Threshold sensitivity**: tested at 80th percentile only (K1121 used 70th).
   Could retune, but bootstrap p-values (0.23-0.49 vs B0) suggest no amount
   of tuning recovers significance without data-mining.
3. **Only 2 alt-data sources**: STLFSI, ANFCI, VVIX not tested here (K1116/
   K1118 already showed null for forecasting).
4. **OOS (2023-2026) was a bull market with VIX suppressed**: only 666 stress
   days out of 1,819 (36.6%). Bootstrap cannot formally test stress-only.
5. **No fractional share constraints, no margin/rebalance threshold**: real
   implementation would have higher TX drag and wider weight tolerance.
6. **Single TX cost tested (5 bps)**: higher costs (10 bps) would further
   destroy S2/S3/S4 edge (already marginal with high turnover).

## Paper 4 implication

K1123 strengthens the "alt-data compendium of nulls" chapter:

- Before K1123: alt-data null for forecasting (K1116/K1118) + null for 2-asset
  allocation (K1121)
- After K1123: alt-data ALSO null for 3-asset cross-asset allocation

The null is robust across forecasting vs allocation, across 2-asset vs 3-asset,
across step-function vs smooth-tilt, and against multiple baselines (static,
risk-parity). Increasingly hard to argue alt-data adds any investable value.

## Derivative research directions (written back to research_program.md)

1. **Is the K846 50/50 moat genuinely untouchable?** K1123 + K1121 + K846
   triple-validate. Next step: stress-test 50/50 across 3 more regime splits
   (inflation / rate-cycle / dollar-cycle) rather than volatility-stress.
2. **What if we abandon alt-data and explore alt-universes?** 50/50 SPY/GLD
   is specifically a *US-asset* moat. Does 50/50 generalize to ex-US
   (50/50 EFA/GLD) and EM (50/50 EEM/GLD)?
3. **TLT is the new VT**: TLT 2022-2024 drawdown is an event-study in duration
   risk. Does "dynamic duration tilt" (TLT when Fed dovish, IEF/cash when
   Fed hawkish) rescue the bond leg? K1124+ possible.
4. **Pure drawdown-reduction overlay**: alt-data may be useless for Sharpe, but
   what if we use it purely as a *drawdown veto* (cut SPY to 0 when NFCI>0.5
   persists 5 days)? Accept lower CAGR for MDD cut of >10%.
5. **Data-mined threshold tuning**: explicitly test 60/70/80/90 percentile
   thresholds + Jensen-adjusted p-value for data-mining. If NONE survives, the
   null is total.

## Files

- `k1123.py` - experiment script (7 strategies, publication-aware lags, TX net)
- `k1123_plots.py` - plot generator
- `k1123_results.json` - all metrics, bootstrap, hypothesis tests
- `weight_trajectory.png` - stacked-area weight evolution (B2 / S1 / S4)
- `cumulative_returns_vs_baselines.png` - all 7 strategies wealth curves
- `risk_metrics_comparison.png` - Sharpe / MDD / Calmar / CAGR bar charts
- `regime_conditional_sharpe.png` - stress vs calm Sharpe by strategy
- `data/panel.parquet` - SPY + GLD + TLT + VIX + EPU + NFCI daily
- `data/weights.parquet` - per-strategy weight panel
- `data/backtest.parquet` - daily returns + turnover + TX
- `data/fred_USEPUINDXD.csv`, `data/fred_NFCI.csv`, `data/fred_STLFSI4.csv` - FRED cache (from K1121/K1122)
- `run.log` - runtime log

## References

- Baker, Bloom, Davis (2016) *QJE* - EPU index
- Brave, Butters (2011) - NFCI (Chicago Fed)
- Politis, Romano (1994) - Stationary bootstrap
- Harvey, Liu, Zhu (2016) - Sharpe t>3 threshold
- K1121 - 2-asset SPY+GLD alt-data allocation (tied 50/50 baseline)
- K1116, K1118 - Alt-data forecasting (all null, 9 experiments)
- K846 - 50/50 SPY/GLD triple-moat validation
- K687, K697 - VT = drawdown insurance, not alpha

## Code review trail

2026-04-17 Gemini review (Codex quota exhausted):

- Lookahead lag: NFCI shift(5), EPU shift(2), vol shift(1) correctly implemented.
  Weight at t uses info from t-1 or earlier. **PASS**
- TX cost: `dw = w.diff().abs().sum()` then `r_net = r_gross - dw * bps/1e4`
  applied to day-t return. **PASS**
- B2 Risk Parity: inverse-vol normalized to sum=1 with shift(1). **PASS**
- Bootstrap: Politis-Romano with correct stationary block logic, block_mean=20,
  centered distribution for 2-sided p-value. **PASS**
- S4 smooth: weights sum to 1 and non-negative due to wSPY clip(0.15, 0.60)
  and gld_share clip(0.15, 0.85). **PASS**

**Gemini verdict: ALL PASS.**

Seed: 42 (np.random.seed + rng.default_rng + bootstrap seed)
