# Codex source-level review — K1346

- Review date: 2026-06-16
- Reviewer: Codex CLI interactive session
- Verdict: CONDITIONAL_PASS

## Scope

Reviewed:

- `experiments/k1346/k1346.py`
- `experiments/k1346/k1346_results.json`
- `experiments/k1346/README.md`

## Findings

### 1. Lookahead / leakage — PASS

The experiment uses current-month outcomes with prior-month features.

- Monthly stock features are explicitly lagged with
  `panel[f"{col}_lag1"] = panel.groupby("ticker")[col].shift(1)`.
- Basket membership for month `t` is ranked on `lottery_score_lag1`.
- Lead regressions use `basket_vov_lag1` or `basket_rv_ann_lag1` for month `t`
  SPY/IWM volatility outcomes.
- Tail-excess thresholds use `out[col].shift(1).rolling(...).quantile(...)`,
  so the target threshold is based on prior months only.

No same-month feature is used to choose same-month basket membership.

### 2. Partial-month handling — FIXED

Initial cold run included the partial 2026-06 month. The script now filters the
monthly stock panel to `last_complete_month_end()`, which sets the final usable
month to 2026-05-31 for `END_DATE = 2026-06-17`.

### 3. Multiple testing / Harvey — PASS

Lead tests store HAC t-statistics, two-sided p-values, Bonferroni-adjusted
p-values across six lead specifications, and Harvey `|t| > 3` flags. No lead
test passes, and the README reports this as NULL rather than a directional
claim.

### 4. Bootstrap / random seed — PASS

All bootstrap draws use `np.random.default_rng(42)`. Results are reproducible
given the cached yfinance CSV.

### 5. Data limitations — DISCLOSED

The design is explicitly survivorship-biased because it uses a current-name
retail/speculative proxy universe. This blocks any CRSP-style stock-level
anomaly claim, but the limitation is documented in both README and JSON.

## Residual risks

- yfinance adjusted close is not a bankruptcy/delisting-safe data source.
- The universe is manually curated and current-name biased.
- Monthly close-to-close VoV is a coarse realized proxy, not intraday or
  option-implied volatility-of-volatility.
- Risk-off amplification is descriptive; only the lagged regressions support
  predictive interpretation.

## Conclusion

The code is acceptable for a public-data NULL pilot. The results support only
the narrow conclusion that this yfinance-only lottery basket does not provide
corrected evidence of benchmark-relative crisis VoV amplification or SPY/IWM
tail-vol lead predictive power.
