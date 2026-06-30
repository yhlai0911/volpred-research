# K1584 — Co-jump / HAR-CJ Jump-Axis Pilot

## Motivation

K1584 tests whether adding a jump axis improves realized-volatility forecasting. The motivating literature is stronger than the local data available in this repository:

- Caporin, Kolokolov, and Reno (2017), "Systemic co-jumps", *Journal of Financial Economics*, DOI `10.1016/j.jfineco.2017.06.016`.
- Ding, Li, Liu, and Zheng (2024), "Stock co-jump networks", *Journal of Econometrics*, DOI `10.1016/j.jeconom.2023.01.026`.
- Corsi, Pirino, and Reno (2010), "Threshold bipower variation and the impact of jumps on volatility forecasting", *Journal of Econometrics*, DOI `10.1016/j.jeconom.2010.07.008`.
- Bormetti et al. (2015), "Modelling systemic price cojumps with Hawkes factor models", *Quantitative Finance*, DOI `10.1080/14697688.2014.996586`.

The proper systemic co-jump design needs synchronized multi-asset high-frequency data. The local repository does not currently contain a long synchronized multi-asset panel, so this experiment is intentionally narrower: a gateable single-market HAR-CJ forecast test on TAIFEX TX plus a short, non-gateable SPY/0050 same-calendar-date diagnostic.

## Data

### Gateable HAR-CJ test

- Market: TAIFEX TX active-contract day session.
- Source: `experiments/k1582/data/tx_active_daily_measures_2017_2026.parquet`.
- Lineage: K1582 built this cache from raw TAIFEX `Daily_*TX.csv` tick files, selecting the active contract by day-session volume and aggregating prices to intraday returns.
- Raw sample: 2017-05-16 to 2026-06-29.
- Daily rows: 2,219.
- Feature rows after lag/rolling warm-up: 2,197.
- OOS forecasts: 1,697.
- Minimum training window: 500 observations.

### Co-jump diagnostic only

- Markets: local SPY and 0050.TW 5-minute CSV snapshots.
- Sources: `data/intraday/SPY_5min_2026-*.csv`, `data/intraday/0050_TW_5min_2026-*.csv`.
- Overlap: 98 same-calendar-date observations from 2026-01-20 to 2026-06-26.
- Status: diagnostic only. This is not clock-synchronized cross-market high-frequency data and is not a systemic co-jump network test.

## Method

For each day, the script computes:

- `RV`: sum of intraday squared log returns.
- `BPV`: Barndorff-Nielsen-Shephard bipower variation.
- continuous variance: `min(BPV, RV)`.
- jump variance: `max(RV - continuous_variance, raw_jump_from_K1582, 0)`.
- jump share: `jump_variance / RV`.
- jump event flag: `jump_share > 0.01`.

These are distinct objects. Jump event count, jump variance, and jump share are not interchangeable.

The one-step forecast target is `RV_t`. All forecast features are built from source series shifted by one day:

```python
lag = series.shift(1)
d[f"{name}_w"] = lag.rolling(5, min_periods=5).mean()
d[f"{name}_m"] = lag.rolling(22, min_periods=22).mean()
```

Each OOS forecast trains an expanding OLS model on rows strictly before the forecast row. Models are estimated in log-RV space and retransformed with a residual-variance correction.

Models:

- `HAR`: log RV lags at daily, weekly, monthly horizons.
- `HAR_C`: continuous-variance lags only.
- `HAR_RVJ`: HAR plus lagged jump-share and jump-event features.
- `HAR_CJ`: continuous-variance lags plus jump-share and jump-event features.
- `HAR_CJ_cluster`: `HAR_CJ` plus lagged 5-day and 22-day jump-event frequencies.

Evaluation:

- Primary loss: Patton QLIKE on `RV_t`.
- Pairwise tests: `volpred.stats.model_evaluation.dm_test`, horizon `h=1`.
- Strong gate: candidate lower QLIKE than HAR and DM `t < -3`.
- Bootstrap: moving-block bootstrap on mean loss difference, `B=1000`, block size 5, seed 42.

## Results

### TX HAR-CJ forecast test

Verdict: **NULL**.

HAR is the best model by mean QLIKE:

| Model | Mean QLIKE | QLIKE improvement vs HAR | DM t vs HAR | DM p |
|---|---:|---:|---:|---:|
| HAR | 0.168677 | baseline | baseline | baseline |
| HAR_C | 0.168994 | -0.188% | 0.326 | 0.745 |
| HAR_RVJ | 0.169800 | -0.666% | 1.414 | 0.157 |
| HAR_CJ | 0.169973 | -0.768% | 1.590 | 0.112 |
| HAR_CJ_cluster | 0.170121 | -0.856% | 1.704 | 0.089 |

The jump split does not improve the gateable TX forecast. The strongest result is actually in the wrong direction: adding jump-cluster features worsens mean QLIKE by 0.86%, with a positive DM statistic, meaning candidate losses exceed HAR losses.

Jump diagnostics for the TX panel:

- Jump-event days: 1,242 / 2,219.
- Jump-event rate: 55.97%.
- Mean jump-variance share: 7.08%.
- Median jump-variance share: 2.97%.

The high event rate reflects the deliberately low `jump_share > 0.01` diagnostic threshold. The formal forecast comparison uses continuous jump-share regressors, not only this event count.

### SPY/0050 same-calendar-date diagnostic

This diagnostic is **not gateable**.

- Overlap days: 98.
- SPY jump days: 53.
- 0050.TW jump days: 67.
- Same-calendar-date co-jump days: 39.
- Expected co-jump days under independence: 36.23.
- Event-indicator correlation: 0.122.
- Permutation upper-tail p-value: 0.156.

Interpretation: the short local SPY/0050 panel does not provide strong evidence of systemic co-jump clustering. Because the two assets trade in different time zones and this diagnostic uses same calendar dates rather than synchronized timestamps, it should not be cited as a network result.

## Conclusion

K1584 is a null result for the implementable HAR-CJ jump axis. On the only long, gateable local intraday panel, splitting realized variance into continuous and jump components does not improve next-day RV forecasts beyond a plain HAR baseline.

The literature-motivated systemic co-jump direction remains potentially valuable, but this experiment says the repository needs a long synchronized multi-asset high-frequency panel before making network or Hawkes-style claims.

## Files

- `k1584.py`: experiment script.
- `k1584_results.json`: full machine-readable results.
- `data/tx_harcj_oos_forecasts.csv`: OOS forecasts and actual RV.
- `figures/k1584_harcj_diagnostics.png`: QLIKE comparison and recent TX jump-share plot.

## Reproducibility

Run from the repository root:

```bash
uv run python experiments/k1584/k1584.py
```

Seed: 42.
