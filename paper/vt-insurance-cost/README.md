# Paper 4: The True Cost of Volatility Targeting — Insurance Premium Decomposition

**Target Journal**: Finance Research Letters (FRL)
**Status**: ✅ Submission-ready (R3 SEVERE=0)
**Pages**: 14 | **Citations**: 17

## Data Sources
- SPY, GLD: yfinance (2005-2026)
- VIX: yfinance (^VIX)
- OOS: 2023-01-01 to 2024-12-31

## Reproduction
```bash
uv run python paper/vt-insurance-cost/reproduce.py
```

## Experiment Files
| File | Description |
|------|-------------|
| k811v2_threshold_0.5.py | Insurance cost decomposition (main) |
| k811v2_sensitivity_*.json | Sensitivity analysis results |

## Number Traceability
See `reviews/audit_step1_2.md` for complete traceability table.
All numbers verified — 0 mismatches.
