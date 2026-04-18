# Paper 6: Scripts / Reproduction Guide

---

## Primary Scripts (paper root)

| Script | Location | Purpose | Runtime |
|--------|----------|---------|---------|
| `reproduce.py` | `paper/prg-periodic-garch/` | Main reproduction pipeline: re-runs core PRG validation across 6 markets | ~15 min |

## Experiment Scripts (paper/prg-periodic-garch/experiments/)

All core model estimation and evaluation scripts are co-located in the paper's `experiments/` sub-folder:

| Script | Experiment | Purpose |
|--------|-----------|---------|
| `k874c_periodic_realized_garch.py` | K874c | Original PRG estimation on TAIFEX TX; baseline QLIKE comparison |
| `k874d_fair_comparison.py` | K874d | Corrected denominator-consistent evaluation; TAIFEX DM t=5.10 |
| `k874e_full_comparison.py` | K874e | Full 5-model horse race (PRG vs HAR/RV-GARCH/EGARCH/GJR) |
| `k880_prg_spy_validation.py` | K880 | SPY OOS validation; DM t=6.00; main cross-market result |
| `k880b_es_supplement.py` | K880b | ES evaluation for SPY (UC/CC/DQ tests at 1%/5%) |
| `k880v2_prg_fixed.py` | K880v2 | Denominator-fix version confirming OOS improvement |
| `k881_prg_multi_asset.py` | K881 | QQQ/GLD/EEM multi-asset validation |
| `k881b_multi_asset_es.py` | K881b | ES evaluation for QQQ/GLD/EEM |
| `k883_taifex_tick_prg.py` | K883 | High-frequency tick-based PRG on TAIFEX TX |
| `k884_har_day_night.py` | K884 | HAR day-night session decomposition analysis |
| `k886_prg_0050tw.py` | K886 | 0050.TW (Taiwan ETF) PRG validation; DM t=5.27 |

## Full Reproduction Sequence

```bash
# Step 1: TAIFEX baseline (requires ~/Dropbox/TAIFEXDATA/)
uv run python paper/prg-periodic-garch/experiments/k874d_fair_comparison.py
uv run python paper/prg-periodic-garch/experiments/k874e_full_comparison.py

# Step 2: SPY cross-market validation
uv run python paper/prg-periodic-garch/experiments/k880_prg_spy_validation.py
uv run python paper/prg-periodic-garch/experiments/k880b_es_supplement.py

# Step 3: Multi-asset robustness (QQQ/GLD/EEM)
uv run python paper/prg-periodic-garch/experiments/k881_prg_multi_asset.py
uv run python paper/prg-periodic-garch/experiments/k881b_multi_asset_es.py

# Step 4: Taiwan ETF validation (0050.TW)
uv run python paper/prg-periodic-garch/experiments/k886_prg_0050tw.py
```

## Dependencies

```
yfinance >= 0.2.40
arch >= 6.3.0
scipy >= 1.12
statsmodels >= 0.14
numpy >= 1.26
pandas >= 2.1
matplotlib >= 3.8
```

Install: `uv pip install yfinance arch scipy statsmodels numpy pandas matplotlib`

## Notes

- TAIFEX data requires local `~/Dropbox/TAIFEXDATA/` access (not redistributable).
- All yfinance-based markets (SPY/QQQ/GLD/EEM/0050.TW) reproduce automatically.
- Results JSON files are pre-computed and stored in `paper/prg-periodic-garch/experiments/`.
