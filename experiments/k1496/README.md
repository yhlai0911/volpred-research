# K1496 — HAR-RV Window Length vs Regime on TAIFEX TX1

- Experiment ID: `K1496`
- Status: complete
- Task: `research_realized_variance_regime`
- Seed: `42`

## Motivation

`research_realized_variance_regime` asked whether the "right" realized-volatility window length depends on regime, and whether high-volatility states should shorten the HAR-style memory window while low-volatility states lengthen it.

This matters because the repo has many HAR-like baselines, and a naive "22-day monthly component is always right" assumption may be too rigid if intraday RV reacts very differently in calm versus stressed markets.

## Data

- Asset: TAIFEX TX1 day session
- Source: local cached 5-minute realized variance panel from [`experiments/k1303/data/_tx1_daily_cj_2017-2026.parquet`](/Users/yhlai0911/Desktop/volpred-research/experiments/k1303/data/_tx1_daily_cj_2017-2026.parquet)
- Sample: `2017-05-16` to `2026-05-08`
- Daily rows: `2186`
- RV definition: sum of 5-minute squared log returns over the day session

This is a true intraday-RV target, not a daily `r²` proxy.

## Literature Check

- Corsi (2004/2009), HAR-RV: multi-horizon realized-volatility components can mimic long memory with a parsimonious additive structure.
- Andersen, Bollerslev, Diebold, and Labys (2003): realized volatility constructed from intraday data is the correct empirical object for volatility forecasting.
- Feng and Zhang (2025), *Journal of Forecasting*: window-size choice can materially change realized-volatility forecast loss, and the optimal choice is an empirical question rather than a fixed convention.
- Patton (2011): QLIKE remains the standard loss for variance-forecast comparison.

## Design

### Model family

To isolate the window-length question, this experiment uses a generalized HAR-style two-scale specification:

```text
log(RV_t) = a + b1 * log(RV_{t-1}) + bw * mean(log(RV_{t-w:t-1})) + e_t
```

Candidate windows:

- `w=5`
- `w=10`
- `w=22`
- `w=63`

The `shift(1)` discipline is explicit in code: both `RV_{t-1}` and the rolling window use only information available before day `t`.

### Primary forecast scheme

- Estimation: rolling OLS
- Training window: `1000` trading days
- OOS target: one-day-ahead `RV_t`
- Loss: QLIKE on true intraday RV

### Regime definition

Regimes are **not** split with full-sample thresholds.

- Signal: lagged 22-day mean RV
- Classification: expanding tertiles, using only history available before each date
- Warmup: 252 days

This avoids the known full-sample-threshold lookahead pitfall documented elsewhere in the repo.

### Robustness

Four estimation schemes are compared:

- rolling `504`
- rolling `1000`
- rolling `1500`
- expanding `1000`

### Bootstrap

- Circular block bootstrap
- Block length: `21`
- Reps: `1000`
- Seed: `42`

Bootstrap is used for regime-conditional loss differences such as `QLIKE(5d) - QLIKE(63d)`.

## Main Results

### Primary spec: rolling-1000

Best window by regime:

| Regime | Best window | Key nuance |
|---|---:|---|
| Low RV tertile | `63d` | only by a hair; all four windows are nearly tied |
| Mid RV tertile | `5d` | clear advantage over `22d` and `63d` |
| High RV tertile | `5d` | long windows fail badly when vol spikes |

Primary mean QLIKE by regime:

| Regime | 5d | 10d | 22d | 63d |
|---|---:|---:|---:|---:|
| Low | 4.3496 | 4.3530 | 4.3504 | 4.3486 |
| Mid | 1.7546 | 1.7547 | 1.8882 | 2.0092 |
| High | 77.4911 | 122.6482 | 304.8198 | 622.0476 |

Interpretation:

- **High-volatility regimes clearly punish long memory windows.**
- The apparent low-volatility preference for `63d` in the primary spec is economically tiny.

### Robustness verdict

The "high vol -> shorter window" conclusion is robust.

The "low vol -> longer window" conclusion is **not** robust.

Across robustness schemes:

- high regime best window = `5d` in **4/4**
- mid regime best window = `5d` in **4/4**
- low regime best window flips between `5d` and `63d`

So the honest conclusion is:

> **Regime dependence exists mainly on the high-vol side.**  
> In stressed states, long windows (`22d`, `63d`) become too stale.  
> In calm states, evidence for "you should definitely lengthen to 63d" is weak and unstable.

### Split-half adaptive-rule audit

An ex-ante rule was learned on the first half of OOS:

- low -> `63d`
- mid -> `5d`
- high -> `5d`

Applied to the second half of OOS, it performs essentially the same as fixed `5d`, not better.

That means the low-regime extension is too weak to produce a meaningful overall gain.

## Practical Takeaway

The defensible rule from this experiment is conservative:

1. Do **not** hard-code `22d` as the universally right HAR long-memory window for TAIFEX intraday RV.
2. In high-volatility states, shorten aggressively; `5d` is the safest choice in this sample.
3. Do **not** promote a low-volatility `63d` rule into production yet; the evidence is too setting-dependent.

## Files

- Script: [`experiments/k1496/k1496.py`](/Users/yhlai0911/Desktop/volpred-research/experiments/k1496/k1496.py)
- Results: [`experiments/k1496/k1496_results.json`](/Users/yhlai0911/Desktop/volpred-research/experiments/k1496/k1496_results.json)
- Figure 1: ![primary](/Users/yhlai0911/Desktop/volpred-research/experiments/k1496/k1496_primary_regime_qlike.png)
- Figure 2: ![robustness](/Users/yhlai0911/Desktop/volpred-research/experiments/k1496/k1496_robustness_heatmap.png)

## Caveats

- Single market: TAIFEX TX1 only. This is a methodology-calibration result, not a universal cross-asset law.
- The model family is intentionally simplified to isolate window length. It is not a full HAR-CJ / semivariance horse race.
- The adaptive rule was audited with a split-half procedure, but not yet embedded in a live rolling selector.
- No knowledge entry is written here; code/result review should happen first.
