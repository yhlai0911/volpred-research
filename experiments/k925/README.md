# K925: CPI Announcement Volatility Event Study -- SPY

## Problem
How does SPY volatility behave around CPI announcement days? Does the CPI surprise direction matter? Should investors adjust portfolios ahead of CPI?

## Motivation
- CPI 04/10 (2026) upcoming -- need event-driven article
- K513 found CPI day |ret| ratio = 1.03x (NS p=0.758) in broad macro event study
- K773 found CPI date approximation was a bug (used 13th+weekend adj, not actual release)
- K856 found Fed DiD/RDD NULL -- but CPI is data surprise, not policy decision
- K801 found VIX shock guard NULL
- This experiment goes DEEPER on CPI specifically: surprise proxy, inflation regime, 12/VIX auto-adaptation

## Key Prior Results
- **K513**: CPI 1.03x (NS), FOMC 1.28x (sig), NFP 1.09x (NS). Half-weight strategy hurts Sharpe -0.072
- **K773**: CPI dates were approximate -- this experiment uses BLS official release dates
- **K801**: DVIX shock overlay NULL

## Method
1. **BLS Official CPI Release Dates** (not approximation): scrape from FRED CPIAUCSL release dates or use known schedule
2. **CPI Surprise Proxy**: deviation of actual CPI MoM from 3-month MA trend (no consensus data available)
3. **Event Window [-5,+5]**: SPY |return|, VIX level, VIX change around CPI days
4. **High-Inflation (2021-2023) vs Low-Inflation (2015-2020)** regime comparison
5. **12/VIX Auto-Adaptation**: does 12/VIX strategy automatically de-risk before CPI?
6. **Bootstrap CI** for CPI day vol ratio (1000 reps, seed=42)
7. **Visualization**: event window plots, CPI vs non-CPI comparison

## Data
- SPY daily prices: yfinance (2015-01 to 2026-03)
- VIX: yfinance ^VIX
- CPI data: FRED CPIAUCSL (monthly, for surprise proxy)
- CPI release dates: manually compiled from BLS schedule

## Expected Results
- CPI day |return| likely close to normal (consistent with K513)
- VIX may show mild pre-CPI increase (uncertainty premium)
- High-inflation era may show stronger CPI effect
- 12/VIX likely auto-adapts (VIX rise -> weight drop)
- Regardless of result direction, valuable for CPI article

## Limitations
- No consensus forecast data -- CPI surprise is proxy (deviation from trend)
- Daily frequency only (no intraday 8:30 ET analysis)
- BLS release dates may have ~1 day uncertainty in older periods
