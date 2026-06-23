# Codex Source Review - K1541

Verdict: **PASS_WITH_LIMITATIONS**

Review date: 2026-06-23

## Scope

Reviewed:

- `k1541_convertible_vol_management_beta_timing.py`
- `k1541_convertible_vol_management_beta_timing_results.json`
- `README.md`
- Generated PNG figures and daily panel CSV outputs

## Checks

- Lookahead guard: PASS. Volatility-management weights use
  `asset_ret.rolling(21).std().mul(sqrt(252)).shift(1)`, and rolling beta
  replication estimates each date from observations ending at `t-1`.
- Data transparency: PASS. Results JSON records yfinance availability, effective
  sample windows, FRED UMCSENT source, and the unavailable `CONV` proxy.
- Formal tests: PASS. The script uses project canonical
  `strategy_dm_test(loss_fn="negative_return")`, 1,000 fixed-seed circular
  block-bootstrap Sharpe CI, and HAC alpha tests. The conclusion follows the
  formal gate rather than raw Sharpe differences.
- Reproducibility: PASS. Random seed is fixed at 42; `py_compile` and
  `json.tool` validation passed after rerun.
- Output integrity: PASS. Results JSON, two daily panel CSVs, and four non-empty
  PNG figures were generated.

## Findings

No source-level blocker found.

The conclusion is appropriately conservative: `CWB` and `ICVT` volatility
management reduce drawdown, but neither clears the VM-vs-raw gate nor the
stricter VM-vs-VM-beta gate. `CONV` is explicitly reported as unavailable
rather than backfilled.

## Residual Limitations

- ETF proxies cannot answer individual convertible-bond issue selection or
  convertible-arbitrage questions.
- Levered weights do not include financing costs above 1x.
- UMCSENT is a coarse monthly sentiment proxy; AAII was not used in this
  free-source run.
- The beta replication is a liquid factor baseline, not a structural convertible
  valuation model.
