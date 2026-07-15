# K1379 — Paper 9 HAR-style daily-r² benchmarks (methodology repair)

## Status

This rerun supersedes the 2026-05-19 K1379 artifact. The original run used
reversed QLIKE (`forecast/actual`), an iid loss-differential variance in place
of HAC, an incorrect ad-hoc HLN factor, inconsistent A4f fit/OOS normalization,
and a mutable Paper 9 CSV containing duplicate dates. Those defects invalidate
the old loss levels, DM statistics, and “statistically non-inferior”
interpretation.

K1379 is only **partial evidence** for Paper 9 review item C4. Its two HAR-style
models are trained on lagged daily squared returns, not on intraday realized
variance. They therefore must not be presented as canonical Corsi HAR-RV
benchmarks or as evidence that A4f matches a model requiring intraday data.

## Data and protocol

- Source: `experiments/k1685/data/k1685_spy_vix_snapshot.csv`, an independent
  yfinance 1.2.0 SPY/`^VIX` fetch pinned by K1685 on 2026-07-11.
- SHA256: `eee7f9c62ce3ed3ee68d2bffeb3c9386fb8a6343e1a053379cfc89058518e3fb`.
- Inputs: unadjusted `spy_close` (to retain the original K1379 specification)
  and `vix_close`.
- Analysis data: 2000-01-04 through 2026-05-18; 6,632 return observations.
- OOS policy: 2019-01-01 through the original publication endpoint
  2026-05-18; 1,854 forecast dates and 1,852 shared valid loss dates. Two
  zero-return dates are excluded from every model's QLIKE/DM mask.
- Rolling estimation: 2,000 observations; refit every 63 OOS dates; one-day
  forecast horizon; seed 42.
- Information set: every day-*t* forecast uses returns, squared returns, and
  VIX only through *t−1*. Training slices end strictly before the forecast
  origin.
- A4f timing: estimation and OOS recursion both use the Paper 9 Engle-style
  normalization `u_{t−1}=r_{t−1}/sqrt(τ_t)`. Here `τ_t` is predetermined by
  `VIX_{t−1}`, so this alignment introduces no lookahead.

The old Paper 9 CSV had ten duplicated dates in May 2026. The clean snapshot
has unique dates and the script fails closed on hash drift or duplicate dates.
The OOS end is explicitly fixed so the methodology repair is not confounded by
the snapshot's later observations through 2026-07-10.

## Models and loss

- GJR: rolling GJR-GARCH(1,1).
- A4f: `τ_t = θ₀ + θ₁ VIX²_{t−1}` with free short-run intercept.
- HAR-style daily-r²: OLS on daily, 5-day, and 22-day lags of squared daily
  log returns.
- HAR-style daily-r²-VIX: the preceding regression plus `VIX²_{t−1}`.

All four forecasts are evaluated on the same daily squared-return proxy using
canonical Patton QLIKE:

`L_t = actual_t/predicted_t − log(actual_t/predicted_t) − 1`.

The primary DM statistic calls
`volpred.stats.model_evaluation.dm_test(loss1, loss2, h=1)`. It uses the
canonical rule-selected Bartlett Newey-West bandwidth
`max(1, min(ceil(h^(1/3) n^(1/3)), n//4))`, which is 13 here. The loss
differential is `loss(model 1) − loss(model 2)`, so negative *t* favors the
first named model. The reporting screen is `|t| > 3` (Harvey, Liu, and Zhu,
2016); this is distinct from the Harvey-Leybourne-Newbold small-sample
correction.

Canonical DM is unscaled. For auditability, the results also report the
correct non-primary HLN diagnostic factor
`sqrt((n + 1 − 2h + h(h−1)/n)/n)`. At `h=1`, `n=1,852`, it is 0.999730 and
does not materially affect any result.

## Corrected results

### Pointwise QLIKE

| Model | Mean QLIKE | Interpretation |
|---|---:|---|
| A4f | 1.399812 | Lowest among the three stable specifications |
| GJR | 1.479503 | A4f is 5.386% lower |
| HAR-style daily-r² | 1.524461 | A4f is 8.177% lower |
| HAR-style daily-r²-VIX | 1.1777e9 | Dominated by three nonpositive raw forecasts and the numerical floor |

The HAR-style daily-r²-VIX mean is not a stable economic magnitude. Its raw
OLS forecast is nonpositive on 2019-01-14, 2019-01-16, and 2019-01-18, then
bounded at `1e-16` before QLIKE. On the diagnostic common sample that excludes
those three dates (`n=1,849`), its mean QLIKE is 1.537463 rather than 1.1777e9.

### Canonical HAC-DM

| Comparison (model 1 vs model 2) | DM t | p | loss-diff acf(1) | `|t|>3` | Reading |
|---|---:|---:|---:|:---:|---|
| A4f vs GJR | -4.370 | 0.000013 | -0.023 | PASS | A4f lower loss |
| A4f vs HAR-style daily-r² | -7.699 | 2.22e-14 | -0.064 | PASS | A4f lower loss |
| A4f vs HAR-style daily-r²-VIX | -1.050 | 0.2939 | -0.001 | FAIL | Floor-sensitive comparator; no Harvey-screen difference |
| HAR-style daily-r² vs GJR | +3.110 | 0.001897 | -0.022 | PASS | GJR lower loss |
| HAR-style daily-r²-VIX vs GJR | +1.050 | 0.2939 | -0.001 | FAIL | No Harvey-screen difference |
| HAR-style daily-r²-VIX vs HAR-style daily-r² | +1.050 | 0.2939 | -0.001 | FAIL | No Harvey-screen difference |

