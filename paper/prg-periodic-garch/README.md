# Paper 6: Periodic Realized GARCH — Session-Boundary Information Transfers

**Target Journal**: Finance Research Letters (FRL)
**Status**: ✅ Near submission-ready (R2 SEVERE=0)
**Pages**: 14 | **Citations**: 19

## Data Sources
- TAIFEX TX tick: ~/Dropbox/TAIFEXDATA/ (volume-based contract selection)
- SPY, QQQ, GLD, EEM, 0050.TW: yfinance
- OOS periods vary by market (2018-2026)

## Reproduction
```bash
uv run python paper/prg-periodic-garch/reproduce.py [--quick]
```

## Key Experiments
| File | Market | Result |
|------|--------|--------|
| k880_prg_spy_validation.py | SPY | DM t=6.00 PASS |
| k881_prg_multi_asset.py | QQQ/GLD/EEM | All Harvey PASS |
| k886_prg_0050tw.py | 0050.TW | DM t=5.27 PASS |
| k874d_fair_comparison.py | TAIFEX | DM t=5.10 PASS |

## Important Note
Using realized overnight return for intraday prediction is NOT lookahead.
Sessions complete sequentially: overnight ends → intraday starts.
