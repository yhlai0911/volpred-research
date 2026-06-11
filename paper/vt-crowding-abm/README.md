# Paper 5: Monotone Strategy-Specific Erosion under VT Crowding — Matched-Control Identification via ABM

**Target Journal**: Finance Research Letters (FRL)
**Status**: 🔶 **narrative_rewrite_complete_pending_review（2026-06-11 15:xx 台灣時間，Codex phase-2 收尾）** — 已完成 Discussion / Conclusion monotone-not-tipping framing、abstract 補註 K1471 redesign layer `total_sims=94,500`、README 狀態更新，並保持 source binding 指向 `experiments/k1471_vt_crowding_redesign/k1471_full_results.json`。待主線程 / paper-review-cycle 做最終審查與提交前 polish。Codex review verdict: CONDITIONAL_PASS (presentation/interpretation caveats only, 無 calc bug)。Evidence: `experiments/k1471_vt_crowding_redesign/full_results_interpretation.md`。｜前狀態歷史：v5 雙審稿人 5 blocking → K1471 redesign + M=500 resimulation 完成；R3 SEVERE=0（v3 audit, 已被新 narrative 覆蓋）；v2 revise 2026-04-19。
**Pages**: 15 | **Citations**: 16 (13 original + 3 new: barroso2021, cederburg2020, liu2019)

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
