# K1360 Codex Source Review

Review date: 2026-06-21

Reviewer: Codex CLI (`codex-vscode`)

Verdict: **CONDITIONAL_PASS**

The code supports the reported `WEAK_KALSHI_DIAGNOSTIC_UNDERPOWERED` conclusion. I found no source-level blocker that would justify a stronger claim or reverse the headline interpretation.

## Checks

| Area | Status | Evidence |
|---|---|---|
| Three-piece experiment standard | PASS | `README.md`, `K1360.py`, `K1360_results.json` exist. |
| Data provenance | PASS | Results JSON records Kalshi public API endpoints, yfinance tickers, selected series, sample dates, market counts, and Polymarket probe cache paths. |
| Scope | PASS | Script includes CPI, Core CPI, FOMC, Payrolls, and NFP-style Kalshi series (`K1360.py:53-60`). |
| Lookahead | PASS | Regression predictors are explicitly lagged with `.shift(1)` after calendar-day aggregation (`K1360.py:537-541`). |
| Signal aggregation | PASS | Event-market rows are reduced to event-day max absolute probability shock before daily regression (`K1360.py:389-424`), avoiding direct pooled market-row inference. |
| Baseline | PASS with caveat | `ZQ=F` is lagged and reported as a FedWatch-like free baseline (`K1360.py:475-510`, `K1360.py:537-540`), but not full CME FedWatch probability history. |
| Formal tests | PASS | Newey-West HAC regression is implemented with lag 5 (`K1360.py:549-628`); top-quintile and event-study diagnostics are secondary. |
| Randomness | PASS | `SEED = 42` and deterministic API caches are used (`K1360.py:49`, `data/raw/`). |
| Claim strength | PASS | Verdict requires t>=3 plus cross-market replication for support; actual result has no Kalshi t>=3 target (`K1360.py:745-784`). README forbids robust forecast claims. |

## Numeric Cross-Check

Headline rerun output:

```json
{
  "experiment_id": "K1360",
  "verdict": "WEAK_KALSHI_DIAGNOSTIC_UNDERPOWERED",
  "period": ["2025-09-03", "2026-06-18"],
  "n_market_trading_days": 200,
  "selected_kalshi_events": 32,
  "selected_kalshi_markets": 186,
  "polymarket_blocked": true,
  "kalshi_t_ge_3_targets": [],
  "kalshi_t_ge_2_targets": ["spy_rv5_forward"]
}
```

Primary HAC t-stats for the Kalshi lagged shock:

| Target | HAC t |
|---|---:|
| SPY 1d absolute return | +1.71 |
| SPY 5d forward RV | +2.12 |
| SPY left-tail loss | +0.32 |
| `log(VIX9D/VIX)` change | -2.25 |
| VIX log change | -1.86 |
| VIX9D log change | -2.22 |

The only positive volatility target above `t>=2` is SPY 5d forward RV. It does not pass the Harvey-style `t>=3` discovery threshold, and Polymarket replication is unavailable in this environment.

## Caveats

- `CONDITIONAL_PASS`, not full PASS, because Polymarket is blocked/unusable and the cross-market replication requirement is not met.
- `ZQ=F` is a reasonable free Fed funds futures proxy, but it is not the CME FedWatch meeting-probability API.
- Event-day realized sample has only 10 rows, so event-day tail-move diagnostics are underpowered.
- Kalshi daily candles are end-of-day aggregates; the one-calendar-day lag is conservative, but no intraday close alignment is attempted.

## Required Interpretation

Allowed:

> Kalshi public API can build lagged macro-event probability shocks. In this 2025-09 to 2026-06 pilot, there is only weak diagnostic evidence for SPY 5-day forward RV, with no t>=3 support and no Polymarket replication.

Not allowed:

> Prediction-market shocks robustly forecast equity volatility.

Not allowed:

> Kalshi beats FedWatch.
