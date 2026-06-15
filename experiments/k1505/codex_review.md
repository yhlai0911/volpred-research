# K1505 Codex Self-Review

Verdict: PASS

## Checks

- Lookahead: PASS. Month-t vol signal uses `real_return_paths[:, month - 12 : month]`, excluding `r_t`; market drawdown is read before applying month-t return, and market NAV updates only after the withdrawal / return step (`k1505_vol_aware_withdrawal.py:198`, `k1505_vol_aware_withdrawal.py:205`, `k1505_vol_aware_withdrawal.py:230`).
- Timing: PASS. Withdrawal occurs before applying the month return, matching the stated beginning-of-month convention (`k1505_vol_aware_withdrawal.py:216`, `k1505_vol_aware_withdrawal.py:222`, `k1505_vol_aware_withdrawal.py:227`).
- Data integrity: PASS. SPY/IEF adjusted closes are cached from yfinance; CPI comes from local FRED CPIAUCSL; partial current month is dropped before monthly returns (`k1505_vol_aware_withdrawal.py:87`, `k1505_vol_aware_withdrawal.py:107`, `k1505_vol_aware_withdrawal.py:113`).
- Randomness/reproducibility: PASS. Fixed seed, path count, horizon, and 12-month moving-block bootstrap are explicit (`k1505_vol_aware_withdrawal.py:46`, `k1505_vol_aware_withdrawal.py:155`, `k1505_vol_aware_withdrawal.py:292`).
- Drawdown formula: PASS. Historical signal drawdown and simulated wealth MDD both use compounded NAV / cumulative wealth peaks, not cumulative-sum returns (`k1505_vol_aware_withdrawal.py:130`, `k1505_vol_aware_withdrawal.py:171`).
- Statistical comparison: PASS. Dynamic policies are compared to fixed on the same bootstrap paths with paired path-level deltas and CI (`k1505_vol_aware_withdrawal.py:278`, `k1505_vol_aware_withdrawal.py:379`).
- Overclaim guard: PASS. Results JSON marks `not_an_oos_forecast=true`, records the full-sample vol threshold caveat, and reports spending shortfall alongside ruin probability (`k1505_vol_aware_withdrawal.py:348`, `k1505_vol_aware_withdrawal.py:383`).

## Residual Risks

- The common ETF/CPI sample is only 242 monthly observations; 30-year results are bootstrap simulation, not historical cohort evidence.
- The vol threshold is descriptive full-sample calibration. It should not be reused as an advertised live OOS forecast without a separate walk-forward test.
