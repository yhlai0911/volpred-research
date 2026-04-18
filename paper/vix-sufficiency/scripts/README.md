# Paper 4: Scripts / Reproduction Guide

---

## Primary Scripts (paper root)

| Script | Location | Purpose |
|--------|----------|---------|
| `reproduce.py` | `paper/vix-sufficiency/` | Main reproduction pipeline: re-runs core 11-family signal evaluation |

## Experiment Scripts (experiments/kXXX/)

All signal family and compendium experiments are in their respective directories.
See `experiments.md` for full K-number index.

### Core 11-Family Signal Evaluation

| Script | Experiment | Family |
|--------|-----------|--------|
| `k730_cross_asset_vol_momentum.py` | `paper/vix-sufficiency/experiments/` | Family 1: cross-asset vol momentum |
| `k731_vix_term_structure.py` | `paper/vix-sufficiency/experiments/` | Family 2: VIX term structure |
| `k732_pcr_behavioral_sentiment.py` | `paper/vix-sufficiency/experiments/` | Family 3: behavioral sentiment |
| `k752_vix_sufficiency_eras.py` | `paper/vix-sufficiency/experiments/` | Era stability test (Table 5) |
| `k799_grand_evaluation.py` | `paper/vix-sufficiency/experiments/` | Grand QLIKE + MCS evaluation |
| `k824v2_quantile_fixed.py` | `paper/vix-sufficiency/experiments/` | VaR/ES backtest (Table 4) |

### Alt-Data Compendium (2026-04-13+)

| Script | Experiment | Purpose |
|--------|-----------|---------|
| `experiments/k1116/k1116.py` | K1116 | SPY + EPU/NFCI/STLFSI alt-data weekly DM |
| `experiments/k1117/k1117.py` | K1117 | Conditional null on VIX jump days |
| `experiments/k1118/k1118.py` | K1118 | Cross-asset (SPY/GLD/TLT) alt-data |
| `experiments/k1121/k1121.py` | K1121 | Alt-data portfolio allocation 2-asset |
| `experiments/k1123/k1123.py` | K1123 | Alt-data portfolio allocation 3-asset |
| `experiments/k504/k504_stlfsi_strategy.py` | K504 | STLFSI4 macro-stress VT |

### 2026-04-17 Robust Models Compendium

| Script | Experiment | Purpose |
|--------|-----------|---------|
| `experiments/k1129/k1129.py` | K1129 | GAS-t commodity (32 tests) |
| `experiments/k1135/k1135.py` | K1135 | Commodity skew-t GAS VaR/ES |
| `experiments/k1136/k1136.py` | K1136 | HAR-RV-X + MIDAS commodity compendium |
| `experiments/k1137/k1137.py` | K1137 | Regime-invariant HAR (Verdict C) |
| `experiments/k1138/k1138.py` | K1138 | Equity compendium (SPY/QQQ/IWM) |
| `experiments/k1139/k1139.py` | K1139 | VIX component decomposition |
| `experiments/k1143/k1143.py` | K1143 | GAS-t equity harm mechanism |

## Full Reproduction Sequence

```bash
# Step 1: Core 11-family horse race
uv run python paper/vix-sufficiency/reproduce.py

# Step 2: Alt-data compendium (K1116 → K1123)
uv run python experiments/k1116/k1116.py
uv run python experiments/k1117/k1117.py
uv run python experiments/k1118/k1118.py
uv run python experiments/k1121/k1121.py
uv run python experiments/k1123/k1123.py

# Step 3: Robust models compendium (K1129 → K1143)
uv run python experiments/k1129/k1129.py
uv run python experiments/k1135/k1135.py
uv run python experiments/k1136/k1136.py
uv run python experiments/k1137/k1137.py
uv run python experiments/k1138/k1138.py
uv run python experiments/k1139/k1139.py
uv run python experiments/k1143/k1143.py
```

## Dependencies

```
yfinance >= 0.2.40
arch >= 6.3.0
scipy >= 1.12
statsmodels >= 0.14
fredapi >= 0.5.0
pytrends >= 4.9.2
numpy >= 1.26
pandas >= 2.1
matplotlib >= 3.8
```

Install: `uv pip install yfinance arch scipy statsmodels fredapi pytrends`
