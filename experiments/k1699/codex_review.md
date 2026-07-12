# K1699 Codex Code Review

- **Date**: 2026-07-12
- **Reviewer**: Codex CLI (`codex exec`, gpt-5.4, reasoning effort high, read-only sandbox)
- **Scope**: `experiments/k1699/k1699.py` + referenced modules (`experiments/k880/k880_prg_spy_validation.py`, `paper/prg-periodic-garch/experiments/k881_prg_multi_asset.py`, `k886_prg_0050tw.py`, `k883_taifex_tick_prg.py`) + canonical `src/volpred/stats/model_evaluation.py`
- **Note**: first attempt with default gpt-5.6-sol/ultra timed out at 570s (bounded wrapper exit 124); review completed on gpt-5.4/high.

## Verdict

**PASS_WITH_CAVEAT** — "I do not see a headline-invalidating lookahead or parameter-order bug. The saved six-market DM table is credible."

## Findings (verbatim from Codex)

1. `k881/k886`-family PRG close-convention path has a refit-failure stale-state hole. In k1699.py (prg_close_convention_forecasts, `_prg_forecast_day` branch), if a scheduled refit returns `None`, the code skips both full-state rebuild and the one-day propagation, then still forecasts with the old `h_state`. In that failure path the forecast is based on `F_{t-2}` rather than `F^c_{t-1}`. This is not a lookahead bug, and I do not see an obvious symptom in the saved `k1699_results.json`, but it is a real correctness risk.

2. TAIFEX lag-robustness variant lacks an explicit lower-bound guard for `i_ov_prev = i_ov - 2`. For this experiment's actual split (`IS_FRACTION=0.60` on a long sample) it is effectively safe, so it does not invalidate the reported TAIFEX headline cell.

Checked and passed (Codex items 3–7):

3. The headline PRG variants themselves are strict `t-1` day-ahead. `tminus1_exp` and `tminus1_lag` only use `h` after intraday `t-1`, `r_intra[t-1]`, and optionally lagged overnight `t-1`; only the canonical diagnostic touches day-`t` overnight data, by design. Underlying state recursions in k880/k881/k886 match that timing.
4. TAIFEX session indexing/measurability is correct. `build_session_series` defines session `2d` as overnight and `2d+1` as intraday; `prg_recursive_oos` computes `h[t]` from `x[t-1], r[t-1]`. So `h_all[i_ov]` and `params_at_session[i_ov]` are `F^c_{d-1}`-measurable, and refits use only `r_arr[:t]`.
5. GJR and HAR are genuinely strict one-step-ahead in all referenced modules (GJR refits on `[:t]`, rebuilds state to `t-1`, updates once with `r[t-1]`; HAR uses only shifted lag regressors).
6. Parameter ordering is consistent: estimators return `[o0,a0,b0,o1,a1,b1,g0,g1]`; `_prg_propagate_days_numba(o0,a0,b0,g0,o1,a1,b1,g1,...)` call is correct.
7. Evaluation logic is sound: canonical QLIKE `actual/predicted` orientation, canonical DM `loss_a - loss_b` with negative `t` favoring the first model, common-sample masking before both, orientation labelled correctly. The 2x-bandwidth helper is a reasonable sensitivity diagnostic. Minor note: common sample is also intersected with `PRG_canonical_diag` (stricter than necessary, harmless — kept intentionally as the K1544 anchor).

## Post-review fixes applied (2026-07-12, same session)

- **Finding 1 fixed**: the `_prg_forecast_day` branch now tracks `rebuilt`; when a scheduled refit fails, the one-day state propagation still runs with the previous parameters, keeping the forecast on `F^c_{t-1}`.
- **Finding 2 fixed**: `i_ov_prev >= 0` guard added to the TAIFEX lag variant.
- **Additional fix found during rerun verification (not a Codex finding)**: rerunning from the pinned CSV snapshots produced TAIFEX values that drifted visibly (QLIKE ~1%, DM t -0.49 → 0.00) versus the in-memory build. Root cause: pandas `read_csv` default C float parser is up to 1 ulp off; the non-convex PRG/GJR MLEs amplify 1e-16 input perturbations into different optimization basins. Fixed by `float_precision="round_trip"` on all snapshot reads. After the fix, two consecutive runs from snapshots are bit-identical, and TAIFEX matches the original tick-built values exactly.
- Because the ulp fix also restored the OHLC markets to the exact snapshot bits, final table values shifted at noise level versus the table Codex saw (e.g., SPY exp-vs-GJR DM t +0.30 → +0.74). No cell changed Harvey status for exp-vs-GJR (all remain insignificant) and the exp-vs-HAR significance pattern is identical, so the reviewed conclusions carry over unchanged.
