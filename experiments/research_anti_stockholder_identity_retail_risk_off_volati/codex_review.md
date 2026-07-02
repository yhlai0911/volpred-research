# Codex Review

## Scope

Reviewed `research_anti_stockholder_identity_retail_risk_off_volati.py`, generated data artifacts, figures, and machine-readable results for reproducibility, lookahead safety, and result interpretation.

## Checks

- Re-ran the experiment with:

```bash
uv run python experiments/research_anti_stockholder_identity_retail_risk_off_volati/research_anti_stockholder_identity_retail_risk_off_volati.py
```

- Verified syntax with:

```bash
python -m py_compile experiments/research_anti_stockholder_identity_retail_risk_off_volati/research_anti_stockholder_identity_retail_risk_off_volati.py
```

- Confirmed nonempty outputs:
  - `data/analysis_panel.csv`
  - `data/summary_table.csv`
  - `research_anti_stockholder_identity_retail_risk_off_volati_results.json`
  - `figures/wikimedia_attention_signal.png`
  - `figures/primary_test_diagnostics.png`

## Lookahead Review

- Primary and secondary Wikimedia identity-attention predictors use `.shift(1)`.
- Generic fear-attention controls use `.shift(1)`.
- FINRA monthly margin controls are forward-filled to trading days and shifted by 22 trading days.
- Market controls use lagged returns, lagged realized variance, or lagged VIX level.
- Future labels are built with `forward_sum` / `forward_mean`, which place `t+1..t+h` outcomes at forecast origin `t`.
- Expanding OOS uses `train_end = pos - horizon`, excluding rows whose forward labels would not be known at the forecast origin.

No lookahead issue was found in the reviewed implementation.

## Result Review

Verdict: `WEAK_RAW_ONLY_NO_ROBUST_OOS_PASS`.

The strongest positive raw cell is retail/meme 22-day realized variance:

- coefficient `+0.1604`
- HAC t `2.85`
- raw p `0.0044`
- Holm p `0.1060`
- OOS MSE improvement `-4.22%`
- DM t `-0.72`

This does not pass the gate. Other weak positive cells also fail Holm correction and worsen OOS forecasts. The result should be described as a weak in-sample diagnostic only, not a usable signal.

## Residual Risk

- The identity proxy is indirect: Wikimedia pageviews are public attention, not surveyed anti-stockholder identity or non-participation attitudes.
- Google Trends and GDELT phrase proxies were not used because both were rate-limited during setup.
- Daily OHLCV cannot identify retail flow, options flow, or broker-specific risk-budget changes.
- FINRA margin debt is monthly and broad; it is a conservative context control, not a high-frequency retail shock.

## Conclusion

The experiment is reproducible and lookahead-safe under the stated public-data fallback design. The evidence does not support promoting this proxy into the strategy or article pipeline without direct identity/search data.
