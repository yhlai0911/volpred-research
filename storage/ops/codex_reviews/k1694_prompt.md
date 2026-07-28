# K1694 primary-path review — FCM clearing concentration × commodity small-trader crowding-out

You are reviewing a **completed** experiment that reports a **NULL** verdict. Your job is
the primary path: does the code actually estimate what the write-up claims, and is the
NULL trustworthy (i.e. not a NULL manufactured by a bug)?

## Files

- `experiments/K1694/K1694.py` — analysis script (the only compute path)
- `experiments/K1694/lag_sensitivity.py` — publication-lag robustness check
- `experiments/K1694/K1694_results.json` — main result
- `experiments/K1694/K1694_lag_sensitivity.json` — lag grid result
- `experiments/K1694/README.md` — status
- `experiments/K1694/data/*.csv` — cached inputs (FCM monthly, DCOT weekly, RV monthly)

## Background you need

This directory was salvaged from a stale worktree on 2026-07-19 with **no results at all**;
the original agent never got the script to run. On 2026-07-29 three defects were fixed so
it would execute:

1. `build_panel`: `.dt.to_timestamp(how="end").normalize()` → `.dt.normalize()` (pandas
   API; `Series` has no `.normalize`).
2. `panel_regression`: the panel time index was a pandas `Period`, which `linearmodels`
   rejects outright. Now indexed on `month_ts` (timestamp).
3. `bootstrap_interaction`: replicate months were relabelled `f"B{k}"` (a **string**),
   so `PanelOLS` raised on every replicate, the bare `except Exception: return np.nan`
   swallowed it, and `boots` came back empty — i.e. the bootstrap had been silently
   estimating nothing. Relabel is now the integer `k`, and the point-estimate path
   converts a `Period` month to a timestamp. `n_boot` is now 2000/2000.

Fix 3 is the one that most deserves your scepticism: it changed a silent all-NaN path
into a live one, and it is the path that produces the headline CI.

## Reported result

- Verdict: **NULL**
- spec1 `fcm_x_highvol`: coef 3.146e-04, t_DK 1.55, t_cluster_month 1.59
- Block bootstrap (by month, 2000 reps): point 3.509e-04, 95% CI [-2.72e-05, 7.47e-04],
  two-sided p 0.074
- Time-series spec `hhi_x_volfrac`: t 0.54 (HAC lag 6)
- Panel: 3293 usable rows, 22 commodities, 2014-02..2026-07

## Questions to answer, in order

1. **Does the bootstrap now do what it claims?** Block bootstrap is by month; check the
   resampling preserves the cross-sectional block, that the relabelling cannot collide,
   and that the point estimate and the replicates estimate the *same* specification
   (note the bootstrap `rhs` omits the time trend `t` that spec1 includes — is that
   intentional or a spec mismatch that makes the CI incomparable to the reported t-stats?).
2. **Lookahead / lag alignment.** `FCM_LAG_DAYS = 45` is a *synthetic* constant:
   `avail_date = month_end + 45d`, never checked against real CFTC publication dates. The
   as-of merge is `merge_asof(..., left_on="month_end", right_on="avail_date",
   direction="backward")`. Two things to judge: (a) is the merge direction genuinely
   lookahead-free, and (b) the outcome `d_nonrep` is measured *across* the month whose
   `month_end` is the merge key, so a signal that became available mid-month is matched to
   an outcome partly predating it — does that matter for the stated (associational) claim?
   `K1694_lag_sensitivity.json` re-estimates spec1 over assumed lags 30/45/60/75/90 days;
   |t_DK| stays in 1.27-1.55 throughout. Is that sufficient to retire the concern?
3. **Is the NULL real or manufactured?** Look for power loss from construction errors:
   the `rv_z` / `highvol` within-commodity transforms use full-sample moments (a
   look-ahead in regime *labelling* — does it bias toward or away from NULL?), the
   `dropna` cascade, the FCM series being a single system-wide monthly factor
   (effective d.o.f.), and `_acf_bandwidth(np.zeros(nmonths), nmonths)` — the
   Driscoll-Kraay bandwidth is computed from a zero vector, not from residuals. Is that
   a defensible floor or a bug?
4. **Does anything in `K1694_results.json` overstate what was estimated?** Check
   `data_provenance` and `limitations` against the code.

## Verdict contract

End your review with a line of exactly this form:

`VERDICT: PASS` — the NULL is trustworthy and may be written to knowledge.json, or
`VERDICT: FAIL` — with the specific defect(s) that must be fixed first.

Be adversarial. A NULL that comes from a broken estimator is worse than no result,
because it closes a research direction that was never actually tested.
