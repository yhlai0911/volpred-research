# Paper 5: Monotone Strategy-Specific Erosion under VT Crowding — Matched-Control Identification via ABM

**Target Journal**: Finance Research Letters (FRL)
**Status**: 🔶 **body_rewrite_in_progress（2026-06-11 14:15 台灣時間，主線程 hourly-14）** — 已完成 title + abstract + intro 段落 3-4 narrative rewrite（撤回 70% tipping → monotone strategy-specific erosion + matched-control identification 主貢獻）；xelatex compile 26 pages exit OK。**待 followup task（下班 fire）**：(a) Model section 引入 RR_* matched-control 設定；(b) Results section 重寫（threshold table 加 direction 欄 + grid artifact 揭露 + 不顯著 cells 不列 interval + RR_MR/TF cell2 病態 regime 排除）；(c) Discussion / Conclusion 對齊 monotone-not-tipping framing；(d) abstract sim count 94,500 對應 Methodology 補述；(e) `% source:` binding 全文掃描更新指向 `experiments/k1471_vt_crowding_redesign/k1471_full_results.json`。Codex review verdict: CONDITIONAL_PASS (5 HIGH 全 presentation/interpretation, 無 calc bug)。Evidence: `experiments/k1471_vt_crowding_redesign/full_results_interpretation.md`。｜前狀態歷史：v5 雙審稿人 5 blocking → K1471 redesign + M=500 resimulation 完成；R3 SEVERE=0（v3 audit, 已被新 narrative 覆蓋）；v2 revise 2026-04-19。
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
