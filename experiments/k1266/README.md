# K1266: Multivariate Rough Volatility (rough Bergomi) on SPY/QQQ/IWM

**Date**: 2026-05-03
**Verdict**: **NULL** (FAIL — multivariate rough vol does not beat DCC-GARCH)
**Status**: Code review in progress (Codex), preliminary results below

## Motivation

arXiv:2412.14353 (December 2024) proposes a multivariate rough volatility
framework that extends univariate Rough Bergomi (Bayer-Friz-Gatheral 2016)
to multi-asset settings via correlated rough innovations. This experiment
tests whether such framework outperforms (i) univariate rough Bergomi and
(ii) DCC-GARCH (Engle 2002) on a 3-ETF panel (SPY, QQQ, IWM).

## Differentiation from prior work in this repo

| K | What | Verdict |
|---|------|---------|
| K34 | Rough HAR + Cross Rough multivariate (Ridge over-shrinks) | NEGATIVE |
| K529 | Rough vol pilot SPY (HAR-Rough best, RFSV vs GJR DM p=0.80 NS) | NULL |
| K785 | MF2-GARCH (Conrad-Engle) | one of 7 ML ceiling fails |
| K806 | Multivariate fBm + cross-asset H regressors | NULL |
| K936 | EWMA time-varying Hurst | NULL (DM t=-0.80 NS) |
| K973 | SPY daily R/S Hurst centered on 0.5 | rough vol unmeasurable daily |
| K1129 | 4 commodity × rough vol | 4/4 triple-gate FAIL |
| K1263 | latest ML ceiling check | FAIL |
| **K1266** | **Multivariate rough Bergomi + DCC baseline + joint Σ eval** | **NULL (this work)** |

K1266 differs from K806 by: (a) different spec (rough Bergomi vs mfBm),
(b) different baseline (DCC-GARCH, missing in K806), (c) different
evaluation (joint Σ multivariate QLIKE + Frobenius, not r²-only),
(d) different assets (US ETF panel, not cross-asset zoo).

## Methodology

### Data
- Assets: SPY, QQQ, IWM
- Source: yfinance (auto_adjust=False, raw Close)
- Period: 2010-01-05 to 2026-04-29 (4,104 trading days)
- IS: 2010-01-05 to 2018-12-31 (n=2,263)
- OOS: 2019-01-02 to 2026-04-29 (n=1,841, includes 2020 COVID + 2022 bear)

### Models

1. **DCC-GARCH(1,1)** (Engle 2002) — multivariate baseline
   - Step 1: per-asset GARCH(1,1) → conditional std D_t
   - Step 2: dynamic correlation Q_t = (1−a−b)Q̄ + a·zz' + b·Q_{t−1}
   - Step 3: Σ_t = D_t R_t D_t

2. **Univariate Rough Bergomi** (per-asset, simplified RFSV)
   - log v_{t+1} = α·mean(recent 22d) + (1−α)·mean(window 252d)
   - α = 0.5 + (0.5 − H), H from variogram
   - Convexity adjustment for log-normal forecast
   - Treats Σ as diagonal (no cross-asset correlation)

3. **Multivariate Rough Vol** (arXiv:2412.14353, simplified)
   - Per-asset rough Bergomi forecast → σ_i
   - Constant correlation matrix R from IS log-RV residuals
   - Σ_{t+1} = D R D

### Evaluation