For the positive-raw-forecast diagnostic sample, A4f vs HAR-style
daily-r²-VIX is `t=-2.256`, `p=0.0242`, still below the `|t|>3` reporting
screen. Thus the floor changes the loss magnitude but not that qualitative
screen.

### HAC lag sensitivity

| Comparison | lag 0 (no HAC) | lag 1 | lag 5 | lag 10 | lag 13 primary | lag 20 |
|---|---:|---:|---:|---:|---:|---:|
| A4f vs GJR | -4.232 | -4.281 | -4.285 | -4.317 | -4.370 | -4.504 |
| A4f vs HAR-style daily-r² | -7.949 | -8.216 | -8.045 | -7.818 | -7.699 | -7.648 |
| HAR-style daily-r² vs GJR | +2.941 | +2.974 | +3.044 | +3.073 | +3.110 | +3.207 |

A4f's two stable pairwise passes survive the full displayed lag grid. The
GJR-versus-daily-r²-HAR comparison is threshold-sensitive: it misses `|t|>3`
at lags 0 and 1, and narrowly passes from lag 5 onward. Its canonical lag-13
result is primary, but it should be described as borderline rather than as a
bandwidth-invariant result.

## Supersession audit

| Comparison | Old invalid t / p | Corrected t / p | Harvey-screen change |
|---|---:|---:|---|
| A4f vs GJR | -1.191 / 0.2338 | -4.370 / 0.000013 | FAIL → PASS |
| A4f vs HAR-style daily-r² | +0.289 / 0.7723 | -7.699 / 2.22e-14 | FAIL → PASS; sign convention corrected |
| A4f vs HAR-style daily-r²-VIX | +0.648 / 0.5171 | -1.050 / 0.2939 | FAIL → FAIL |
| HAR-style daily-r² vs GJR | -1.073 / 0.2833 | +3.110 / 0.001897 | FAIL → PASS; sign convention corrected |
| HAR-style daily-r²-VIX vs GJR | -1.118 / 0.2638 | +1.050 / 0.2939 | FAIL → FAIL |
| HAR-style daily-r²-VIX vs HAR-style daily-r² | -0.207 / 0.8358 | +1.050 / 0.2939 | FAIL → FAIL |

Three of six Harvey screens change from fail to pass. This old/new comparison
jointly reflects the corrected QLIKE orientation, canonical HAC inference,
aligned A4f normalization, and clean unique-date input; it must not be
attributed to HAC alone.

## Conclusion and limitations

- Under this fixed-window daily-r² proxy protocol, A4f has lower QLIKE than GJR
  and the stable HAR-style daily-r² comparator, and both differences exceed
  the pre-specified `|t|>3` screen.
- The VIX-augmented HAR-style OLS comparator is numerically unstable and yields
  no Harvey-screen difference under either the bounded primary run or the
  positive-forecast diagnostic.
- K1379 does **not** establish equivalence, non-inferiority, or performance
  against canonical intraday HAR-RV. Paper 9 C4 remains only partially
  addressed.
- Daily squared returns are a noisy proxy; the nested model pairs receive an
  unconditional fixed-window predictive-ability comparison, not a dedicated
  equivalence or nested incremental-content test.

## Reproduction and outputs

Run from the repository root:

```bash
uv run python experiments/k1379/k1379.py
```

The script hash-checks its input, regenerates all loss arrays, recreates the
chart, validates a temporary JSON file, and atomically replaces the result.

- `k1379.py`: computation and rendering.
- `k1379_results.json`: full metadata, QLIKE, six DM tests, ACF(1–5), HAC-lag
  sensitivity, correct HLN diagnostics, forecast-stability audit, and
  supersession record.
- `k1379_loss_gjr.npy`, `k1379_loss_a4f.npy`, `k1379_loss_har.npy`,
  `k1379_loss_har_vix.npy`: regenerated pointwise losses.
- `k1379_valid_mask.npy`: common primary evaluation mask.
- `k1379_general_article_chart.png`: corrected public-facing loss and primary
  DM comparison.
- `k1379_hac_lag_sensitivity.png`: pre-specified HAC-lag sensitivity for the
  three stable model comparisons.

## References

- Corsi (2009), *Journal of Financial Econometrics* 7(2), 174–196.
  <https://doi.org/10.1093/jjfinec/nbp001>
- Diebold and Mariano (1995), *Journal of Business & Economic Statistics*
  13(3), 253–263. <https://doi.org/10.1080/07350015.1995.10524599>
- Harvey, Leybourne, and Newbold (1997), *International Journal of
  Forecasting* 13(2), 281–291.
  <https://doi.org/10.1016/S0169-2070(96)00719-4>
- Harvey, Liu, and Zhu (2016), *Review of Financial Studies* 29(1), 5–68.
  <https://doi.org/10.1093/rfs/hhv059>
- Newey and West (1987), *Econometrica* 55(3), 703–708.
  <https://doi.org/10.2307/1913610>
- Patton (2011), *Journal of Econometrics* 160(1), 246–256.
  <https://doi.org/10.1016/j.jeconom.2010.03.034>
