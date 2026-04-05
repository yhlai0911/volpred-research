# Paper 1: Leverage Direction Matters — Asymmetric Volatility and the Cross-Section of VT Alpha

**Target Journal**: Journal of Banking and Finance (JBF)
**Status**: R1 review — 5 CRITICAL, needs revision
**Pages**: 62 | **Citations**: 54

## Data Sources
- SPY, QQQ, GLD, TLT, EEM, BTC-USD, IWM, SLV: yfinance
- VIX: yfinance (^VIX)

## Reproduction
```bash
uv run python paper/leverage-direction/reproduce.py
```

## Known Issues (from R1)
- C1: HM gamma internal contradiction (Sec 4.7 vs Sec 5.4)
- C2: Kupiec p-values aggressively rounded (0.67→0.60)
- C3: Table 5 cherry-picks from 3 experiments — K899 unified VaR pending
- C4-C5: Tables 1, 3 partially untraceable
- Paper needs shortening to ~45 pages for JBF
