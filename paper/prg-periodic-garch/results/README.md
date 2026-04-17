# Paper 6: Results Index

**Paper**: Periodic Realized GARCH — Session-Boundary Information Transfers
**Results Last Updated**: 2026-04-17

---

## Tables → Source Mapping

| Table | Description | Source File / Experiment |
|-------|-------------|--------------------------|
| Table 1 | Data summary and session decomposition | K883 (`k883_results.json`) + K880 (`k880_results.json`) |
| Table 2 | Out-of-sample QLIKE and DM tests across six markets | K874d, K880, K881, K886 results JSON |
| Table 3 | Ablation study: removing session-boundary update (SPY) | K880v2 (`k880v2_results.json`) |
| Table 4 | VaR (1%) and ES evaluation | K880b (`k880b_results.json`), K881b (`k881b_results.json`) |
| Table 5 | Volatility-timing strategy performance on TAIFEX TX | K874d/K883 results JSON |

---

## Key JSON Results Files

| File | Location | Contents |
|------|----------|----------|
| `k874c_results.json` | `paper/prg-periodic-garch/experiments/` | K874c baseline QLIKE |
| `k874d_results.json` | `paper/prg-periodic-garch/experiments/` | K874d fair comparison; TAIFEX DM t=5.10 |
| `k874e_results.json` | `paper/prg-periodic-garch/experiments/` | K874e full 5-model comparison |
| `k880_results.json` | `paper/prg-periodic-garch/experiments/` | K880 SPY OOS; DM t=6.00 |
| `k880b_results.json` | `paper/prg-periodic-garch/experiments/` | K880b ES evaluation |
| `k880v2_results.json` | `paper/prg-periodic-garch/experiments/` | K880v2 denominator-fixed |
| `k881_results.json` | `paper/prg-periodic-garch/experiments/` | K881 QQQ/GLD/EEM; all Harvey PASS |
| `k881b_results.json` | `paper/prg-periodic-garch/experiments/` | K881b ES multi-asset |
| `k883_results.json` | `paper/prg-periodic-garch/experiments/` | K883 TAIFEX tick PRG |
| `k884_har_day_night_results.json` | `paper/prg-periodic-garch/experiments/` | K884 HAR day/night decomposition |
| `k886_prg_0050tw_results.json` | `paper/prg-periodic-garch/experiments/` | K886 0050.TW; DM t=5.27 |

---

## Figures → Source Mapping

| Figure | Description | Source |
|--------|-------------|--------|
| Fig. 1 | QLIKE comparison: PRG vs benchmarks (SPY) | `experiments/k880_charts/qlike_comparison.png` |
| Fig. 2 | Rolling QLIKE ratio (SPY) | `experiments/k880_charts/rolling_qlike_ratio.png` |
| Fig. 3 | Multi-asset DM heatmap | `experiments/k881_charts/dm_heatmap.png` |
| Fig. 4 | QLIKE all assets comparison | `experiments/k881_charts/qlike_all_assets.png` |

---

## Reproduction

```bash
# Full pipeline (all 6 markets)
uv run python paper/prg-periodic-garch/reproduce.py

# Individual experiments
uv run python paper/prg-periodic-garch/experiments/k880_prg_spy_validation.py
uv run python paper/prg-periodic-garch/experiments/k881_prg_multi_asset.py
uv run python paper/prg-periodic-garch/experiments/k886_prg_0050tw.py
```

OOS periods vary by market:
- TAIFEX: 2018–2026
- SPY/QQQ/GLD/EEM: 2018–2026
- 0050.TW: 2018–2026
