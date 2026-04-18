# Paper 6: Supporting Experiments Index

**Paper**: Periodic Realized GARCH — Session-Boundary Information Transfers
**Journal**: Finance Research Letters (FRL)
**Status**: Near submission-ready (R2 SEVERE=0)
**Last Updated**: 2026-04-17

---

## Core Experiments

| K | Title | Contribution | Path |
|---|-------|-------------|------|
| K874c | Periodic Realized GARCH (base) | Original PRG estimation; QLIKE benchmarking vs HAR/RV-GARCH on TAIFEX TX | `experiments/k874c/` |
| K874d | Fair Comparison (methodology correction) | Corrected denominator-consistent OOS evaluation; DM t=5.10 TAIFEX PASS | `experiments/k874d/` |
| K874e | Full Model Comparison | Comprehensive 5-model horse race (PRG vs HAR/RV-GARCH/EGARCH/GJR) | `experiments/k874e/` |
| K880 | PRG SPY Validation | SPY out-of-sample validation; DM t=6.00 PASS; overnight session transfer confirmed | `experiments/k880/` |
| K880b | ES Supplement (SPY) | ES evaluation complement to VaR; UC/CC/DQ tests | `experiments/k880/` |
| K880v2 | PRG Fixed (denominator fix) | Confirmed OOS improvement after denominator consistency fix | `experiments/k880v2/` |
| K881 | PRG Multi-Asset | QQQ/GLD/EEM cross-asset validation; all Harvey PASS | `experiments/k881/` |
| K881b | Multi-Asset ES Supplement | ES evaluation for all 3 cross-asset markets | `experiments/k881/` |
| K883 | TAIFEX Tick PRG | High-frequency tick-data PRG on TAIFEX TX futures | `experiments/k883/` |
| K884 | HAR Day-Night | HAR decomposition for daytime vs overnight session returns | `experiments/k884/` |
| K886 | PRG 0050.TW | 0050.TW (Taiwan equity ETF) PRG validation; DM t=5.27 PASS | `experiments/k886/` |

---

## Experiment Scripts (paper/prg-periodic-garch/experiments/)

These scripts are co-located in the paper folder for convenience. They mirror or extend the above experiments:

| Script | Description |
|--------|-------------|
| `k874c_periodic_realized_garch.py` | K874c replication |
| `k874d_fair_comparison.py` | K874d fair comparison |
| `k874e_full_comparison.py` | K874e full 5-model comparison |
| `k880_prg_spy_validation.py` | K880 SPY validation |
| `k880b_es_supplement.py` | K880b ES supplement |
| `k880v2_prg_fixed.py` | K880v2 denominator fix |
| `k881_prg_multi_asset.py` | K881 multi-asset |
| `k881b_multi_asset_es.py` | K881b ES for multi-asset |
| `k883_taifex_tick_prg.py` | K883 TAIFEX tick PRG |
| `k884_har_day_night.py` | K884 HAR day/night decomposition |
| `k886_prg_0050tw.py` | K886 0050.TW validation |

---

## Table → Experiment Mapping

| Table | Caption | Source Experiment |
|-------|---------|------------------|
| Table 1 | Data summary and session decomposition | K883 (TAIFEX tick data), K880 (SPY) |
| Table 2 | Out-of-sample QLIKE and DM tests across six markets | K874d (TAIFEX), K880 (SPY), K881 (QQQ/GLD/EEM), K886 (0050.TW) |
| Table 3 | Ablation study: removing session-boundary update (SPY) | K880v2 |
| Table 4 | VaR (1%) and ES evaluation | K880b (SPY), K881b (cross-asset) |
| Table 5 | Volatility-timing strategy performance on TAIFEX TX | K874d/K883 |

---

## Figure → Experiment Mapping

| Figure | Caption | Source |
|--------|---------|--------|
| Fig. 1 | QLIKE comparison (PRG vs benchmarks) | `experiments/k880_charts/qlike_comparison.png` |
| Fig. 2 | Rolling QLIKE ratio | `experiments/k880_charts/rolling_qlike_ratio.png` |
| Fig. 3 | Multi-asset DM heatmap | `experiments/k881_charts/dm_heatmap.png` |
| Fig. 4 | QLIKE all assets | `experiments/k881_charts/qlike_all_assets.png` |

---

## Orphan / TODO Notes

- `paper/prg-periodic-garch/figures/` directory not yet created — figures currently referenced from `experiments/kXXX_charts/`. [TODO: create figures/ with soft-links]
- K884 HAR day-night results are supplementary; not directly cited in main.tex tables but inform methodology discussion.
