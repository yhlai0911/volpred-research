# Paper 5: Monotone Strategy-Specific Erosion under VT Crowding — Matched-Control Identification via ABM

**Target Journal**: Quantitative Finance (QF; primary) → JEBO (secondary); FRL only as fast-track fallback with heavy cuts
**Status**: 🔶 **VT-only revision in progress（2026-07-14）** — P0-1~P0-4 完成：敘事單一化、scope 收斂 VT-only（family ordering 全面撤回，含 conclusion / knife-edge 節殘留清除）、K1471 TF/MR 誠實補報（tab:tfmr_gate + RR_TF erosion）、reproduce gate 173/173 GREEN + PDF 零內部路徑洩漏、P0-5 機械批次（redesign-layer §2 描述、sims 口徑、Bonferroni 句、Kyle 頁碼、bib 排序、本 README）。剩：v6 跨模型獨立 review（同模型自審不算）→ QF compliance gate。v4 GREEN PASS 已作廢（同模型自審假陽性第三例）。
**Pages**: 34 | **Citations**: 22 bibitems

## Data Sources
- Agent-based simulation (no external data needed)
- K827v3: Fixed liquidity ABM with 9 OAT parameter variations

## Reproduction
```bash
uv run python paper/vt-crowding-abm/reproduce.py
```

## Key Results (post-K1471 redesign, 2026-06-11)
- **No discrete tipping point**: sup-Wald exogenous detector rejects flatness (p ≤ 0.003 in 5/5 microstructure cells) but identifies no internal break; "70% threshold" was a circular Sharpe-only-detector artifact.
- **VT Sharpe monotonically erodes**: canonical cell ($\lambda=0.005$, $\gamma=200$) Sharpe 0.510 @ 10% → -0.271 @ 100%; adjacent path-bootstrap 95% CIs separate from 40% onward; max marginal degradation in (70%, 100%].
- **Mechanism = systematic direction of vol-feedback, not crowded flow per se**: turnover-matched random-direction control RR_VT (same footprint, randomized direction) shows zero degradation in all 5 cells (Sharpe actually improves +0.06~0.09). Cleaner counterfactual than NoiseControl baseline.
- **Original "70%" survives only as descriptive level-crossing** (relative drop >70%) in 3 of 5 cells (cell1/3/5).
- **TF/MR family-level evidence qualified**: RR_MR matched-control fails in pathological regime (treatment-input gate failure); TF cell2 pathological regime excluded. Family-level claim weaker than v5.

## Self-Contained Index (2026-04-17)

| File | Status |
|------|--------|
| `data_sources.md` | ✅ Pure simulation — no external data |
| `scripts/README.md` | ✅ Reproduction guide for all ABM experiments |
| `results/README.md` | ✅ Table → JSON source mapping |
| `figures/` | ✅ Directory created (no figures in current draft) |
| `experiments.md` | ✅ Full K-number index (K827–K864) |

## Supporting Experiments (K Index)

| K | Title | Key Result |
|---|-------|-----------|
| K827 | ABM VT Crowding (base) | Original simulation baseline |
| K827v2 | ABM Sensitivity | OAT 9-parameter sweep (Table 3) |
| K827v3 | ABM Fixed Liquidity | Main results: tipping point 50–70% |
| K864 | Heterogeneous ABM | Microstructure effects (Table 2) |
