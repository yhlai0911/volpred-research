# K927: Macro Regime Detection — Can Macro Variables Predict VIX Regime Changes?

## Research Question
VIX exhibits clear regime structure (calm <15, normal 15-25, high >25). Can macroeconomic variables predict transitions between regimes, particularly escalation from calm to elevated volatility?

## Related Work (Knowledge Base)
- **K278**: VIX regime transition — escalation 3-4x faster than de-escalation; 50% crisis ≤2 days
- **K259**: Macro Surprise — VIX absorbs macro information
- **K504**: STLFSI4 macro stress regime — NULL (no improvement over 12/VIX)
- **K526**: GARCH-MIDAS — OOS didn't beat GJR but regime transition advantage
- **K752**: VIX era-dependent R² (0.24-0.64)
- **K912**: MF-GJR strongest in low VIX regime
- **K856**: Fed DiD/RDD NULL (Fed doesn't cause regime shift)

## Literature
- Hamilton (1989): Markov regime-switching models
- Moreira & Muir (2017): Volatility-managed portfolios
- Estrella & Mishkin (1998): Yield curve as recession predictor
- Adrian, Boyarchenko & Giannone (2019): Vulnerable growth (NFCI predicts downside risk)

## Method
1. VIX regime classification: calm(<15), normal(15-25), high(>25)
2. Macro variables from FRED: term spread (GS10-GS2), credit spread (BAA10Y), NFCI, initial claims (ICSA)
3. Probit model: P(regime_up_{t+h}) = Φ(Xβ), h = 5, 10, 22 days
4. OOS: IS 2006-2018, OOS 2019-2026
5. Metrics: AUC, precision/recall, Brier score
6. Incremental test: macro on top of VIX level

## Error Log Rules Applied
- Fixed seed: np.random.seed(42)
- signal.shift(h) for no lookahead
- Harvey (2016) |t| > 3.0 for significance
- Null result reported honestly

## Data Sources
- yfinance: ^VIX (daily)
- FRED: GS10, GS2, BAA10Y, NFCI, ICSA (various frequencies, forward-filled to daily)
- Period: 2006-01-03 to 2026-03-30 (5091 obs)

## Key Results

### VIX Regime Distribution (2006-2026)
- Calm (VIX<15): 34.5%, Normal (15-25): 48.2%, High (>25): 17.3%
- 471 total transitions, 236 escalations, 234 de-escalations

### OOS Probit AUC (IS: 2006-2018, OOS: 2019-2026)
| Model      | h=5d   | h=10d  | h=22d  |
|------------|--------|--------|--------|
| Macro only | 0.5443 | 0.5458 | 0.5600 |
| VIX only   | 0.6039 | 0.6376 | 0.6887 |
| VIX+Macro  | 0.5822 | 0.6106 | 0.6597 |
| Delta      | -0.022 | -0.027 | -0.029 |

### Lead-Lag Analysis
All macro variables LAG VIX regime changes (9-20 days behind), not lead.

### Partial Correlations (conditional on VIX)
NFCI has the largest partial r (-0.33), but the sign flips — suggesting suppression, not true incremental info.

## Conclusion
**MIXED, leaning NULL for practical purposes.** Macro variables are statistically significant IS (LR tests p<0.05) but do NOT improve OOS prediction beyond VIX alone. All macro variables LAG VIX regime changes rather than lead them. Adding macro variables to VIX actually HURTS OOS AUC by 2-3%. This is consistent with K259 (VIX absorbs macro) and K504 (STLFSI4 null). VIX is a faster, more efficient aggregator of macro risk than individual macro indicators.

**Nuance**: Rolling IS AUC shows macro > VIX in 71% of windows, suggesting macro has genuine signal that doesn't survive the IS/OOS boundary — classic overfitting of slow-moving macro variables.
