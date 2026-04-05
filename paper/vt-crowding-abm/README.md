# Paper 5: When Volatility Targeting Crowds — Quantifying the Tipping Point via ABM

**Target Journal**: Finance Research Letters (FRL)
**Status**: ✅ Submission-ready (R3 SEVERE=0)
**Pages**: 15 | **Citations**: 13

## Data Sources
- Agent-based simulation (no external data needed)
- K827v3: Fixed liquidity ABM with 9 OAT parameter variations

## Reproduction
```bash
uv run python paper/vt-crowding-abm/reproduce.py
```

## Key Results
- Tipping point: 50-70% VT adoption
- 10-20% adoption: safe (Sharpe ~0.50)
- 50%+: collapse (Sharpe negative, flash crashes)
