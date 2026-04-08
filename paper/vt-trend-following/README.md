# Paper 3: Is Volatility Targeting Just Trend Following?

**Target Journal**: Journal of Portfolio Management / Financial Analysts Journal
**Status**: R1 review — 7 HIGH, needs revision
**Pages**: 33 | **Citations**: 18

## Data Sources
- SPY, GLD, DIA, QQQ, IWM, 13 intl markets: yfinance

## Reproduction
```bash
uv run python paper/vt-trend-following/reproduce.py
```

## Known Issues
- A.1: Table 3 → K898 provides verified data
- A.2-A.3: Tables 5 (13 markets) and 6 (bootstrap) need new experiments
- B.1: "1.4%" TSMOM contribution is misleading average
- Tables 1/2/4 fully verified (81% overall match)
