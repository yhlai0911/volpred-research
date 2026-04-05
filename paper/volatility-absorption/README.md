# Paper 8: The Volatility Absorption Hypothesis

**Target Journal**: TBD
**Status**: R1 review — 5 SEVERE, needs major revision
**Pages**: 38 | **Citations**: 37

## Data Sources
- SPY: yfinance
- VIX: yfinance
- NFP dates: manual

## Reproduction
```bash
uv run python paper/volatility-absorption/reproduce.py
```

## Known Issues
- S1: Null simulation → K897 proves absorption is real (not GARCH artifact)
- S2: Table 5 sample-size inconsistency
- S3: Tables 9-10 fully untraceable
- S4: Table 6 NFP discrepancies
- Missing .py scripts for K716-K722
