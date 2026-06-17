# Codex 24h Source Review: mile_cbf8ba62

- Article: `統計檢定通過了，監管機關還是會亮黃燈：換個分配假設，差距就出來了`
- Task: `paper_review_mile_cbf8ba62`
- Source experiment: `experiments/k802/`
- Review date: 2026-06-17
- Verdict: `FAIL`

## Scope

Reviewed:

- `experiments/k802/k802_gjr_skewt.py`
- `experiments/k802/k802_gjr_skewt_results.json`
- `experiments/k802/plot_article_charts.py`
- `storage/reports/feed.json` item `mile_cbf8ba62`

`experiments/k802/README.md` is a placeholder and is not usable as evidence.

## Claim-Evidence Match

The article's reported numeric values match the current JSON:

| Article claim | JSON source | Status |
|---|---:|---|
| OOS 2023-2024, `n=502` | `n_oos=502` | PASS |
| GJR+Normal: 9 violations, 1.79%, Kupiec p=0.108, yellow, Trinity fail | `var_backtest_results.GJR+Normal` | PASS |
| GJR+StudentT: 6 violations, 1.20%, Kupiec p=0.670, green, Trinity pass | `var_backtest_results.GJR+StudentT` | PASS to JSON, FAIL to methodology |
| GJR+SkewedT: 6 violations, 1.20%, Kupiec p=0.670, green, Trinity pass | `var_backtest_results.GJR+SkewedT` | PASS to JSON, FAIL to methodology |
| GARCH+Normal: 7 violations, 1.39%, p=0.402, green | `var_backtest_results.GARCH+Normal` | PASS to JSON |
| GJR+FHS: 5 violations, 1.00%, p=0.993, green | `var_backtest_results.GJR+FHS` | PASS to JSON |
| QLIKE GJR=1.469, GARCH=1.514, DM=-3.25, p=0.0012 | `qlike_results` | PASS |
| Spearman GJR=0.212, GARCH=0.109 | `spearman_results` | PASS |

The failure is not a transcription error. It is a methodology/specification problem in the experiment and the article's regulatory framing.

## Critical Findings

### 1. Basel traffic-light rule is nonstandard and internally inconsistent

`k802_gjr_skewt.py` classifies Basel zones by violation rate:

```python
if pi_hat <= alpha_var * 1.5:
    traffic = 'green'
elif pi_hat <= alpha_var * 2.0:
    traffic = 'yellow'
else:
    traffic = 'red'
```

That makes `6/502 = 1.20%` green. But the article says that in `500` trading days, `1%` VaR with `5` to `9` violations is yellow and `5` or fewer is green. Under that article text, Student-t and Skewed-t with `6` violations would be yellow, not green.

The standard Basel traffic-light table is defined for a 250-day backtest: green `0-4`, yellow `5-9`, red `>=10`. K802 neither applies the canonical 250-day rule nor clearly discloses that it is using a custom rate-scaled rule. Therefore the central claim "Student-t/Skewed-t turn Trinity green" is not publication-grade evidence.

### 2. Student-t / Skewed-t VaR quantiles are not unit-variance standardized

The code estimates df from standardized residuals, then uses raw SciPy t quantiles:

```python
z_t = float(t_dist.ppf(alpha_var, df=df_t_cur))
var_gjr_t[i] = sigma_gjr * z_t
```

For a standardized Student-t innovation with unit variance, the quantile should be scaled by `sqrt((df-2)/df)`. With K802 df around `16`, the unscaled quantile is roughly `6.8-7.0%` wider than the unit-variance quantile. The script comments mention this issue but do not apply the scale. The Fernandez-Steel skewed-t path is likewise not centered or variance-standardized.

This matters because the article's main mechanism is that Student-t/Skewed-t reduce violations from `9` to `6`. A several-percent widening of the tail threshold could be enough to change that count in a 502-day sample. The current run cannot support a clean claim that the improvement comes from a correctly standardized innovation distribution.

## Other Issues

- `dm_test()` is hand-implemented inside `k802_gjr_skewt.py`, not the canonical project helper. It is a Newey-West HAC t-statistic and uses the strict `|t| > 3` threshold; the article's QLIKE/DM wording is directionally acceptable, but it should not imply a full HLN/Harvey small-sample correction.
- `var_backtest()` returns Kupiec/Christoffersen p=1 in boundary cases such as zero violations or degenerate transition probabilities. This does not drive the current `6-9` violation counts, but it is unsafe for reuse.
- `plot_article_charts.py` draws the yellow threshold at `1.5%`, matching the custom code rule, while the article text describes a count-based `5-9` yellow range. The visual and prose are therefore not the same standard.

## Lookahead Audit

No direct lookahead bug found in the OOS loop. For current OOS index `t`, the code sets `r_train = returns_all[:t]`, fits/refits on past data only, then forecasts the variance and VaR threshold for `returns_all[t]`. This is equivalent to `signal from t-1, return at t`.

## DM / Harvey Check

The article's QLIKE numbers and DM statistic match the JSON. However, the implementation is a custom HAC DM statistic with `|t| > 3` reporting, not the canonical helper and not a full HLN correction. This is a disclosure issue, not the main blocker.

## Verdict

`FAIL`.

The article accurately copies K802 JSON values, but K802's Basel/Trinity classification and Student-t/Skewed-t VaR construction are not strong enough to support the published conclusion. The central claim should be treated as unreviewed/unsafe until K802-v2 reruns with:

1. canonical Basel traffic-light handling, preferably on rolling annual 250-day windows or with a clearly justified custom 500-day rule;
2. unit-variance standardized Student-t and centered/variance-standardized skewed-t quantiles;
3. regenerated charts and article language after rerun;
4. canonical DM helper or explicit "custom Newey-West DM" disclosure.

No knowledge update or downstream paper/article citation should use K802's `dual_champion_achieved=true` until the rerun is complete.
