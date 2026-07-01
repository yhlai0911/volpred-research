# Codex Review - K1599 Daily Co-Jump Proxy and HAR-CJ-Style Forecast Test

verdict: CONDITIONAL_PASS

## Findings

| Severity | Location | Issue | Fix / Status |
|---|---|---|---|
| MED | `k1599.py` | Uses daily close-to-close returns and a BNS-style daily scale, not synchronized high-frequency RV/BPV. | Scope is explicit; result is labeled `SUPPORTED_DAILY_PROXY`, not HAR-CJ replication. |
| MED | `k1599.py` | Fixed jump threshold 2.5 may affect co-jump frequency and forecast gains. | Listed as a limitation; paper-level use requires threshold sensitivity and 5-minute data. |
| LOW | `k1599.py` | Annual-refit log-OLS nested models can benefit from extra features in a broad stress regime. | OOS DM/Holm is applied; interpretation stays at feature usefulness, not structural causality. |
| LOW | `k1599_results.json` | Target is squared daily returns, a noisy volatility proxy. | QLIKE is appropriate for noisy variance proxies, but intraday RV follow-up is required. |

## Checks

- Data provenance: uses frozen local `experiments/k1552/data/prices.parquet`; no live download.
- Lookahead control: jump flags for date `t` use return `t`, but all jump/co-jump features are shifted before forecasting date `t+1`; HAR features use lagged log-r2.
- K1303 guardrail: method is not presented as full HAR-CJ; it uses a bipower-style proxy and keeps conclusion below paper-grade high-frequency evidence.
- Metric orientation: QLIKE uses `actual / forecast - log(actual / forecast) - 1` via repo helpers.
- Inference: per-asset paired DM/HAC uses `h=1`; Holm correction is applied across 36 pair tests; Harvey |t| > 3 required for strict wins.
- Artifact completeness: script, README, JSON results, compressed OOS forecast CSV, figure, review, and knowledge handoff are present.

## Result Integrity

Core JSON checks:

- `verdict = SUPPORTED_DAILY_PROXY`
- mean QLIKE: `HAR_CJ_proxy = 2.2489`, `HAR_J_proxy = 2.2638`, `HAR_daily = 2.2915`
- best model by asset: `HAR_CJ_proxy` for all 12 ETFs
- strict HAR-CJ wins: 18
- strict HAR-CJ losses: 0
- co-jump stress diagnostic: next-day market r2 high-minus-low diff = 0.000289, Welch t = 3.07, p = 0.00239
- next-day mean absolute return high-minus-low diff = 0.004525, Welch t = 4.60, p = 0.00000668

The positive result is usable as a research lead: co-jump counts appear informative in daily ETF data, but publication-grade claims require high-frequency replication.
