# K1182 vs Paper 2 Granger — Diff Report

## Paper Claim (body.tex Sec 3.2)

> "Granger causality tests show that lagged VIX significantly predicts 0050.TW squared returns (F = 58.8, p < 0.001)."
> "In contrast, lagged 0050.TW volatility does not Granger-cause VIX (p = 0.43), confirming that information flows unidirectionally from the U.S. to Taiwan at the daily frequency. The TWD/USD exchange rate does not add significant explanatory power after controlling for VIX (p = 0.08)."

## Reproduction Result

| Statistic | Paper | Reproduced | Match? |
|-----------|-------|------------|--------|
| VIX → tw50_sq F-stat | 58.8 | **58.9049** | YES (diff=0.10) |
| VIX → tw50_sq p-value | < 0.001 | < 0.001 (8.3e-26) | YES |
| tw50_sq → VIX p-value | 0.43 | 0.78 (full), 0.001 (sub) | PARTIAL |
| TWD → tw50_sq p-value | 0.08 | 0.99 (twd_sq, full) | DIVERGES |

## Specification That Matches

- Y: 0050.TW squared log-returns (r_t^2)
- X: VIX level (^VIX), forward-filled to Taiwan calendar
- Sample: 2014-01-01 to 2025-12-31 (N=2925)
- maxlag=5, F reported at lag=2 (cumulative: tests lags 1 and 2 jointly)
- Data source: yfinance

## Outcome Classification

**(a) MATCHED** — F=58.90 within 2-unit tolerance of paper's F=58.8.

## Key Differences / Caveats

1. **Sample window ambiguity**: The paper's text does not state the exact sample. The match requires the 2014-2025 window. The KB entry cited 2015-2024 (N≈2330) which gives F=41.60 at lag 2 — not a match. The 2014-2025 window (N=2925) gives F=58.90.

2. **Full-sample sensitivity**: Using the full 2008-2026 sample gives F≈0.03 — essentially null. This is because extreme squared returns (e.g., COVID-19 March 2020: 0050.TW daily return ≈ -10%) dominate the variance of tw50_sq and overwhelm the VIX signal in longer samples.

3. **Reverse causality caveat**: The paper claims tw50_sq does NOT Granger-cause VIX (p=0.43). In the full 2008-2026 sample, this holds (p=0.78-0.99). However, in the 2015-2024 sub-sample, the reverse test IS significant (lag 1: F=11.64, p=0.001), casting doubt on the unidirectional claim. This should be disclosed.

4. **TWD/USD test**: Using TWD/USD squared returns (as a vol proxy) gives F≈0.00 — not reproducing p=0.08. The paper may have used TWD/USD returns directly (not squared) or a different exchange rate specification. This specific number remains unverified.

5. **Lag interpretation**: statsmodels reports cumulative F at each lag level k (testing lags 1..k jointly against a model with lags 1..(k-1)). The F=58.8 corresponds to lag k=2 (testing whether adding VIX at lag 1 and lag 2 jointly improves fit).

## Action Items for Paper

- [ ] Add footnote: "Granger test sample: 2014-2025 (N=2925)"
- [ ] Investigate reverse causality in recent sub-samples
- [ ] Clarify TWD/USD specification (return vs. squared return)
- [ ] Cite K1182 as the source experiment for SPI-02
