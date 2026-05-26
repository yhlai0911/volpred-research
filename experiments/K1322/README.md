# K1322 — HAR-RV vs Random Walk on 0050.TW 5-min RV (Taiwan ETF)

**Status**: exploratory framework setup, small-sample (`UNTRUSTWORTHY_SMALL_SAMPLE`)
**Date run**: 2026-05-26
**Worktree**: `agent-af9b396e7976b970b`
**Seed**: 42

## Motivation

The TAIFEX TX1 NULL quartet (K868 day/night, K1301 HAR-RS semivariance, K1303 HAR-CJ jump, K1309 BMA) converged on a clean conclusion:

> **Standard HAR-RV (Corsi 2009) is a near-sufficient statistic for daily realized variance on TAIFEX TX1.** Semi-variance, jump, and BMA augmentations all NULL once HAR-RV is included.

K1322 asks the natural cross-market question: **does the same finding hold on the 0050.TW Taiwan ETF?** The two instruments differ in important microstructure dimensions:

| dimension          | TAIFEX TX1                          | 0050.TW                              |
|--------------------|-------------------------------------|--------------------------------------|
| instrument         | index future                        | spot ETF                             |
| liquidity          | deep (institutional / arb book)     | moderate (retail-tilted)             |
| session            | 08:45-13:45 day + night (17:00-05:00) | 09:00-13:30 day only               |
| open mechanism     | continuous from prior session       | 09:00 call-auction opening           |
| tick density       | very high (tens of thousands/day)   | ~52 5-min bars / day in this sample  |

If HAR-RV beats Random Walk significantly on 0050.TW too, the **near-sufficient-statistic claim generalises across Taiwan instruments**, strengthening the TX1 finding. If NULL on 0050.TW but PASS on TX1, the difference itself becomes a new research direction (which microstructure feature breaks HAR-RV).

This first iteration is **exploratory** — the available intraday window (76 trading days, 2026-01-20 to 2026-05-22) is too short to give the Diebold-Mariano test useful power. The script and JSON schema are the deliverables; the verdict is gated on a future re-run when `n_total >= 200`.

## Data

- **Source**: `data/intraday/0050_TW_5min_<date>.csv` (76 files, accessed from main repo)
- **Schema**: 3-row metadata header (`Price/Ticker/Datetime`), then 5-min OHLCV bars
- **Session**: 09:00-13:30 TW (01:00-05:30 UTC in file timestamps)
- **Pre-open drop**: the 01:00 UTC bar (`Volume == 0`) is a pre-open auction snapshot; dropped before computing returns
- **Effective bars/day**: ~52 (sd=0) after dropping the auction bar

## Method

### RV construction (per day d)
```
r_5min,k = log(P_k / P_{k-1})            for k = 1 .. M
RV_d     = sum_k r_5min,k^2
```

### HAR-RV (Corsi 2009) — alternative model
```
log(RV_t) = b_0 + b_d * log(RV_{t-1}) + b_w * log(RV_w) + b_m * log(RV_m) + eps_t
```
where `RV_w = mean(RV_{t-5..t-1})` and `RV_m = mean(RV_{t-22..t-1})` — all features `.shift(1)`-ed on a lagged daily series.

### Random Walk — baseline
```
log(RV_t) ≈ log(RV_{t-1})       (no parameters)
```
Identical lag convention to HAR; this is the fair baseline (cf. K1303 v2 ABD fix).

### Lookahead policy
- All features explicitly `.shift(1)` before the target date.
- Rolling means are computed on the lagged series — never the contemporaneous one.
- Target = `log(RV_t)` (same-day realized variance, standard Corsi/ABD 1-step convention).
- 70/30 **chronological** split (no shuffle).

### Loss & test
- Loss = **QLIKE pointwise** (Patton 2011) on the RV level: `L(a, f) = a/f - log(a/f) - 1`. (We exponentiate the log-RV forecasts before computing QLIKE.)
- Test = **Diebold-Mariano with Newey-West HAC + HLN small-sample correction (Harvey 1997)**, `h=1`. Imported from `volpred.stats.model_evaluation.dm_test`; inline fallback if the package is unavailable.
- Pass rule (Harvey 2016 threshold): `|DM_HLN_t| > 3` **AND** HAR-RV QLIKE < RW QLIKE.

