# Codex Review: K1351

## Scope

Reviewed `experiments/k1351/k1351.py`, reran the experiment, checked generated JSON and
figure metadata, and inspected the lookahead guards for the OOS HAR-X design.

## Findings

No blocking issue found for the current null conclusion.

Important audit points:

- `CL=F` negative-price handling was corrected before finalizing results. The initial log-return
  implementation created invalid values around April 2020; final code uses simple returns and
  records this in README/results.
- Oil features are explicitly lagged via `oil_signal = oil_raw.shift(1)`.
- Target HAR features are lagged via `target_signal = target_raw.shift(1)`.
- Expanding OLS uses only prior rows for target date `t`: `train = df.iloc[:pos].copy()`.
- The verdict requires Harvey `t > 3.0`; `CL=F -> SPY` is therefore correctly treated as weak
  evidence rather than a pass despite positive QLIKE improvement.

## Verification

Commands run:

```bash
uv run python -m py_compile experiments/k1351/k1351.py
uv run python experiments/k1351/k1351.py
jq '{sample, summary}' experiments/k1351/k1351_results.json
file experiments/k1351/fig_k1351_oos_qlike.png experiments/k1351/fig_k1351_oil_vol_context.png
```

Outputs checked:

- `k1351_results.json` verdict: `NULL_NO_HARVEY_PASS`.
- `fig_k1351_oos_qlike.png`: PNG, `1540 x 1120`.
- `fig_k1351_oil_vol_context.png`: PNG, `1540 x 980`.

## Residual Risk

The experiment uses daily close-to-close squared simple returns, not intraday RV. That is acceptable
for this yfinance pilot but should not be cited as high-frequency realized-volatility evidence.
