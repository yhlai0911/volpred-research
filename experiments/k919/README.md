# K919: Diurnal Asymmetric Spillover Network (DASN) -- SPY to Taiwan Transmission Channel

## Problem (Gemini G3-1)
K907 found SPY is a vol transmitter (+34.8%), 0050.TW is a receiver (-18.4%). K906 found SPY overnight accounts for ~50% of total vol. **Does SPY-to-Taiwan volatility transmission occur via overnight gap (opening jump) or intraday follow-through (during session)?**

## Motivation
- K907: SPY -> 0050.TW spillover confirmed (TCI network)
- K906: SPY overnight ~50% total vol
- K847: Overnight gap 61% tradeable (R^2=0.83)
- K848: After-hours vol share 24% -> 57% (2017-2026)
- Academic value: Quantify precise time window of international vol transmission (market microstructure x international contagion)
- Practical value: Should Taiwan investors react before open or during session?

## Method
1. Data: SPY & 0050.TW daily OHLC from yfinance (2012-01 to 2026-03)
2. Decompose returns into overnight (gap) and intraday components
3. Three transmission channels:
   - Channel 1: Gap-to-Gap (SPY ret(T) -> 0050.TW overnight gap(T+1))
   - Channel 2: Intraday Follow-Through (SPY ret(T) -> 0050.TW intraday(T+1))
   - Channel 3: Total Transmission (SPY ret(T) -> 0050.TW total ret(T+1))
4. Variance decomposition of 0050.TW returns attributable to each channel
5. VIX regime dependence (4 quartile regimes)
6. Temporal trend: pre vs post night-session (2017/05)
7. Granger causality tests (bidirectional)

## Data Sources
- yfinance: SPY, 0050.TW, ^VIX (daily OHLC)
- Period: 2012-01 to 2026-03

## Expected Results
- Gap channel should dominate (K847: gap R^2=0.83)
- Intraday channel should be weaker (info already priced in at open)
- High VIX -> stronger gap channel (panic -> larger opening jumps)
- Post night-session -> gap channel may weaken (night session partially absorbs US info)

## References
- K907: International vol spillover network
- K906: SPY overnight vol decomposition
- K847: TAIFEX overnight gap tradability
- K848: Night session vol share trend