### Seed
`np.random.seed(42)` at module top. OLS via `numpy.linalg.lstsq` (deterministic). No bootstrap (small-sample makes it uninformative); seed kept for any future stochastic addition.

## Results

| field                | value             |
|----------------------|-------------------|
| n\_total\_days       | 76                |
| n\_train             | 37                |
| n\_test              | **17**            |
| RV mean / std        | 8.59e-05 / 6.19e-05 |
| HAR \beta\_d         | 0.178             |
| HAR \beta\_w         | 0.460             |
| HAR \beta\_m         | -1.197 (large SE) |
| HAR QLIKE (OOS)      | 0.170             |
| RW  QLIKE (OOS)      | 0.443             |
| HAR OOS R²           | -0.444            |
| RW  OOS R²           | -2.008            |
| **DM-HLN \|t\|**     | **1.87**          |
| **DM-HLN p**         | **0.080**         |
| verdict              | `UNTRUSTWORTHY_SMALL_SAMPLE` |

(`\|t\|` written with escaped pipes per K549 sanitizer convention.)

**Reading**: HAR-RV produces a noticeably lower QLIKE than the Random Walk (0.170 vs 0.443) and lower MSE on log-RV, with the DM-HLN t-statistic at 1.87 (p ~ 0.08) — directionally consistent with HAR-RV being preferred, but well below the Harvey 2016 `\|t\| > 3` threshold. With `n_test = 17`, this test is severely under-powered; both models post negative OOS R² because the in-sample mean is a non-trivial baseline on this short window. **No publishable claim** rests on this run — it is a framework smoke test.

## Caveats

1. **n_test = 17 < 50** — DM-HLN is under-powered; the test cannot distinguish HAR-RV from Random Walk at the Harvey threshold even when the QLIKE gap looks meaningful in raw terms.
2. **Negative OOS R²** for both HAR and RW reflects the short window: test variance is below the in-sample mean baseline, which is common in compact regimes and not by itself evidence of model failure.
3. **HAR \beta\_m = -1.20** (large SE 0.60) — this is a small-sample artifact, not a real negative monthly persistence. Expect to flip sign / shrink toward 0.1-0.4 as n grows.
4. **Single asset, single regime** — 2026-01-20 to 2026-05-22 happens to be a benign trending environment. Cross-regime robustness requires more sample.

## Revisit gate

**Threshold**: `n_total_days >= 200` (approx. Aug 2026 if 5-min data collection continues at the current 76-day-per-4-month cadence).

When re-run with n >= 200:
- `n_test ~ 60`, sufficient for Harvey-threshold DM-HLN power
- Verdict should be one of `PASS`, `NULL`, `CONDITIONAL_PASS` (not `UNTRUSTWORTHY_SMALL_SAMPLE`)
- Compare resulting verdict to TX1 NULL quartet for cross-market generalisation claim

## How to reproduce

```bash
uv run python experiments/K1322/K1322.py
```

Outputs:
- `experiments/K1322/K1322_results.json` — all numeric outputs above plus full methodology
- `experiments/K1322/rv_series.png` — daily RV time series chart
- `experiments/K1322/codex_review.md` — Codex primary-path code review

## Related K

- **K868** — TAIFEX day/night session boundary forecast timing
- **K1301** — HAR-RS (semivariance) NULL on TX1
- **K1303** — HAR-CJ (continuous + jump) NULL on TX1
- **K1309** — Bayesian model averaging NULL on TX1
- **K848** — original TAIFEX 5-min RV construction

## References

- Corsi, F. (2009). *A simple approximate long-memory model of realized volatility*. JFE 7(2):174-196.
- Andersen, T., Bollerslev, T., Diebold, F. (2007). *Roughing it up*. RFS 89(4):701-720.
- Patton, A. (2011). *Volatility forecast comparison using imperfect volatility proxies*. JoE 160(1):246-256.
- Harvey, D., Leybourne, S., Newbold, P. (1997). *Testing the equality of prediction mean squared errors*. IJF 13(2):281-291.
- Harvey, C. (2016). *Editorial: The scientific outlook in financial economics*. JoF 72(4):1399-1440.
