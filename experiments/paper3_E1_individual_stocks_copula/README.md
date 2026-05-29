# Paper3_E1 — Individual Stocks Copula λ_L Threshold Validation

**Boss directive 2026-05-29**: Paper 3 reframe (asset-class-specific copula advantage) 必須擴大驗證範圍。E1 = individual stocks 擴展；E2 = other equity markets；E3 = commodities。Body rewrite 暫停直至 E1/E2/E3 完成。

## Parent / Lineage
- Reuses K1100b machinery (1500-line copula-GARCH framework: A4f marginals, DCC-A4f-ASYM benchmark, Student-t / Clayton copulas, CF-Rolling VaR, Trinity tests, DM QLIKE).
- Modifications vs K1100b: PAIRS replaced with 12 individual-stock pairs; load_data fetches 13 stocks + ^VIX (no GVZ — no stock-specific IV index); data range extended to 2010-01-01 — 2026-05-28; OOS_START=2015-06-01.

## Hypotheses
- **H1** (same-sector NULL): On AAPL-MSFT, GOOGL-META, NVDA-AMD, JPM-BAC, GS-MS, XOM-CVX — λ_L > 0.4 → Copula-GARCH NULL vs DCC-A4f-ASYM (mixing-averaging dominant, replicates K1100b SPY-QQQ pattern at stock level).
- **H2** (cross-sector PASS): On AAPL-XOM, MSFT-JPM, GOOGL-CVX, NVDA-BAC, META-JNJ, AMD-XOM — λ_L < 0.2 → Copula-GARCH significantly beats DCC at Harvey |t| > 3.0 (copula advantage scales with tail-independence).
- **H3** (cross-pair scaling): DM t-stat negatively correlated with mean λ_L across N=12 pairs (R² > 0.4 expected if Paper 3 reframe holds).
- **H4** (validation): Same-sector individual-stock null replicates K1100b ETF-level finding (no degradation moving from ETF to stock universe).

## Design
| | |
|---|---|
| Pairs | 12 (6 same-sector + 6 cross-sector) |
| Models | DCC-A4f-ASYM (benchmark), Copula-t-A4f-ASYM, Copula-Clayton-A4f-ASYM |
| Cells | 12 × 3 = 36 |
| Marginal | A4f with VIX² regressor (canonical systemic equity factor) |
| Data | yfinance 2010-01-01 → 2026-05-28 (4122 days post-merge) |
| OOS | 2015-06-01 onwards (~2700 days/pair), window=1250, refit=63d |
| α levels | 1%, 2.5% |
| Portfolio weights | 50/50 |
| MC paths | 5000/day |
| Seed | 42 |

## Sectors
- **Tech**: AAPL, MSFT, GOOGL, META, NVDA, AMD
- **Fin**: JPM, BAC, GS, MS
- **Energy**: XOM, CVX
- **Healthcare**: JNJ

## Note on META
META IPO 2012-05-18 → in-sample window length is shorter for META pairs (GOOGL-META, META-JNJ). evaluate_pair() drops NaN per-pair, so these pairs use META's actual valid range. Bootstrap inference will reflect smaller effective sample.

## Runtime
- K1100b: 5 pairs ≈ 28 min.
- E1: 12 pairs ≈ 67 min (no SPY-style marginal-sharing economy — each pair has independent marginals).
- Boss directive 4-6 hr estimate covers any pooled-MLE / bootstrap follow-up.

## Execution
```bash
uv run python experiments/paper3_E1_individual_stocks_copula/paper3_E1.py
```

Or queued via compute_queue (recommended — hourly fire cannot host 67-min compute):
```bash
uv run python scripts/compute_queue.py enqueue \
  --script experiments/paper3_E1_individual_stocks_copula/paper3_E1.py \
  --title "Paper3_E1 — Individual stocks copula λ_L threshold" \
  --result-artifact experiments/paper3_E1_individual_stocks_copula/paper3_E1_results.json \
  --followup-brief "Read paper3_E1_results.json — verify H1 (same-sector NULL), H2 (cross-sector PASS), H3 (DM-vs-λ_L correlation), H4 (K1100b replication). Write knowledge.json entry with PASS/CONDITIONAL_PASS/FAIL verdict + Codex review. Decision: enqueue E2/E3 or revise PAIRS if anomalies." \
  --followup-task-type paper_review \
  --timeout 14400
```

## Output Files
- `paper3_E1_results.json` — per-pair λ_L, DM t-stat, Trinity, FZ, cross-pair scatter.
- `paper3_E1_tail_dependence_by_pair.png` — λ_L distribution per pair.
- `paper3_E1_dm_vs_lambdaL.png` — H3 scatter (DM t vs mean λ_L).
- `paper3_E1_fz_heatmap.png` — FZ scores by pair × model.
- `run.log` — execution log.

## Honesty Notes
- Lookahead: K1100b code uses rolling refit with strict t-1 information set — inherited unchanged.
- Seed fixed (42) across numpy + MC paths.
- Power: 12 pairs is small for cross-pair regression (H3); H3 R² interpretation requires bootstrap CI.
- Sector classification is GICS-based but not formally re-verified — meta-classification reference: standard SP500 sector tags.

## References
- K1100b (2026-04-13) — ETF-level asset-class copula advantage.
- K1100/K1100b/K1142/K1172 — Paper 3 reframe foundation.
- Patton (2006) IER 47(2) — modelling asymmetric dependence.
- Christoffersen, Errunza, Langlois & Huang (2012) RFS — int'l copula tail.
- Ang & Chen (2002) JFE — asymmetric equity-pair correlation.
- K1216c (2026-05) — pooled-MLE multistart methodology.
- Lai (2024) APFM 31(2) — PRS copula baseline.
