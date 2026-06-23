# Codex Source Review - K1542

Verdict: **PASS_WITH_LIMITATIONS**

Review date: 2026-06-23

## Scope

Reviewed:

- `k1542_muni_convenience_premium_tax_liquidity_stress.py`
- `k1542_muni_convenience_premium_tax_liquidity_stress_results.json`
- `README.md`
- Generated daily panel CSV and PNG figures

## Checks

- Lookahead guard: PASS. ETF cheapening, drawdown, volume, control RV, VIX,
  quarterly tax receipts, and weekly financial-stress inputs are lagged before
  being matched to forward RV/drawdown/correlation targets.
- Data transparency: PASS. yfinance ticker availability and FRED series metadata
  are recorded in the results JSON.
- Formal tests: PASS. In-sample tests use HAC standard errors with
  Bonferroni/BH correction; OOS uses expanding-window forecasts and canonical
  `dm_test` on squared forecast errors.
- Research-honesty framing: PASS. The README reports in-sample passes but keeps
  the overall verdict at `WEAK_DIAGNOSTIC_ONLY` because no OOS target passes the
  DM gate.
- Reproducibility: PASS. `py_compile`, `json.tool`, and non-empty figure checks
  passed after the formal run.

## Findings

No source-level blocker found.

Important caveat: the in-sample MUB/TFI/HYG RV passes are not enough for a
production claim. The OOS improvements for MUB/TFI RV are economically visible
but statistically weak (`dm_t` around -1.4), so the result should be treated as
a follow-up lead, not as a validated cross-asset volatility prior.

## Residual Limitations

- ETF residual cheapening is not a direct bond-level convenience-premium measure.
- ETF volume is not underlying municipal bond trading volume.
- FRED tax receipts are quarterly and lagged; they mainly support the fiscal
  state narrative rather than high-frequency timing.
- A stronger v2 needs municipal fund flows or bond-level MSRB/EMMA data.
