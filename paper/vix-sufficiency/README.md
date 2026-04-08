# Paper 7: Can Anything Beat VIX? A Systematic Out-of-Sample Evaluation

**Target Journal**: Journal of Forecasting
**Status**: ✅ Near submission-ready (R2 SEVERE=0)
**Pages**: 39 | **Citations**: 40

## Data Sources
- SPY, VIX, VIX3M, VIX9D: yfinance
- Various signal families: yfinance + FRED
- OOS: 2008-2026 (8,325 trading days)

## Reproduction
```bash
uv run python paper/vix-sufficiency/reproduce.py
```

## Key Finding
30+ VIX sufficiency tests: no signal passes Harvey |t|>3.0 in full sample.
Era-specific exceptions: GFC (3 signals pass), COVID (1 signal passes).

## Experiments (22 files)
Core: K730 (cross-asset), K731 (term structure), K732 (sentiment),
K752 (era stability), K799 (QLIKE), K824v2 (VaR)
