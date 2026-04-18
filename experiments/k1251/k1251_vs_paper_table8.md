# K1251 vs Paper 8 Table 8 — allclose per cell

- Sample: 2006-01-04 -> 2026-03-30 (5090 days)
- Seed: 42
- Formula verbatim from `paper/volatility-absorption/main_v2.tex` lines 472-497.
- Primary RV window: 22-day (matches K720 / Section 3.7).

## Paper Table 8 (canonical)

| Regime | Avg Shock Loss (%) | Daily Hedge Cost (%) | CB Ratio |
|--------|-------------------|---------------------|----------|
| Calm | 1.18 | 0.086 | 13.7 |
| Elevated | 1.56 | 0.196 | 8.0 |
| High | 2.61 | 0.725 | 3.6 |

## K1251 reconstruction (RV=22, raw VRP as hedge cost)

| Regime | Days | Shock Days | Avg Shock Loss (%) | Daily Hedge Cost raw (%) | Daily Hedge Cost clipped (%) | CB Ratio raw | CB Ratio clipped |
|--------|------|-----------|-------------------|-------------------------|------------------------------|--------------|------------------|
| Calm | 1735 | 33 | 1.2138 | 0.6208 | 0.6208 | 1.9553 | 1.9553 |
| Elevated | 2454 | 357 | 1.5497 | 1.3876 | 1.3876 | 1.1168 | 1.1168 |
| High | 880 | 376 | 2.6276 | 4.5859 | 4.5859 | 0.573 | 0.573 |

## Allclose verdict per cell (rtol=0.05 vs paper, RV=22 raw VRP)

| Regime | Shock Loss | Hedge Cost | CB Ratio |
|--------|-----------|-----------|----------|
| Calm | 1.2138 vs 1.18 (2.87%) YES | 0.6208 vs 0.086 (621.85%) NO | 1.9553 vs 13.7 (85.73%) NO |
| Elevated | 1.5497 vs 1.56 (0.66%) YES | 1.3876 vs 0.196 (607.96%) NO | 1.1168 vs 8.0 (86.04%) NO |
| High | 2.6276 vs 2.61 (0.67%) YES | 4.5859 vs 0.725 (532.53%) NO | 0.573 vs 3.6 (84.08%) NO |

## Summary

- RV=22 raw VRP   : 3/9 cells within 5% of paper
- RV=22 clipped VRP: 3/9 cells within 5% of paper
- RV=20 raw VRP   : 3/9 cells within 5% of paper

## Interpretation

- A YES verdict in the CB Ratio column is what ultimately drives paper Table 8 reproduce_report.
- If hedge-cost cells diverge but CB ratios match, the divergence is likely a formula variant
  (raw vs clipped VRP, or a different RV window). 三方一致 rule requires explicit disclosure.
- If CB ratios diverge substantially, the paper owner should consider K1231 option (a) data-
  vintage alignment for SPY/VIX (same fix that helps K716/K718), or option (c) errata.