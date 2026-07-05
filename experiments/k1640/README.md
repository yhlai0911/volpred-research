# K1640 - VIX 30/40 panic-entry event study

## Research Question

Is "buy SPY when VIX breaks 30 or 40" genuinely better than entering on a random trading day?

K1640 is a focused 30/40-threshold replication of the broader K1633 myth-bust. It keeps the task-specified thresholds only and re-computes the full event-study table with seed 42.

## Data

- Source: yfinance `^VIX` close and SPY adjusted close
- Cache: `data/vix_full.csv`, `data/spy_full.csv`
- Period: 1993-01-29 to 2026-07-02
- Trading days: 8,413
- Event definition: first upward cross from below, de-clustered by 20 trading days

Event counts:

- VIX > 30: 50 events
- VIX > 40: 17 events

## Method

Primary entry is signal-day close:

```python
fwd = SPY[t + H] / SPY[t] - 1
```

This is an event-study convention: it measures what happened after the VIX close crossed the threshold. It is not a same-close executable trading claim.

Robustness uses explicit one-day lag:

```python
signal_lag1 = signal.shift(1).fillna(False)
```

For each threshold x horizon cell:

- Horizons: 5, 10, 20, 60 trading days
- Baseline: every eligible trading day as entry, same SPY price series
- Inference: HAC/Newey-West regression `forward_return ~ event_dummy`, `maxlags = H`
- Multiple testing: Benjamini-Hochberg FDR across 8 lag0 cells
- Placebo: 5,000 random-entry draws per cell
- Seed: 42

## Main Result

Verdict: `CONDITIONAL_PASS_HALF_TRUE_QUALIFIED`

Baseline SPY win rates are already high:

- H5: 58.8%
- H10: 61.9%
- H20: 65.4%
- H60: 71.9%

Lag0 primary cells:

| Cell | Events | Excess mean | Win vs baseline | HAC p | BH q |
|---|---:|---:|---:|---:|---:|
| VIX>30, H5 | 50 | +1.26% | +11.2pp | 0.0068 | 0.054 |
| VIX>30, H60 | 50 | +2.55% | +2.1pp | 0.0360 | 0.096 |
| VIX>40, H60 | 17 | +6.19% | +16.4pp | 0.0191 | 0.076 |

Multiple testing:

- 8 lag0 cells
- 7/8 have positive excess return
- Raw 5% survivors: VIX>30/H5, VIX>30/H60, VIX>40/H60
- FDR 5% survivors: none
- FDR 10% survivors: VIX>30/H5, VIX>30/H60, VIX>40/H60

Lag1 robustness is weaker:

- 8 lag1 cells
- 6/8 have positive excess return
- Raw 5% survivor: VIX>30/H5 only
- FDR 5% survivors: none
- FDR 10% survivors: none

## Interpretation

The myth is half true. Panic entry after VIX 30/40 tends to beat a random entry date, but the edge is incremental and statistically fragile under strict multiple-testing control.

The durable pattern is not an instant bounce. The strongest economic pattern is 60 trading days, especially VIX>40 with +6.19% excess mean, but that cell has only 17 events. The short-horizon "close your eyes and buy" story is much weaker once lag1 timing and FDR are applied.

## Relationship to K1633

K1633 is the broader 30/35/40 general-audience myth-bust and article evidence package. K1640 is the task-specific 30/40 replication with its own script, result JSON, figures, and seed=42. The overlapping 30/40 numbers match K1633's lag0 primary results up to rounding.

## Outputs

- `k1640.py`: reproducible experiment script
- `k1640_results.json`: full cell-level results, FDR, placebo, lag1 robustness
- `data/k1640_cell_summary.csv`: compact per-cell table
- `data/k1640_event_returns.csv`: event-level forward returns
- `figures/k1640_excess_returns.png`
- `figures/k1640_winrates.png`

## Literature Checked

- Whaley (2000), The Investor Fear Gauge
- Giot (2005), Relationships Between Implied Volatility Indexes and Stock Index Returns
- Bekaert and Hoerova (2014), The VIX, the Variance Premium and Stock Market Volatility
