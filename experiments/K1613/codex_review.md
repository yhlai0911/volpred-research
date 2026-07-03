# K1613 Codex source review

Reviewer: Codex self-review in main interactive session
Date: 2026-07-03
Verdict: `CONDITIONAL_PASS`

## Scope

Reviewed:

- `experiments/K1613/K1613.py`
- `experiments/K1613/K1613_results.json`
- `experiments/K1613/README.md`
- generated CSV and PNG artifacts under `data/` and `figures/`

## Checks

### Data binding

PASS. README numbers are copied from `K1613_results.json`:

- TAIFEX formal rows: `1,082` daily rows, `1,060` feature rows, `464` OOS forecasts.
- Formal OOS period: `2020-01-02` to `2021-12-30`.
- Verdict: `DIRECTIONAL_ONLY_NO_HARVEY_PASS`.
- Best TAIFEX model: `HAR_MedRV_input`, QLIKE `0.2380`, improvement `+2.58%`, DM `t=-0.79`, `p=0.432`.

### Lookahead

PASS. The code creates every HAR feature from `measure.shift(1)` before weekly/monthly rolling means. Expanding OOS forecasts use training rows strictly before the forecast row. The target is same-row standard RV after lagged features are built, so the forecast for date `t` uses information through `t-1`.

### Target alignment

PASS. The primary target is fixed as next-day standard 5-minute `RV` for every model. MedRV / RK / TSRV only replace the HAR input series. This avoids the mechanical estimator-specific target alignment problem.

### TAIFEX roll / settlement handling

PASS with caveat. K1613 reads the K1100h 2017-2021 day-session 5-minute bar cache because it preserves intraday close paths needed for RK / TSRV / MedRV. The cache is TX1-derived, so K1613 explicitly drops third-Wednesday settlement days before forecasting.

Caveat: this is still not as clean as the newer K1582 full-TX active-contract loader, because K1582's saved cache is daily aggregate only and cannot recompute intraday-path estimators. A future rerun should persist active-contract intraday bars.

### Inference

PASS. Pairwise inference uses repo `dm_test` with `h=1`, and strict pass requires lower QLIKE plus DM `t < -3`. MCS uses the repo `model_confidence_set`, alpha `0.10`, bootstrap `1,000`, seed `42`.

The result is not overclaimed. MedRV is directionally best, but DM `t=-0.79` is far below the Harvey threshold, and MCS retains all models.

## Caveats

- Self-review is weaker than independent review.
- Fixed RK bandwidth and TSRV grid count are transparent but not optimal bandwidth/noise estimators.
- SPY diagnostic has only `49` OOS forecasts and is correctly marked non-gateable.
- K1100h TX1 data require settlement-day filtering; K1613 applies this but cannot fully replace an active-contract intraday cache.

## Required before publication

Any article should describe K1613 as a measurement-method null/directional result. Do not headline MedRV as a confirmed improvement; the correct phrasing is "directional average QLIKE improvement that fails Harvey/MCS confirmation."
