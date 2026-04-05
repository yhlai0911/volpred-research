# Paper 2: Volatility Targeting in Taiwan — Leverage Amplification and Timezone Transmission

**Target Journal**: Pacific-Basin Finance Journal
**Status**: R1 review — 6 SEVERE, needs revision
**Pages**: 60 | **Citations**: 34

## Data Sources
- 0050.TW, TWII, TSMC, 9 TW stocks: yfinance (clean_tw50_data required)
- TAIFEX TX tick: ~/Dropbox/TAIFEXDATA/
- VIX: yfinance

## Reproduction
```bash
uv run python paper/taiwan-vt/reproduce.py
```

## Known Issues
- S1: Missing ES analysis → K896 provides data
- S2-S4: Gamma conflicts → K892 provides correct values
- S5: VT performance tables need JSON
- S6: SSVS PIP conflict needs investigation
- Section 5 (high-frequency) ~95% verified
