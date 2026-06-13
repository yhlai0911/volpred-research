# K905 / mile_40c66bef — Codex 24h-rule Review

- **Article**: `mile_40c66bef` "風險模型愈花俏愈準嗎？這次市場給了相反答案"
- **Published**: 2026-06-13T09:01:29.109534+00:00
- **Review date**: 2026-06-13
- **Reviewer**: Codex desktop
- **Task**: `paper_review_mile_40c66bef`
- **Linked K**: `K905`
- **Verdict**: `CONDITIONAL_PASS_AFTER_CORRECTION`

## Summary

The article's main numeric claims match
`experiments/k905/k905_quantile_vol_forecast_results.json`, and the script's OOS
loop uses data through `t-1` for each evaluated return. The review found one
article-level over-broad statement: the original "5% all models fail" phrasing
was true only under the script's strict Trinity screen, which applies a
Basel-style 250-day traffic-light check to 5% VaR. It was not true for
Kupiec + Christoffersen coverage tests alone.

Mitigation applied:

- Updated the published article via `scripts/publish_draft.py --update`.
- Added a visible 2026-06-13 correction note to the article.
- Completed the previously placeholder K905 README with data, method, result,
  figure, and limitation sections.

## A. Lookahead — PASS

The OOS loop explicitly uses training data ending before the evaluated return:

- `train_end = pos`, `r_train = returns.values[:train_end]`
- the evaluated return is appended later via `oos_returns.append(returns.values[pos])`

Relevant source lines: `k905_quantile_vol_forecast.py:666-674`,
`k905_quantile_vol_forecast.py:705-710`,
`k905_quantile_vol_forecast.py:760-774`.

Quantile HAR training also builds features from `t-1`:

- `compute_har_features(r_sq, t - 1)` for training rows
- `quantile_har_predict()` uses the latest available training return, not the
  target return

Relevant source lines: `k905_quantile_vol_forecast.py:318-330`,
`k905_quantile_vol_forecast.py:373-380`.

No same-day signal times same-day return issue was found.

## B. Number Consistency — PASS

Cross-checks against `k905_quantile_vol_forecast_results.json`:

| Article claim | Ground truth | Verdict |
|---|---:|---|
| OOS period 2019-01-02 to 2026-04-02 | `oos_period` exact match | PASS |
| OOS sample 1,823 days | `n_oos = 1823` | PASS |
| FHS lowest pinball loss at 1% | `M3_FHS = 0.00038414`, rank 1 | PASS |
| FHS lowest pinball loss at 5% | `M3_FHS = 0.00125298`, rank 1 | PASS |
| Normal 1% breach rate 2.03% | `M1_Normal.var_1pct.violation_rate = 0.020296` | PASS |
| CAViaR 1% breach rate 0.88% | `M4_CAViaR.var_1pct.violation_rate = 0.008777` | PASS |
| 1% full Trinity passes only Student-t and FHS | `M2_StudentT` and `M3_FHS` only | PASS |

The two article figures are generated from the same stored result JSON via
`experiments/k905/k905_article_figures.py`.

## C. Statistical Framing — FIXED

Original issue:

- `trinity_test()` always combines Kupiec + Christoffersen + Basel-style
  traffic-light screen.
- `basel_traffic_light()` uses the standard 250-day exception thresholds
  (`<=4` Green, `5-9` Yellow, `>9` Red), which are designed for 1% regulatory
  VaR.
- Applying that same screen to 5% VaR makes the 5% "all fail" statement a strict
  project screen, not a formal Basel 5% verdict.

Relevant source lines: `k905_quantile_vol_forecast.py:521-537`,
`k905_quantile_vol_forecast.py:576-581`.

The corrected article now states:

- under the strict Trinity screen, all five models fail at 5%;
- under Kupiec + Christoffersen coverage alone, Normal, FHS, CAViaR, and
  QuantHAR pass at 5%, while Student-t fails Kupiec.

## D. DM / Harvey Claims — PASS

The article does not claim that FHS significantly beats all alternatives. The
corrected wording clarifies that FHS is the point-estimate leader rather than a
formal significance winner.

Stored DM tests versus FHS all have `significant_Harvey = false`. The largest
raw 5% result is CAViaR versus FHS (`t = 2.0646`, `p = 0.0390`), but it does not
cross the project `abs(t) > 3.0` publication threshold.

## E. Reproducibility — CONDITIONAL_PASS

Before this review, `experiments/k905/README.md` was a planning placeholder. The
script and result JSON existed, but the experiment folder did not satisfy the
current documentation standard.

Fixed in this review:

- README status changed to `COMPLETE`.
- Data source, OOS period, model list, metrics, figure generation, and limitations
  are now documented.

Remaining limitations:

- The script still stores no HLN small-sample adjusted DM p-values.
- The 5% Basel-style screen remains in the artifact as a conservative project
  screen; future experiments should either make the function alpha-aware or label
  this screen explicitly in JSON.
- Supabase sync was not run in this sandboxed hourly tick; local feed/report files
  were updated.

## Article Update Applied

Command used:

```bash
MPLCONFIGDIR=/private/tmp/matplotlib-cache .venv/bin/python scripts/publish_draft.py \
  storage/drafts/k905_general_draft.md \
  --update mile_40c66bef \
  --update-action codex_24h_review_k905_correction \
  --update-summary "Codex 24h review clarified that the 5% all-fail statement applies to the strict Trinity screen with a Basel-style 250-day check, while Kupiec + Christoffersen coverage passes for most models; K905 README provenance was completed."
```

A second update only cleaned wording after the general-audience sanitizer rewrote
one phrase awkwardly. It did not change numbers or methodology.

## Conclusion

`CONDITIONAL_PASS_AFTER_CORRECTION`.

The published article is now aligned with the stored K905 artifact and no longer
overstates the 5% VaR result. K905 is acceptable as a general-audience article,
with the documented caveat that the strict 5% Trinity verdict depends on a
Basel-style screen that is conservative outside its standard 1% regulatory use.
