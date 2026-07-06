# S-02 Cross-OOS Rerun Report — vt-insurance-cost v3

**Task**: `paper2_vt_insurance_cost_s02_cross_oos_rerun`  
**Date**: 2026-07-06  
**Verdict**: S-02 fixed, but evidence remains weak. S2 is not contribution-tier.

## Source Changes

- Modified root runner: `experiments/k811v2/k811v2_insurance_premium_vov_fixed.py`
- Synced paper-bundled runner: `paper/vt-insurance-cost/experiments/k811v2_insurance_premium_vov_fixed.py`
- Removed live `yfinance` fetch from the rerun path.
- Loader now uses pinned raw-Close CSVs from `paper/vt-insurance-cost/data/`:
  - `spy_2012_2024.csv`
  - `gld_2012_2024.csv`
  - `vix_2012_2024.csv`
  - `vvix_2012_2024.csv`
- Cross-OOS grid expanded from 4 to 6 complete two-year windows:
  - 2013-14
  - 2015-16
  - 2017-18
  - 2019-20
  - 2021-22
  - 2023-24
- Archived results file is preserved. New output files:
  - `experiments/k811v2/k811v2_insurance_premium_vov_fixed_cross_oos6_results.json`
  - `paper/vt-insurance-cost/experiments/k811v2_insurance_premium_vov_fixed_cross_oos6_results.json`

## Data Basis

The rerun uses pinned raw-Close CSVs generated with `auto_adjust=False`, matching the paper reproduction rule. It does not download data.

One basis difference remains: the archived K811v2 result includes the 2012-01-03 return using a 2011 close from the original live pull, yielding `N=3262`; the pinned 2012-2024 reproduction CSVs start on 2012-01-03, so the first computable return is 2012-01-04 and the rerun has `N=3261`. This does not affect the six Cross-OOS windows, which begin in 2013.

## Six-Window Results

| Window | S0 Sharpe | S2 Sharpe | S2 beats S0 | S3 beats S0 | S4 beats S0 |
|---|---:|---:|---:|---:|---:|
| 2013-14 | 1.4591 | 1.3764 | No | No | No |
| 2015-16 | 0.1524 | -0.2130 | No | No | No |
| 2017-18 | 0.2759 | 0.3078 | Yes | Yes | Yes |
| 2019-20 | 0.7169 | 1.3367 | Yes | Yes | Yes |
| 2021-22 | -0.0434 | -0.2171 | No | No | No |
| 2023-24 | 1.5100 | 1.3468 | No | No | Yes |

Summary:

- S2 beats S0 in `2/6` windows.
- S3 beats S0 in `2/6` windows.
- S4 50/50 SPY/GLD beats S0 in `3/6` windows.
- Full-sample DM remains below Harvey threshold:
  - S2 vs S0: `t=0.7487`, `p=0.4541`, not significant.
  - S1 vs S0: `t=2.4156`, below `|t| > 3`.

## Code Review

PASS for the rerun purpose.

- **No live fetch**: runner reads pinned CSVs only; no `yfinance` import remains.
- **No archived overwrite**: output goes to `*_cross_oos6_results.json`, preserving `k811v2_insurance_premium_vov_fixed_results.json`.
- **Atomic output**: JSON is written to a temp file, parsed with `json.load`, then atomically replaced.
- **Lookahead**: strategy signals remain lagged through `vov_zscore_lag`, `vix_rising_lag`, `vov_lag`, and `vix_lag`; S2/S3 weights use lagged arrays.
- **Cross-OOS completeness**: all six complete non-overlapping windows are now reported.

## Paper Action

`main.tex` was updated to use the complete six-window evidence and downgrade S2:

- Abstract: S2 success-rate framing updated to `2 of 6`; S2 framed as hypothesis-generating.
- Introduction: cost decomposition is now the primary contribution; VVIX conditioning is exploratory.
- Cross-OOS section: replaced incomplete-window caveat with six-window results.
- Discussion/limitations/conclusion: S2 moved out of contribution tier; cost decomposition remains the robust contribution.

## Verification Commands

```bash
uv run python -m py_compile experiments/k811v2/k811v2_insurance_premium_vov_fixed.py paper/vt-insurance-cost/experiments/k811v2_insurance_premium_vov_fixed.py
uv run python experiments/k811v2/k811v2_insurance_premium_vov_fixed.py
uv run python paper/vt-insurance-cost/experiments/k811v2_insurance_premium_vov_fixed.py
jq '.cross_oos' experiments/k811v2/k811v2_insurance_premium_vov_fixed_cross_oos6_results.json
```
