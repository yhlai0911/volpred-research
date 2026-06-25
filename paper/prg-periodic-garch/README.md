# Paper 6: Periodic Realized GARCH — Session-Boundary Information Transfers

**Target Journal**: Finance Research Letters (FRL)

> **Status override (2026-06-24)**: The older submission-ready status below is
> superseded by K1544 (`experiments/k1544_prg_fair_info_gjr/`). A true
> current-overnight GJR-X benchmark beats canonical PRG Extended under the old
> `h_overnight + h_intraday` timing convention, while PRG only regains the
> advantage under an explicit full-day-at-open `x_overnight + h_intraday`
> convention. Do not submit or add body-level reinforcement until the
> forecast-timing narrative is decided.

**Status**: ✅ **Submission-ready (all clear)** (2026-04-19 final pass: Codex P10 audit 2 blockers RESOLVED (PRS continuity §6 + 11pt/≤15pp) + v2 revise 2 MAJOR Fix B + 6 MED + 10 MINOR + 17/17 DOIs + citation_check.md synced + main.pdf 13pp A4 11pt + **reproduce gate 100% GREEN 15/15** after DM_t tolerance calibration reflecting yfinance retroactive drift (0.10 → 0.15/0.20, all Harvey |t|>3 qualitative claims intact)).
**Pages**: 13 | **Citations**: 19

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
