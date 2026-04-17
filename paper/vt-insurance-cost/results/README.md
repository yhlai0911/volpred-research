# Paper 4: Results Index

**Paper**: The True Cost of Volatility Targeting — Insurance Premium Decomposition
**Results Last Updated**: 2026-04-17

---

## Tables → Source Mapping

| Table | Description | Source File / Experiment |
|-------|-------------|--------------------------|
| Table 1 | Strategy Performance: Full Sample (2012–2024) | `paper/vt-insurance-cost/experiments/k811v2_th0_5_results.json` + `k811v2_th1_0_results.json` |
| Table 2 | Insurance Premium Decomposition (%/year) | `paper/vt-insurance-cost/experiments/k811v2_insurance_premium_vov_fixed_results.json` |

---

## Key JSON Results Files

| File | Location | Contents |
|------|----------|----------|
| `k811_insurance_premium_vov_results.json` | `paper/vt-insurance-cost/experiments/` | K811 original VoV decomposition (pilot; superseded) |
| `k811v2_insurance_premium_vov_fixed_results.json` | `paper/vt-insurance-cost/experiments/` + `experiments/k811v2/` | K811v2 main Table 2 results |
| `k811v2_th0_5_results.json` | `paper/vt-insurance-cost/experiments/` | Threshold σ×0.5 sensitivity |
| `k811v2_th1_0_results.json` | `paper/vt-insurance-cost/experiments/` | Threshold σ×1.0 (base case) |
| `k811v2_th1_5_results.json` | `paper/vt-insurance-cost/experiments/` | Threshold σ×1.5 sensitivity |
| `k811v2_sensitivity_sweep.json` | `paper/vt-insurance-cost/experiments/` + `experiments/k811v2/` | Full parameter sweep |
| `k846_rebalancing_premium_results.json` | `paper/vt-insurance-cost/experiments/` | K846 rebalancing premium component |
| `k860_results.json` | `paper/vt-insurance-cost/experiments/` | K860 prospect theory extension |

---

## Figures

No `\includegraphics` commands in main.tex — all results are tabular.
`figures/` directory created as placeholder.

---

## Number Traceability

All numbers verified with 0 mismatches (see `reviews/audit_step1_2.md`).

Key verified numbers:
- Table 1: Strategy performance (Sharpe, return, max drawdown) for VT vs buy-and-hold (2012–2024)
- Table 2: Insurance premium decomposition (volatility-of-volatility premium, rebalancing premium, total)

---

## Reproduction

```bash
# Main result (Table 2)
uv run python paper/vt-insurance-cost/experiments/k811v2_main.py

# Full sensitivity sweep
uv run python paper/vt-insurance-cost/experiments/sensitivity_sweep.py
```

Data: SPY/GLD/VIX 2012–2024 (in `data/` folder — pre-downloaded CSVs).
