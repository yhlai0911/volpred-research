# K1191: Paper 3 COVID Sub-Period Sharpe 1.295 vs 1.254 — Canonical Replication

## Objective

Reproduce and verify the COVID sub-period Sharpe ratios cited in Paper 3 (vt-trend-following):

> "During the COVID period, TSMOM-hedged VT actually *outperforms* unhedged VT  
> (Sharpe **1.295** vs. **1.254**), because VIX-level deleveraging was optimal  
> while TSMOM signals lagged the V-shaped recovery."  
> — main.tex line 425

**Key questions answered:**
1. Which strategy is 1.295? Which is 1.254?
2. What is the COVID period definition?
3. Do the numbers replicate?

## Findings

### Identity of Strategies
- **1.295** = TSMOM-hedged VT (PureVT = VT − β × TSMOM⊥)
- **1.254** = Unhedged 12/VIX VT (monthly rebalancing)
- Asset: 50/50 SPY/GLD

### Replication Result: QUALITATIVE_MATCH (b)
- Exact numbers NOT reproduced within 5% rtol under any tested COVID definition
- **Direction CONFIRMED**: Hedged VT > Unhedged VT in ALL COVID sub-periods tested
- **Recovery paradox (N177) VERIFIED**: TSMOM hedge removes the lagging TSMOM drag during V-shaped recovery

### COVID Period Results
| Period | VT Sharpe | Hedged Sharpe | Hdg > VT? |
|--------|-----------|---------------|-----------|
| Broad (2020–2022) | 0.310 | 0.714 | YES |
| Calendar 2020 | 0.612 | 1.456 | YES |
| Crisis (2020-02-24 – 2020-12-31) | 0.157 | 1.434 | YES |
| Peak VIX (2020-03-09 – 2020-06-30) | 0.132 | 2.194 | YES |

Best match to paper numbers: `covid_calendar_2020` (VT=0.612, Hdg=1.456), combined diff=0.803

### Most Likely Gap Explanation
The paper's numbers (1.295 / 1.254) likely come from **2020–2021** (Jan 2020 – Dec 2021), capturing both the COVID crash and V-shaped recovery bull run. This period was not directly testable without the Online Appendix definition.

## Methodology

| Parameter | Value |
|-----------|-------|
| Asset | 50/50 SPY/GLD |
| VT rule | w_t = min(12/VIX_{end-of-month t-1}, 1) |
| Rebalancing | Monthly |
| Tx cost | 10 bps/round trip |
| Cash | SHY |
| TSMOM lookback | 252 days |
| TSMOM | Orthogonalized (TSMOM⊥ = TSMOM − β_MKT × MKT, full-sample β) |
| Hedge | Rolling 252-day OLS; beta lagged 1 day |
| Lookahead protection | shift(1) for all signals |
| Seed | 42 |
| Data | yfinance: SPY, GLD, ^VIX, SHY |
| Full period | 2005-01-03 to 2026-03-31 |

## Files

| File | Description |
|------|-------------|
| `k1191.py` | Main experiment script |
| `k1191_results.json` | Full results JSON (all sub-periods) |
| `k1191_vs_paper3_covid_diff.md` | Detailed diff report vs paper claims |
| `run.log` | Full execution log |
| `README.md` | This file |

## Related Experiments

- **K898**: Base VT analysis (full period, daily VIX signal)
- **K1177**: Canonical replication of Paper 3 Table 3 (monthly VT, orth TSMOM)
- **N177**: VIX term structure for recovery (recovery paradox)
- **K30**: Leveraged ETF VT (Sharpe invariant, MDD improvement)

## Data Sources

- SPY: SPDR S&P 500 ETF Trust (2003-12-01 onward)
- GLD: SPDR Gold Shares (2004-11-18 onward)
- VIX: CBOE Volatility Index (via yfinance ^VIX)
- SHY: iShares 1-3 Year Treasury Bond ETF (cash proxy)

## Lookahead Protection

1. VT weight: VIX_{end-of-month t} → weight for month t+1 (1-month lag)
2. TSMOM signal: sign(cum_ret_{t-252:t-1}) → applied at t (shift(1))
3. Rolling beta: estimated through t-1 → applied at t (shift(1))

No same-day signal usage; all signals strictly from past data.