| Metric | Formula | Direction |
|---|---|---|
| Per-asset QLIKE | r²/v − log(r²/v) − 1 | lower better |
| Multivariate QLIKE | tr(Σ⁻¹ rr') + log\|Σ\| | lower better |
| Frobenius distance | ‖Σ_f − rr'‖_F | lower better |
| DM-HLN test | Harvey-Leybourne-Newbold corrected DM | \|t\| > 1.96 sig |

### Lookahead controls

- Forecasts use only data with index < t (`prior_idx = rets.index < dt`)
- Univariate and multivariate rough vol forecast functions explicitly
  exclude day-t observation from history
- DCC-GARCH `forecast_one_step(last_returns)` uses only t−1 returns
- IS parameters frozen for OOS evaluation (no peek-ahead refitting)

### Seed

`np.random.seed(42)` at module top. No bootstrap or MC sampling needed
(closed-form forecasts).

## Results

### Headline (1,841 OOS days, 2019-01-02 → 2026-04-29)

| Metric | DCC-GARCH | Univariate Rough | Multivariate Rough |
|---|---|---|---|
| Multivariate QLIKE (mean) | **−26.04** | −22.31 | −23.54 |
| Rel. improvement (mv_rough vs dcc) | — | — | **−9.58%** (worse) |
| DM-HLN t (mv_rough vs dcc) | — | — | **+13.90** (DCC wins decisively) |
| DM-HLN p | — | — | < 0.001 |
| Subperiod wins (mv_rough vs dcc) | — | — | **0/3** |

### Per-asset OOS QLIKE (mean)

| Asset | DCC-GARCH | Univariate Rough | Multivariate Rough |
|---|---|---|---|
| SPY | **1.5520** | 2.0476 | 2.0476 |
| QQQ | **1.5125** | 1.8138 | 1.8138 |
| IWM | **1.3931** | 1.6859 | 1.6859 |

DCC-GARCH wins on every asset by 27%–32% margin. Note that univariate
and multivariate rough vol have identical per-asset QLIKE — this is by
design: per-asset QLIKE only depends on Σ[i,i] = σ_i², which is the
same in both models (mv_rough only adds off-diagonal correlation, which
does not affect diagonal QLIKE). The two models differ only on
multivariate QLIKE and Frobenius.

### DM-HLN t-stats (positive = first model loss higher = second wins)

| Comparison | mv_QLIKE | Frobenius | SPY | QQQ | IWM |
|---|---|---|---|---|---|
| mv_rough vs dcc | +13.90 | +15.20 | +11.72 | +9.63 | +6.51 |
| uni_rough vs dcc | +20.33 | +16.72 | +11.72 | +9.63 | +6.51 |
| mv_rough vs uni_rough | −31.54 | +1.78 | nan | nan | nan |

mv_rough beats uni_rough on multivariate QLIKE (DM t=−31.54) — the
correlation structure helps over zero-correlation diagonal — but loses
on Frobenius (t=+1.78), and both lose vs DCC across the board.

Per-asset comparison between mv_rough and uni_rough yields nan because
losses are identical (0/0).

### Hurst estimates (IS, variogram method)

- SPY: 0.0153 (essentially noise; consistent with K973 daily R/S → 0.5)
- QQQ: 0.0153
- IWM: 0.10 (estimator floor / fallback applied)

Daily close-to-close log-RV gives variogram H ≈ 0, not the literature
H ≈ 0.10 obtained from 5-min RV (per K529 / K973). Rough vol regime
is hard to detect at daily horizon.

### DCC parameters (MLE on IS)

a = 0.2366, b = 0.7188, a+b = 0.9554 (well below unit root, reasonable)

## Verdict: NULL — 8th rough/frontier ceiling failure

| Gate | Threshold | Result | Pass? |
|---|---|---|---|
| Multivariate QLIKE rel. improvement | > 2% | −9.58% | NO |
| DM-HLN p | < 0.10 | ~0.0 (wrong direction) | NO |
| Subperiod consistency | ≥ 2/3 | 0/3 | NO |

Multivariate rough vol fails decisively against DCC-GARCH on every
metric and every subperiod. This is the **8th** rough-vol / frontier-NN
ceiling failure in this repo (K785, K816, K816v2, K784, K787, K806,
K1129, K1263, **K1266**).

## Counter-intuitive finding (vs prior expectation)

**Expected (~95% prior)**: marginal NULL or noisy result.
**Found**: decisive failure with DM t > 13 in DCC's favor — much
stronger than expected. The simplified rough Bergomi forecast is
**systematically biased** vs GARCH, not just noisy. Two likely reasons:

1. The closed-form rough Bergomi forecast uses log-RV stationary mean
   blend, which under-reacts to recent shocks compared to GARCH
   recursion (GARCH α=0.10+ on r² shock, rough Bergomi α=0.9 on log-RV
   recent which is much smoother).
2. Daily Hurst ≈ 0 means the "rough" regime is unobservable at this
   horizon (consistent with K973). The model is essentially fitting
   noise as if it were rough structure.

This is consistent with **Abi Jaber & Li (2025)** finding that rough vol
implementation underperforms GARCH in practice (knowledge entry
referenced in K45 lit review).

## Limitations

1. **Simplified rough Bergomi spec** — not a full Bayer-Friz-Gatheral
   MC simulation. The closed-form approximation may not capture full
   benefit of rough dynamics. arXiv:2412.14353's full DCC-style time-
   varying R on rough innovations is also simplified to constant R here.
2. **Daily horizon** — rough vol literature uses 5-min RV, where
   H ≈ 0.10 is observable. Daily close-to-close gives H ≈ 0 → rough
   regime unmeasurable, consistent with K973.
3. **Per-asset QLIKE identical** — uni and mv rough have same diagonal
   Σ → identical per-asset QLIKE. This is mathematical, not a bug.
4. **Frozen-IS estimation** — no rolling refit. Rolling DCC may track
   regime shifts better but adds estimation noise.

## Files

- `k1266.py` — main implementation (univariate + multivariate rough Bergomi + DCC-GARCH + DM-HLN)
- `k1266_results.json` — full results (per-day losses, DM tests, subperiods)
- `k1266_qlike_comparison.png` — 3 models × 3 assets bar chart
- `k1266_dm_heatmap.png` — DM-HLN t-stat heatmap (3 pairs × 5 metrics)
- `data/etf_returns.csv` — cached daily log returns

## References

- arXiv:2412.14353 (2024-12) "Multivariate rough volatility"
- Bayer, Friz, Gatheral (2016) "Pricing under rough volatility", Quantitative Finance
- Engle (2002) "Dynamic Conditional Correlation", JBES 20:339–350
- Gatheral, Jaisson, Rosenbaum (2018) "Volatility is rough", Quantitative Finance
- Patton (2011) "Volatility forecast comparison using imperfect volatility proxies", J. Econometrics
- Harvey, Leybourne, Newbold (1997) "Testing the equality of prediction mean squared errors", IJF
- Abi Jaber & Li (2025) — rough vol practical underperformance (cited in K45 lit review)

## Reproducibility

```bash
cd /Users/yhlai0911/Desktop/volpred-research
python experiments/k1266/k1266.py
# Runtime: ~30 seconds
# Output: k1266_results.json + 2 PNG charts
```

Seed: 42. Determinism: complete (no MC, all forecasts closed-form).
