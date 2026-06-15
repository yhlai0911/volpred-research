# Codex Review — K1504 Natural Gas Seasonality / Samuelson Proxy

Reviewer: Codex CLI
Date: 2026-06-16
Verdict: **CONDITIONAL_PASS**

## Scope

Reviewed:

- `experiments/k1504_samuelson_natgas/k1504.py`
- `experiments/k1504_samuelson_natgas/k1504_results.json`
- `experiments/k1504_samuelson_natgas/README.md`

## Findings

No critical source-level issues found.

## Checks

### 1. Reproducibility

PASS. The script reruns end-to-end:

```bash
uv run python experiments/k1504_samuelson_natgas/k1504.py
```

It writes:

- `k1504_results.json`
- `data/natgas_close.csv`
- `data/monthly_realized_vol.csv`
- `data/ng_front_month_expiry_panel.csv`
- two PNG figures

The script uses the existing local yfinance close snapshot first and only falls
back to network download if the local source is missing.

### 2. Numerical Consistency

PASS. README headline numbers match `k1504_results.json`:

- `NG=F` ANOVA `F=3.204`, permutation `p=0.0012`, peak/trough `1.86x`.
- `UNG` ANOVA `F=2.450`, permutation `p=0.0084`, peak/trough `1.55x`.
- Samuelson proxy continuous coefficient `+0.0036`, `t=1.28`.
- Near-expiry dummy coefficient `+0.0217`, `t=0.58`.
- Near-far bootstrap `P(near > far)=0.199`.

### 3. Lookahead / Timing

PASS.

- Monthly persistence control is `lag_log_rv_ann = groupby(ticker).shift(1)`.
- Daily persistence control is `lag_log_abs_ret = shift(1)`.
- The expiry-distance proxy uses calendar information known before the return
  is observed.
- The experiment does not turn same-day season labels into a tradable strategy
  claim.

### 4. Over-Claim Risk

PASS with caveat. The README correctly says:

- Calendar-month seasonality is supported.
- The front-month expiry-distance proxy fails.
- A true Samuelson test requires a contract-level futures maturity panel.

This caveat is essential. `NG=F` is a Yahoo continuous front-month proxy, not a
multi-maturity futures panel.

### 5. Method Caveats

Accepted caveats:

- Business-day counts use a standard weekday calendar, not a full CME holiday
  calendar.
- Yahoo roll timing may not match CME active-contract conventions.
- The test uses close-to-close daily returns, not intraday or implied
  volatility.
- Seasonal ANOVA is descriptive; lagged monthly RV absorbs much of the
  incremental seasonal dummy evidence.

## Final Assessment

`CONDITIONAL_PASS` is appropriate. K1504 is usable as a natural-gas
seasonality result and as a negative free-data Samuelson-proxy screen. It
should not be cited as proof for or against the true Samuelson effect in
natural gas futures without a contract-level term-structure dataset.
