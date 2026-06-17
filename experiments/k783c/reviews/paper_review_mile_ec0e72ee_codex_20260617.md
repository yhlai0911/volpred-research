# Codex 24h Source Review: mile_ec0e72ee

- Article: `風險模型該回頭看 1 年還是 8 年？答案其實要先看市場現在安不安靜`
- Task: `paper_review_mile_ec0e72ee`
- Source experiment: `experiments/k783c/`
- Review date: 2026-06-17
- Verdict: `FAIL`

## Scope

Reviewed:

- `experiments/k783c/k783c_cross_period_window.py`
- `experiments/k783c/k783c_cross_period_window_results.json`
- `experiments/k783c/README.md`
- `storage/reports/feed.json` item `mile_ec0e72ee`

`experiments/k783c/README.md` is a placeholder and is not usable as methodological evidence.

## Claim-Evidence Match

The article's reported numbers match the current JSON:

| Article claim | JSON source | Status |
|---|---:|---|
| SPY data `2000-01-04` to `2026-03-31` | `data_period` | PASS |
| Total observations `6,599` | `total_obs=6599` | PASS |
| Windows `252`, `504`, `1000`, `2000`, `3000`, `ALL` | `windows_tested` | PASS |
| High-vol `2020-2021`, best `2000`, scores `335.38`, `413.26`, `547.98` | `results_by_period.high_vol_2020_2021.window_qlike` | PASS to JSON, FAIL to metric |
| High-vol `w=252` worse than `w=2000` by about `63.5%` | `(547.9794 - 335.3769) / 335.3769 = 63.39%` | PASS |
| Moderate `2018-2019`, best `504`, scores `196.85`, `203.26`, `217.22` | `results_by_period.moderate_2018_2019.window_qlike` | PASS to JSON, FAIL to metric |
| Moderate `w=504` improves vs `w=2000` by about `9.4%` | `pct_gain_vs_2000=9.379` | PASS |
| Calm `2016-2017`, best `252`, scores `590.63`, `617.89`, `676.43` | `results_by_period.calm_2016_2017.window_qlike` | PASS to JSON, FAIL to metric |
| Calm `w=252` improves vs `w=2000` by about `12.7%` | `pct_gain_vs_2000=12.683` | PASS |
| Only one pairwise comparison clears the strict threshold | only `moderate_2018_2019.dm_vs_w2000.1000.beats_baseline_harvey=true` | PASS |
| OOS periods each around `503-505` days | `n_oos`: `505`, `503`, `503` | PASS |

The article accurately transcribes the stored result file. The blocker is that the stored score is not the project's canonical Patton QLIKE loss.

## Critical Finding

### K783c uses the inverse of canonical QLIKE

`k783c_cross_period_window.py` defines:

```python
ratio = sigma2_hat / (r2 + eps)
return float(np.mean(ratio - np.log(ratio) - 1))
```

and the pointwise DM loss repeats the same orientation. The canonical project helper `src/volpred/stats/model_evaluation.py` defines Patton QLIKE as:

```python
ratio = actual / predicted
return ratio - np.log(ratio) - 1
```

Equivalently, common volatility-forecast QLIKE is `log(h) + y / h` up to constants, where `y` is realized variance and `h` is the forecast variance. K783c instead uses `h / y`. This is not a harmless algebraic rewrite. It reverses the asymmetry of the loss and heavily penalizes high forecasts on days with tiny realized squared returns. The result file's own `qlike_scale_note` confirms that the large scores are driven by `sigma2_hat/r2` exploding when `r2` is near zero, which is the opposite orientation from the intended proxy-robust loss.

Because the article's central window ranking is entirely based on this score, the published conclusion that crisis/moderate/calm regimes prefer `2000`/`504`/`252` day windows is not source-review safe until rerun with canonical QLIKE.

## Lookahead Audit

No direct lookahead bug found in the rolling forecast chronology. For OOS date `date`, the code finds `pos = all_idx.get_loc(date)` and trains on:

```python
returns.iloc[:pos]
```

or:

```python
returns.iloc[max(0, pos - window):pos]
```

The forecast is then scored against `returns[pos]`. That is equivalent to `signal from t-1, return at t`.

The rolling window therefore does not touch future returns. However, the implementation does not actually refit every `21` trading days despite `REFIT_EVERY=21`: the non-refit branch calls `fit_gjr_garch(train)` again. This is a reproducibility/metadata problem, not lookahead.

## DM / Harvey Check

The article's "only one strict-threshold pair passes" claim matches JSON. But the DM implementation is a hand-rolled Newey-West lag-1 t-statistic with normal p-values and `|t| > 3` reporting. It is not the canonical project helper and not an HLN small-sample correction. This should be disclosed if the experiment is rerun and republished.

The stronger blocker is still the loss orientation: the DM tests are applied to the same inverse-QLIKE pointwise losses, so their pass/fail results inherit the invalid scoring metric.

## Other Issues

- `README.md` is still a planning placeholder, so the experiment lacks a usable written methods/results record.
- The script writes results to a hard-coded stale worktree path (`.claude/worktrees/agent-af08eda0/...`) instead of `experiments/k783c/`, reducing reproducibility.
- The article is appropriately cautious about statistical strength, but the headline takeaway still rests on the invalid score.

## Verdict

`FAIL`.

The article matches K783c's JSON values and the forecast chronology is lookahead-clean. However, K783c's primary score is the inverse of canonical Patton QLIKE, and all rankings and DM tests depend on that score. Do not cite or syndicate the article's window-regime conclusion as reviewed evidence until K783c-v2 reruns with:

1. canonical `volpred.stats.model_evaluation.qlike_pointwise(actual, predicted)`;
2. canonical DM helper or explicit custom-HAC disclosure;
3. corrected refit cadence or corrected metadata;
4. a real `README.md` methods/results summary;
5. regenerated charts and article language after the corrected run.
