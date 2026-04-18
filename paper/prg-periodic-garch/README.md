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

## Self-Contained Index (2026-04-17)

| File | Status |
|------|--------|
| `data_sources.md` | ✅ Data sources and storage paths |
| `scripts/README.md` | ✅ Reproduction guide for all experiments |
| `results/README.md` | ✅ Table/figure → JSON source mapping |
| `figures/` | ✅ Soft-links: k880_charts + k881_charts PNGs |
| `experiments.md` | ✅ Full K-number index (K874c–K886) |

## Supporting Experiments (K Index)

| K | Market | Key Result |
|---|--------|-----------|
| K874c | TAIFEX | Baseline PRG estimation |
| K874d | TAIFEX | DM t=5.10 PASS (fair comparison) |
| K874e | TAIFEX | Full 5-model horse race |
| K880 | SPY | DM t=6.00 PASS |
| K880b | SPY | ES evaluation |
| K880v2 | SPY | Denominator-fix confirmation |
| K881 | QQQ/GLD/EEM | All Harvey PASS |
| K881b | QQQ/GLD/EEM | ES evaluation |
| K883 | TAIFEX tick | High-frequency PRG |
| K884 | SPY | HAR day/night decomposition |
| K886 | 0050.TW | DM t=5.27 PASS |
