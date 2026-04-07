# K984: SPY→0050.TW Lead-Lag Trading Strategy

## Problem
K983 discovered a strong SPY→0050.TW lead-lag relationship (correlation = 0.40, OOS R² = 15.9%). Can this statistical finding be converted into a profitable trading strategy after Taiwan's high transaction costs (~0.585% round trip)?

## Motivation
- Cross-market lead-lag is one of the best-documented phenomena in international finance
- SPY closes ~4:00 PM ET, TW50 opens ~9:00 AM next day Taiwan time → natural information lag
- K983 showed SPY large moves predict TW50 next-day direction with high accuracy
- Question: does predictability survive transaction costs?

## Method

### Data
- **Source**: yfinance (SPY, 0050.TW, ^VIX)
- **Period**: 2010-01-05 to 2026-04-02 (3,970 aligned trading days)
- **IS/OOS Split**: IS = 2010-2018 (2,214 days), OOS = 2019-2026 (1,756 days)
- **0050.TW split fix**: `clean_tw50_data()` applied for 2014 split artifact

### Strategies Tested
1. **Binary Signal**: SPY up → w=1.0 (hold TW50), SPY down → w=0.0 (cash)
2. **Proportional Signal**: w = clip(0.5 + 26.6 × SPY_return, 0, 1.5)
3. **Threshold Signal**: 4-tier (SPY>+1%: w=1.2, >0%: w=1.0, >-1%: w=0.5, <-1%: w=0.0)
4. **VT + Lead-Lag Overlay**: 8.63/VIX base × (1 + 0.5 × sign(SPY_return))

### Benchmarks
- Buy & Hold 0050.TW
- VT Only (8.63/VIX) — existing Taiwan VT strategy

### Controls
- **Lag**: `signal.shift(1)` — yesterday's SPY return determines today's TW50 weight
- **Transaction costs**: 0.585% round trip, triggered when weight change > 10%
- **Seed**: np.random.seed(42)

## Results

### OOS Performance (2019-2026)

| Strategy | Sharpe | Ann. Return | MDD | Turnover |
|----------|--------|-------------|-----|----------|
| Buy & Hold TW50 | **1.208** | 13.6% | -33.8% | 0.0 |
| VT Only (8.63/VIX) | **1.710** | 10.8% | -13.5% | 6.6 |
| Binary Signal | -0.139 | -1.3% | -97.8% | 122.6 |
| Proportional Signal | 0.782 | 8.4% | -53.0% | 63.3 |
| Threshold Signal | 0.655 | 7.0% | -83.8% | 94.6 |
| VT + Lead-Lag | 0.534 | 5.0% | -85.0% | 69.2 |

### Key Findings

1. **NULL RESULT**: No lead-lag strategy beats Buy & Hold or VT Only in OOS period
2. **Transaction costs destroy alpha**: Binary signal has 1,931 trades → costs obliterate any directional accuracy
3. **VT overlay hurts, not helps**: Adding lead-lag overlay to VT reduces OOS Sharpe from 1.710 to 0.534 — a -1.176 degradation
4. **Turnover is the killer**: Strategies with turnover > 60 all underperform. VT Only has turnover of 6.6 — 10-20x less
5. **Only Proportional shows marginal promise**: Sharpe 0.782 in OOS, but still far below B&H (1.208)
6. **Stability poor**: All lead-lag strategies beat B&H in only 3/8 OOS years

## Conclusion

**The SPY→TW50 lead-lag is statistically real (K983) but NOT economically exploitable.** Taiwan's high transaction costs (~0.585% round trip) destroy the alpha from daily signal-based trading. The lead-lag signal changes too frequently (daily), generating excessive turnover.

The existing VT strategy (8.63/VIX) remains superior because:
- Smooth weight changes → low turnover (6.6 vs 69-123)
- Only 78 trades in 16 years vs 1,900-2,700 for lead-lag strategies
- This confirms the project's core finding: **smooth-weight strategies dominate discrete-signal strategies in high-cost markets**

### Implications
- Lead-lag could potentially work in lower-cost markets (US equities ~0.01% cost)
- Or with lower-frequency signals (weekly/monthly instead of daily)
- But for Taiwan 0050.TW with ~0.585% costs, daily lead-lag trading is not viable

## Files
- `k984_leadlag_strategy.py` — Main experiment script
- `k984_leadlag_strategy_results.json` — Full results with annual breakdown
- `k984_cumulative_returns.png` — Cumulative return comparison
- `k984_annual_returns.png` — Annual return heatmap
- `k984_drawdowns.png` — Drawdown comparison
