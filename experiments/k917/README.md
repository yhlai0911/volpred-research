# K917: Taiwan Ex-Dividend Season Volatility Effect

## Research Question
Does the Taiwan ex-dividend season (June-August) exhibit systematically higher volatility for 0050.TW and 0056.TW? Can this seasonal pattern be exploited or does VIX absorb the effect?

## Motivation
- Taiwan's ex-dividend season (6-8 月) is a structural market event with concentrated dividend distributions
- 0050.TW component stocks have dense ex-dividend activity in this period
- High-dividend ETFs (0056/00878/00919) have even more concentrated ex-dividend dates
- Practical question: should investors adjust positions around ex-dividend season?
- Preparation for 2026 June-August ex-dividend season

## Methodology
1. Monthly realized volatility analysis (2006-2026 for 0050.TW, 2008-2026 for 0056.TW)
2. Ex-dividend day event study ([-10, +10] trading day window)
3. Dividend-fill analysis (days to recover ex-dividend price gap)
4. VIX control regression: vol_t = α + β₁×D_summer + β₂×VIX_t + ε
5. Statistical tests: t-test, Wilcoxon rank-sum, Kruskal-Wallis

## Data Sources
- yfinance: 0050.TW, 0056.TW daily prices + dividends
- yfinance: ^VIX daily close
- volpred.utils.clean_tw50_data for 0050.TW split adjustment

## Error Log Rules Applied
- 0050.TW: must use clean_tw50_data
- Fixed seed: np.random.seed(42)
- All statistical tests use standard implementations

## Results

### Core Finding: NULL RESULT
- **No significant ex-dividend season volatility effect** for 0050.TW
- Summer (Jun-Aug) mean RV = 0.1691, Other months = 0.1846
- Welch's t-test: t=-1.033, p=0.3028 (NOT significant)
- Mann-Whitney U: p=0.7681 (NOT significant)
- Kruskal-Wallis (all 12 months): H=7.90, p=0.7220 (NOT significant)
- Cohen's d = -0.12 (negligible effect size)
- Permutation test (5000 reps): p=0.489

### VIX Sufficiency Confirmed
- Without VIX: summer dummy beta=-0.016, t=-1.035, p=0.30, R²=0.003
- With VIX: summer dummy beta=-0.001, t=-0.103, p=0.92, R²=0.438
- VIX beta=0.012, t=4.42, p<0.0001 — VIX explains 44% of monthly vol variation
- Summer effect completely absorbed by VIX

### Event Study (24 ex-dividend events)
- Vol before ex-div (10d): 0.148, after: 0.172 — slight increase but NOT significant (t=-1.42, p=0.17)
- Fill gap: median 0 days, mean 6.2 days, 87.5% fill within 5 days
- Ex-dividend day mean return: +0.597% (positive, suggesting price typically recovers quickly)

### Year-by-Year Consistency
- Summer vol higher in only 9/17 years (52.9%) — essentially coin flip

### 0056.TW (High-Dividend ETF)
- No seasonal effect either (t=0.087, p=0.931, Cohen's d=0.012)

### Practical Implication
- Investors do NOT need to adjust VT strategy parameters for ex-dividend season
- VIX already captures any seasonal volatility changes
- 8.63/VIX strategy naturally adjusts — no seasonal override needed

## Output Files
- `k917_taiwan_ex_dividend_vol.py` — experiment script
- `k917_taiwan_ex_dividend_vol_results.json` — full results
- `k917_monthly_vol.png` — monthly volatility box plot
- `k917_event_study.png` — event study CAR + fill gap distribution

## References
- Lakonishok & Vermaelen (1986): Tax-induced trading around ex-dividend days, JFE
- Taiwan dividend tax reform literature
