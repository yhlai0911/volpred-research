# Paper 5: Results Index

**Paper**: When Volatility Targeting Crowds — Quantifying the Tipping Point via ABM
**Results Last Updated**: 2026-04-17

---

## Tables → Source Mapping

| Table | Description | Source File / Experiment |
|-------|-------------|--------------------------|
| Table 1 | VT Strategy and Market Outcomes by Adoption Level | `paper/vt-crowding-abm/experiments/k827v3_abm_fixed_liquidity_results.json` |
| Table 2 | Market Microstructure Effects of VT Crowding | `experiments/k864/k864_results.json` |
| Table 3 | Sensitivity of VT Tipping Point to Key Parameters | `paper/vt-crowding-abm/experiments/k827v2_abm_sensitivity_results.json` |

---

## Key JSON Results Files

| File | Location | Contents |
|------|----------|----------|
| `k827_abm_vt_crowding_results.json` | `paper/vt-crowding-abm/experiments/` | K827 base simulation: adoption 0–100%, Sharpe by level |
| `k827v2_abm_sensitivity_results.json` | `paper/vt-crowding-abm/experiments/` | K827v2 OAT sensitivity: 9 parameter variations |
| `k827v3_abm_fixed_liquidity_results.json` | `paper/vt-crowding-abm/experiments/` | K827v3 fixed liquidity: main Table 1 results |
| `k864_results.json` | `experiments/k864/` | K864 heterogeneous agents: Table 2 microstructure |

---

## Figures

No `\includegraphics` commands in main.tex — all results are tabular.
`figures/` directory created as placeholder.
[TODO: figures may be added in revision]

---

## Key Results

| Adoption Level | Sharpe Ratio | Flash Crash Risk |
|---------------|-------------|-----------------|
| 10–20% | ~0.50 (safe) | None |
| 50% | ~0.20 (degraded) | Occasional |
| 70%+ | Negative | Frequent |

Tipping point: 50–70% VT adoption.

---

## Reproduction

```bash
uv run python paper/vt-crowding-abm/reproduce.py
```

All simulation is agent-based (no external data required).
