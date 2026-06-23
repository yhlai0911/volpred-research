# Codex Review - K1538

Verdict: **PASS_WITH_CAVEATS**.

## Scope Reviewed

- `k1538_bond_fund_run_proxy_credit_etf_vol.py`
- `k1538_bond_fund_run_proxy_credit_etf_vol_results.json`
- `README.md`
- generated figures and daily panel

## Checks

- Required experiment files are present.
- Data sources, date range, ticker universe, FRED series IDs, and sample size are
  recorded in results JSON.
- Random seed is fixed at 42.
- Lookahead guard is explicit: `panel["signal_lag"] =
  panel["run_pressure_index"].shift(1)`, while targets begin at date `t`.
- The conclusion is not overstated: no Harvey `t >= 3`, no Bonferroni pass, and
  no OOS DM gate pass.
- FRED fallback behavior is not silent; each series has status and observations
  recorded in `data.fred_status`.

## Caveats

- The proxy is coarse. ETF volume and Amihud-style measures can reflect ETF
  hedging, risk transfer, or market-wide stress, not only bond mutual fund
  redemptions.
- FRED money-market assets are quarterly in this run, so the cash-migration
  component is too low frequency for daily run timing.
- The strongest finding, HYG RV5 HAC t=2.04, is below the project gate and loses
  under multiple-testing correction.
- OOS MSE improvements are positive but statistically weak; do not promote this
  to a trading signal or article-level claim.

## Verification Commands

- `uv run python experiments/k1538_bond_fund_run_proxy_credit_etf_vol/k1538_bond_fund_run_proxy_credit_etf_vol.py`
- `uv run python -m py_compile experiments/k1538_bond_fund_run_proxy_credit_etf_vol/k1538_bond_fund_run_proxy_credit_etf_vol.py`

## Final Use Guidance

Record K1538 as a weak directional proxy / null-gate result. It is useful as a
triage note: public bond ETF run-pressure proxies lean in the expected direction
for short-horizon credit ETF volatility, but are not strong enough to support a
published positive claim without fund-level flow or NAV-discount data.
